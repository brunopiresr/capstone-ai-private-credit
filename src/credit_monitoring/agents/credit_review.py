"""Three bounded PydanticAI roles with full, validated analytical explanations."""

import asyncio
import json
from collections.abc import Callable
from time import perf_counter

from pydantic_ai import Agent, ModelRetry, RunContext, ToolOutput
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage, UsageLimits

from credit_monitoring.agents.models import (
    DEFAULT_MODEL,
    ModelFailure,
    check_response,
    model_identity,
    resolve_model,
)
from credit_monitoring.agents.prompts.credit_review import (
    BEARISH_INSTRUCTIONS,
    BULLISH_INSTRUCTIONS,
    CREDIT_REVIEW_PROMPT_VERSION,
    RECOMMENDATION_INSTRUCTIONS,
)
from credit_monitoring.config.settings import CreditReviewSettings
from credit_monitoring.domain.credit_review import (
    CreditRecommendation,
    ExposureDecisionContext,
    PerspectiveAssessment,
    PerspectiveResult,
    ReviewAction,
    ReviewExecution,
    ReviewRole,
    ReviewSnapshot,
)

type ReviewOutput = PerspectiveAssessment | CreditRecommendation


def _validate_references(references: tuple[str, ...], snapshot: ReviewSnapshot) -> None:
    if unknown := set(references) - {item.evidence_id for item in snapshot.evidence}:
        raise ValueError(f"Unknown evidence references: {sorted(unknown)}")


def _validate_perspective(output: PerspectiveAssessment, snapshot: ReviewSnapshot) -> None:
    for claim in (*output.arguments, *output.counterevidence):
        _validate_references(claim.evidence_ids, snapshot)


def _error_code(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, ModelFailure):
        return error.code
    if isinstance(error, UsageLimitExceeded):
        return "request_limit"
    if isinstance(error, UnexpectedModelBehavior):
        return "invalid_output"
    if isinstance(error, ModelAPIError):
        return "model_api_error"
    return "model_error"


class _ReviewAgent:
    """Shared execution mechanics only; role mandates and output contracts stay explicit."""

    role: ReviewRole
    instructions: str

    def __init__(
        self, *, model: Model | str = DEFAULT_MODEL, settings: CreditReviewSettings | None = None
    ) -> None:
        self.model = model
        self.settings = CreditReviewSettings.model_validate(
            (settings or CreditReviewSettings()).model_dump()
        )

    def skipped(self, code: str) -> ReviewExecution:
        return ReviewExecution(
            role=self.role,
            status="skipped",
            model=model_identity(self.model),
            prompt_version=CREDIT_REVIEW_PROMPT_VERSION,
            error_code=code,
        )

    async def _run(
        self,
        payload: dict,
        output_type: type[PerspectiveAssessment] | type[CreditRecommendation],
        validate: Callable[[ReviewOutput], None],
    ) -> tuple[ReviewOutput | None, ReviewExecution]:
        usage = RunUsage()
        started = perf_counter()
        response_id, code, output = None, None, None
        try:
            async with asyncio.timeout(self.settings.timeout_seconds):
                agent = Agent(
                    resolve_model(self.model),
                    name=f"Credit review: {self.role}",
                    instructions=self.instructions,
                    output_type=ToolOutput(output_type, name="final_result", strict=True),
                    retries={"output": self.settings.output_retries},
                )
                agent.instrument = False

                @agent.output_validator
                def validate_output(ctx: RunContext, candidate: ReviewOutput) -> ReviewOutput:
                    check_response(ctx.messages[-1])
                    try:
                        validate(candidate)
                    except ValueError as error:
                        raise ModelRetry(str(error)) from error
                    return candidate

                async with agent.iter(
                    json.dumps(payload, sort_keys=True, allow_nan=False),
                    usage=usage,
                    usage_limits=UsageLimits(request_limit=self.settings.output_retries + 1),
                ) as run:
                    async for node in run:
                        if Agent.is_call_tools_node(node):
                            # Reject refusals/partial responses before output dispatch or retries.
                            check_response(node.model_response)
                    result = run.result
                if result is None:
                    raise ModelFailure("Model run did not complete.", "model_incomplete")
                check_response(result.response)
                response_id = result.response.provider_response_id
                output = result.output
        except Exception as error:
            code = _error_code(error)
            response_id = getattr(error, "response_id", None)
        execution = ReviewExecution(
            role=self.role,
            status="failed" if code else "complete",
            model=model_identity(self.model),
            prompt_version=CREDIT_REVIEW_PROMPT_VERSION,
            elapsed_seconds=perf_counter() - started,
            requests=usage.requests,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            response_id=response_id,
            error_code=code,
        )
        return output, execution


class _PerspectiveAgent(_ReviewAgent):
    async def assess_async(
        self, snapshot: ReviewSnapshot, decision_context: ExposureDecisionContext | None
    ) -> PerspectiveResult:
        output, execution = await self._run(
            {
                "evidence_snapshot": snapshot.prompt_context(),
                "decision_context": decision_context.model_dump(mode="json")
                if decision_context
                else None,
            },
            PerspectiveAssessment,
            lambda candidate: _validate_perspective(candidate, snapshot),
        )
        return PerspectiveResult(perspective=self.role, analysis=output, execution=execution)


class BullishCreditAgent(_PerspectiveAgent):
    role = "bullish"
    instructions = BULLISH_INSTRUCTIONS


class BearishCreditAgent(_PerspectiveAgent):
    role = "bearish"
    instructions = BEARISH_INSTRUCTIONS


class CreditRecommendationAgent(_ReviewAgent):
    role = "recommendation"
    instructions = RECOMMENDATION_INSTRUCTIONS

    async def recommend_async(
        self,
        snapshot: ReviewSnapshot,
        decision_context: ExposureDecisionContext | None,
        perspectives: tuple[PerspectiveResult, PerspectiveResult],
        allowed_actions: tuple[ReviewAction, ...],
    ) -> tuple[CreditRecommendation | None, ReviewExecution]:
        arguments = {
            (perspective.perspective, argument.argument_id)
            for perspective in perspectives
            if perspective.analysis is not None
            for argument in perspective.analysis.arguments
        }

        def validate(candidate: CreditRecommendation) -> None:
            if candidate.action not in allowed_actions:
                raise ValueError(f"Action must be one of {allowed_actions}.")
            judgments = [
                (item.perspective, item.argument_id) for item in candidate.argument_judgments
            ]
            if len(judgments) != len(set(judgments)) or set(judgments) != arguments:
                raise ValueError(
                    "Judge every supplied argument exactly once, using its role and ID."
                )
            if candidate.action != "defer" and not candidate.evidence_ids:
                raise ValueError("A substantive recommendation requires evidence references.")
            _validate_references(candidate.evidence_ids, snapshot)
            for judgment in candidate.argument_judgments:
                _validate_references(judgment.evidence_ids, snapshot)
            if (
                any(item.analysis is None for item in perspectives)
                and candidate.confidence != "low"
            ):
                raise ValueError("A failed reviewer requires low confidence.")

        return await self._run(
            {
                "evidence_snapshot": snapshot.prompt_context(),
                "decision_context": decision_context.model_dump(mode="json")
                if decision_context
                else None,
                "perspectives": [item.model_dump(mode="json") for item in perspectives],
                "allowed_actions": allowed_actions,
            },
            CreditRecommendation,
            validate,
        )
