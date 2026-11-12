"""Per-question evidence and outcome assembly; never model-authored provenance."""

import json
from dataclasses import dataclass, field

from pydantic_ai.messages import ModelMessage
from pydantic_ai.usage import RunUsage

from credit_monitoring.agents.answer_contract import (
    SCHEMA_VERSION,
    markdown_literal,
    render_content,
)
from credit_monitoring.agents.evidence import EvidenceRegistry
from credit_monitoring.agents.source_tables import materialize_source_tables
from credit_monitoring.agents.tools.sources import result_sources
from credit_monitoring.domain.agent import (
    AgentAnswer,
    AnswerContent,
    AnswerDraft,
    SourceReference,
    ToolExecution,
)
from credit_monitoring.domain.tool_results import ToolOutcome


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
    borrower_id: str | None = None
    ticker: str | None = None
    evidence: EvidenceRegistry = field(default_factory=EvidenceRegistry)
    model_usage: RunUsage = field(default_factory=RunUsage)

    def finalize(self, draft: AnswerDraft) -> AnswerContent:
        return render_content(materialize_source_tables(draft, self.evidence))

    def preview(self, draft: AnswerDraft) -> AnswerContent:
        return render_content(materialize_source_tables(draft, self.evidence, partial=True))

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
        self.evidence.record(execution.outcome, borrower_id=self.borrower_id, ticker=self.ticker)
        for reference in execution.sources:
            self.sources[(reference.document_id, reference.citation)] = reference.model_copy(
                deep=True
            )
        return execution

    def answer(self, content: AnswerContent | str, error: str | None = None) -> AgentAnswer:
        if isinstance(content, str):
            content = AnswerContent(
                summary=content, answer=markdown_literal(content), schema_version=SCHEMA_VERSION
            )
        data = content.model_dump()
        if error:
            data.update(
                confidence=None, confidence_explanation="Confidence unavailable: " + content.summary
            )
        return AgentAnswer(
            **data,
            evidence=list(self.evidence.entries),
            usage={
                "requests": self.model_usage.requests,
                "input_tokens": self.model_usage.input_tokens or None,
                "output_tokens": self.model_usage.output_tokens or None,
            },
            complete=error is None,
            error=error,
            sources=[s.model_copy(deep=True) for s in self.sources.values()],
            tool_trace=[t.model_copy(deep=True) for t in self.trace],
        )
