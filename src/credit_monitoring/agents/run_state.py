"""Per-question evidence and outcome assembly; never model-authored provenance."""

import json
from dataclasses import dataclass, field

from pydantic_ai.messages import ModelMessage
from pydantic_ai.usage import RunUsage

from credit_monitoring.agents.answer_contract import finalize_content
from credit_monitoring.agents.evidence import EvidenceRegistry
from credit_monitoring.agents.request_policy import DispatchPolicy, RequestContext
from credit_monitoring.agents.tools.sources import result_sources
from credit_monitoring.domain.agent import (
    AgentAnswer,
    AnswerContent,
    SourceReference,
    ToolExecution,
)
from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.domain.tool_results import FinancialReview, ToolOutcome


def decode_arguments(raw: str) -> dict | None:
    try:
        value = json.loads(raw)
    except TypeError, json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


@dataclass
class AgentRunState:
    max_tool_rounds: int
    tool_rounds: int = 0
    trace: list[ToolExecution] = field(default_factory=list)
    sources: dict[tuple[str, str], SourceReference] = field(default_factory=dict)
    history: list[ModelMessage] = field(default_factory=list)
    policy: DispatchPolicy | None = None
    request: RequestContext | None = None
    output_repairs: int = 0
    has_retained_evidence: bool = False
    evidence: EvidenceRegistry = field(default_factory=EvidenceRegistry)
    model_usage: RunUsage = field(default_factory=RunUsage)

    def finalize(self, content: AnswerContent) -> AnswerContent:
        if self.policy:
            self.policy.validate_final()
        return finalize_content(
            content,
            self.evidence,
            self.request,
            {
                call.outcome.assessment_run_id
                for call in self.trace
                if hasattr(call.outcome, "assessment_run_id")
            },
        )

    def record(
        self, name: str, call_id: str, raw_arguments: str, outcome: ToolOutcome
    ) -> ToolExecution:
        execution = ToolExecution(
            call_id=call_id,
            name=name,
            arguments=decode_arguments(raw_arguments),
            outcome=outcome,
        ).model_copy(deep=True)
        execution.sources = result_sources(execution.outcome)
        self.trace.append(execution)
        if self.request:
            if isinstance(execution.outcome, (FinancialReview, RiskAssessment)) and (
                {
                    "period_end": str(execution.outcome.period_end),
                    "information_cutoff": str(execution.outcome.information_cutoff),
                }
                != self.request.dates
            ):
                raise ValueError("Returned financial evidence does not match the validated dates.")
            self.evidence.record(
                execution.outcome, borrower_id=self.request.borrower_id, ticker=self.request.ticker
            )
        for reference in execution.sources:
            self.sources[(reference.document_id, reference.citation)] = reference.model_copy(
                deep=True
            )
        return execution

    def answer(self, content: AnswerContent | str, error: str | None = None) -> AgentAnswer:
        if isinstance(content, str):
            content = AnswerContent(answer=content)
        return AgentAnswer(
            schema_version=content.schema_version,
            answer_kind=content.answer_kind,
            claims=[claim.model_copy(deep=True) for claim in content.claims],
            evidence=list(self.evidence.entries),
            usage={
                "requests": self.model_usage.requests,
                "input_tokens": self.model_usage.input_tokens or None,
                "output_tokens": self.model_usage.output_tokens or None,
            },
            answer=content.answer,
            confidence=None if error else content.confidence,
            confidence_explanation="Confidence unavailable: " + content.answer
            if error
            else content.confidence_explanation,
            complete=error is None,
            error=error,
            sources=[s.model_copy(deep=True) for s in self.sources.values()],
            tool_trace=[t.model_copy(deep=True) for t in self.trace],
        )
