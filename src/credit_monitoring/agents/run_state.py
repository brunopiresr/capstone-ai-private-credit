"""Per-question execution state, independent of the services used by tools."""

import json
from dataclasses import dataclass, field

from credit_monitoring.domain.agent import AgentAnswer, SourceReference, ToolExecution


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
    arguments: dict[str, str] = field(default_factory=dict)

    def record(self, name: str, call_id: str, raw_arguments: str, outcome: dict) -> str:
        self.trace.append(
            ToolExecution(
                call_id=call_id,
                name=name,
                arguments=decode_arguments(raw_arguments),
                outcome=outcome,
            )
        )
        for source in outcome.get("sources", []):
            reference = SourceReference(**source)
            self.sources[(reference.document_id, reference.citation)] = reference
        return json.dumps(outcome, ensure_ascii=False)

    def answer(self, text: str, error: str | None = None) -> AgentAnswer:
        return AgentAnswer(
            answer=text,
            complete=error is None,
            error=error,
            sources=list(self.sources.values()),
            tool_trace=self.trace,
        )
