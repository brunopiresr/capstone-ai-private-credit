"""Sequential human evaluation using the prepared cases and existing agent factory."""

import importlib.util
import json
import logging
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import logfire

from credit_monitoring.agents.models import DEFAULT_MODEL
from credit_monitoring.observability import SessionContext, session_scope
from credit_monitoring.observability.configuration import (
    capture_content_enabled,
    is_observability_configured,
    span,
)

DATASET = Path(__file__).resolve().parent / "2026-10-26"
_spec = importlib.util.spec_from_file_location(
    "human_evaluation_workbench", DATASET / "workbench.py"
)
workbench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(workbench)
logger = logging.getLogger(__name__)

RESPONSE_CATEGORIES = {
    "correct": "Correct",
    "incorrect": "Incorrect",
    "incomplete": "Incomplete",
    "unsupported_claims": "Unsupported claims",
    "irrelevant": "Irrelevant",
    "unclear": "Unclear",
    "unable_to_evaluate": "Unable to evaluate",
}


def load_cases() -> list[dict]:
    cases = workbench.read_rows(DATASET / "cases.jsonl")
    if len(cases) != 27 or len(workbench.by_id(cases)) != 27:
        raise ValueError("The evaluation dataset must contain 27 unique questions.")
    return cases


@dataclass
class Attempt:
    interaction_id: str
    folder: Path
    answer: dict
    response_sha256: str
    request_context: dict[str, str] | None = None


class EvaluationRound:
    """One browser's round; rerenders reuse answers, retries create fresh attempts."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        cases: list[dict] | None = None,
        output_root: Path | None = None,
        previous_chat_id: str | None = None,
    ):
        self.cases = load_cases() if cases is None else cases
        if not self.cases:
            raise ValueError("The evaluation needs at least one question.")
        self.model = model
        self.session = SessionContext(name="Agent response evaluation")
        self.folder = (output_root or DATASET / "runs") / f"human-{self.session.session_id}"
        self.folder.mkdir(parents=True, exist_ok=False)
        self.index = 0
        self.attempt: Attempt | None = None
        self._ended = False
        self._emit("evaluation.round_started", previous_chat_id=previous_chat_id)

    @classmethod
    def resume(cls, previous):
        """Use updated methods after a Streamlit reload, preserving the active answer."""
        if type(previous) is cls:
            return previous
        current = cls.__new__(cls)
        current.__dict__.update(vars(previous))
        return current

    @property
    def complete(self) -> bool:
        return self.index == len(self.cases)

    @property
    def case(self) -> dict:
        return self.cases[self.index]

    def _emit(self, event_name: str, *, parent_context=None, **attributes) -> None:
        if not is_observability_configured():
            return
        # An exporter failure must not invalidate feedback already saved locally.
        try:
            message = event_name
            if case_id := attributes.get("case_id"):
                message += f" {case_id}"
            if event_name == "user.feedback":
                message += f" · {RESPONSE_CATEGORIES[attributes['category']]}"
            with (
                session_scope(self.session),
                logfire.attach_context(parent_context) if parent_context else nullcontext(),
            ):
                logfire.info(
                    message,
                    event_name=event_name,
                    chat_id=self.session.session_id,
                    model=self.model,
                    event_time=datetime.now(UTC).isoformat(),
                    question_count=len(self.cases),
                    evaluated_count=sum(1 for _ in self.folder.glob("*/*/feedback.json")),
                    processed_count=self.index,
                    **attributes,
                )
        except Exception:
            logger.warning("Evaluation telemetry could not be emitted.")

    async def generate(self) -> Attempt:
        if self.complete:
            raise ValueError("This round is complete.")
        if self.attempt is not None:
            return self.attempt
        case = self.case
        interaction_id = str(uuid4())
        folder = self.folder / case["case_id"] / interaction_id
        folder.mkdir(parents=True)
        workbench.save(folder / "request.json", {"case": case, "model": self.model})
        answer = {"answer": "", "complete": False, "sources": [], "tool_trace": []}
        started = perf_counter()

        async def capture(event):
            if event.kind in {"tool_call", "tool_result", "run_end"}:
                workbench.append(folder / "events.jsonl", event.model_dump(mode="json"))

        with (
            session_scope(self.session),
            span(
                f"evaluation.request {case['case_id']} · {case['feature']}",
                event_name="evaluation.request",
                chat_id=self.session.session_id,
                interaction_id=interaction_id,
                case_id=case["case_id"],
                feature=case["feature"],
            ),
        ):
            # Resume this request when feedback arrives on a later Streamlit rerun.
            # Retain only its carrier; the request span still ends with generation.
            request_context = dict(logfire.get_context()) if is_observability_configured() else None
            self._emit(
                "evaluation.question_started",
                case_id=case["case_id"],
                interaction_id=interaction_id,
                **({"question": case["question"]} if capture_content_enabled() else {}),
            )
            missing = workbench.missing_sources(case)
            if missing:
                answer["error"] = "Missing prepared sources: " + ", ".join(missing)
            else:
                try:
                    agent = workbench.make_agent(case, folder, self.model, tracing_enabled=None)
                    response = await agent.ask_async(
                        case["question"],
                        ticker=case.get("ticker"),
                        borrower_id=case.get("borrower_id"),
                        event_stream_handler=capture,
                    )
                    answer = response.model_dump(mode="json")
                except Exception as failure:
                    answer["error"] = type(failure).__name__
            workbench.save(folder / "answer.json", answer)
            self.attempt = Attempt(
                interaction_id,
                folder,
                answer,
                workbench.fingerprint(folder / "answer.json"),
                request_context,
            )
            self._emit(
                "evaluation.answer_presented",
                case_id=case["case_id"],
                interaction_id=interaction_id,
                response_sha256=self.attempt.response_sha256,
                status="complete" if answer["complete"] else "error",
                error_type=answer.get("error"),
                elapsed_seconds=round(perf_counter() - started, 3),
            )
        return self.attempt

    def retry(self) -> None:
        if self.attempt is None or self.attempt.answer["complete"]:
            raise ValueError("Only a failed answer can be retried.")
        self.attempt = None

    def skip(self) -> None:
        if self.complete:
            raise ValueError("This round is complete.")
        record = {
            "chat_id": self.session.session_id,
            "case_id": self.case["case_id"],
            "model": self.model,
            "status": "skipped",
            "event_time": datetime.now(UTC).isoformat(),
            "interaction_id": self.attempt.interaction_id if self.attempt else None,
        }
        destination = self.folder / self.case["case_id"] / "skip.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            workbench.save(destination, record)
        self._emit(
            "evaluation.question_skipped",
            parent_context=getattr(self.attempt, "request_context", None),
            case_id=record["case_id"],
            interaction_id=record["interaction_id"],
        )
        self.index += 1
        self.attempt = None
        if self.complete:
            self.end("complete")

    def summary(self) -> list[dict]:
        """Collect saved classifications and comments in question order."""
        submitted = {}
        for path in self.folder.glob("*/*/feedback.json"):
            feedback = json.loads(path.read_text())
            submitted[feedback["case_id"]] = {
                **feedback,
                "submitted": True,
            }
        rows = []
        for case in self.cases:
            if case["case_id"] in submitted:
                rows.append(submitted[case["case_id"]])
            elif (self.folder / case["case_id"] / "skip.json").exists():
                rows.append(
                    {
                        "case_id": case["case_id"],
                        "category": None,
                        "comment": "",
                        "submitted": False,
                        "status": "skipped",
                    }
                )
            elif not self.complete and case["case_id"] == self.case["case_id"]:
                rows.append(
                    {
                        "case_id": case["case_id"],
                        "category": None,
                        "comment": "",
                        "submitted": False,
                        "status": "not_run" if self.attempt is None else "unrated",
                    }
                )
        return rows

    def rate(self, category: str, comment: str) -> None:
        if self.attempt is None or not self.attempt.answer["complete"]:
            raise ValueError("Generate a complete answer before rating it.")
        if category not in RESPONSE_CATEGORIES:
            raise ValueError("Choose a response category first.")
        if len(comment) > 2000:
            raise ValueError("Comments must be at most 2000 characters.")
        feedback = {
            "chat_id": self.session.session_id,
            "case_id": self.case["case_id"],
            "interaction_id": self.attempt.interaction_id,
            "response_sha256": self.attempt.response_sha256,
            "model": self.model,
            "category": category,
            "comment": comment,
            "event_time": datetime.now(UTC).isoformat(),
        }
        destination = self.attempt.folder / "feedback.json"
        if destination.exists():
            saved = json.loads(destination.read_text())
            if any(
                saved[key] != feedback[key] for key in ("category", "comment", "response_sha256")
            ):
                raise ValueError("This answer already has different saved feedback.")
        else:
            workbench.save(destination, feedback)
        self._emit(
            "user.feedback",
            parent_context=getattr(self.attempt, "request_context", None),
            case_id=feedback["case_id"],
            interaction_id=feedback["interaction_id"],
            response_sha256=feedback["response_sha256"],
            category=feedback["category"],
            has_comment=bool(comment.strip()),
            **({"comment": comment} if capture_content_enabled() else {}),
        )
        self.index += 1
        self.attempt = None
        if self.complete:
            self.end("complete")

    def end(self, reason: str) -> None:
        if not self._ended:
            self._emit("evaluation.round_ended", end_reason=reason)
            self._ended = True
