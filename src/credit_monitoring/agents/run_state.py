"""Per-question evidence and outcome assembly; never model-authored provenance."""

import json
from dataclasses import dataclass, field

from pydantic_ai.messages import ModelMessage

from credit_monitoring.domain.agent import (
    AgentAnswer,
    AnswerContent,
    SourceReference,
    ToolExecution,
)


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

    def record(self, name: str, call_id: str, raw_arguments: str, outcome: dict) -> None:
        self.trace.append(
            ToolExecution(
                call_id=call_id,
                name=name,
                arguments=decode_arguments(raw_arguments),
                outcome=outcome,
            )
        )
        if outcome.get("ok"):
            for source in outcome.get("sources", []):
                reference = SourceReference(**source)
                self.sources[(reference.document_id, reference.citation)] = reference

    def answer(self, content: AnswerContent | str, error: str | None = None) -> AgentAnswer:
        if isinstance(content, str):
            content = AnswerContent(answer=content)
        values = content.model_dump()
        if error:
            values.update(
                confidence=None, confidence_explanation="Confidence unavailable: " + content.answer
            )
        return AgentAnswer(
            **values,
            complete=error is None,
            error=error,
            sources=[s.model_copy(deep=True) for s in self.sources.values()],
            tool_trace=[t.model_copy(deep=True) for t in self.trace],
        )
