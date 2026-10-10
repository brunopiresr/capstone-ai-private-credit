"""Public agent outcomes contain executed tools and sources, never private reasoning."""

from typing import Any

from pydantic import Field

from .base import ExtractionModel


class SourceReference(ExtractionModel):
    document_id: str = Field(description="Actual document ID supplied by an evidence tool.")
    citation: str = Field(description="Actual citation supplied by an evidence tool.")


class ToolExecution(ExtractionModel):
    call_id: str = Field(description="SDK tool call ID corresponding to its returned output.")
    name: str = Field(description="Requested tool name; unknown names are recorded as errors.")
    arguments: dict[str, Any] | None = Field(
        description="Decoded arguments, or null for malformed JSON/non-object arguments."
    )
    outcome: dict[str, Any] = Field(description="Executed tool result or explicit dispatch error.")


class AgentAnswer(ExtractionModel):
    answer: str = Field(description="Final answer or explicit incomplete/failure explanation.")
    sources: list[SourceReference] = Field(
        default_factory=list,
        description="Distinct tool sources, including prior successful conversation turns.",
    )
    tool_trace: list[ToolExecution] = Field(
        default_factory=list,
        description="Actual tool dispatch outcomes for this question; no private model reasoning.",
    )
    complete: bool = Field(default=True, description="False for loop limits or model failures.")
    error: str | None = Field(
        default=None, description="Failure code; null for a completed response."
    )
