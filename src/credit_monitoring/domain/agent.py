"""Public agent outcomes contain executed tools and sources, never private reasoning."""

import json
from typing import Any, Literal

from pydantic import ConfigDict, Field

from .base import ExtractionModel
from .tool_results import ToolOutcome


class SourceReference(ExtractionModel):
    document_id: str = Field(description="Actual document ID supplied by an evidence tool.")
    citation: str = Field(description="Actual citation supplied by an evidence tool.")


class ToolExecution(ExtractionModel):
    call_id: str = Field(description="Model tool call ID corresponding to its returned output.")
    name: str = Field(description="Requested tool name; unknown names are recorded as errors.")
    arguments: dict[str, Any] | None = Field(
        description="Decoded arguments, or null for malformed JSON/non-object arguments."
    )
    outcome: ToolOutcome = Field(description="Executed domain result or explicit tool failure.")
    sources: list[SourceReference] = Field(
        default_factory=list, description="Source references derived from this executed result."
    )


class EvidenceEntry(ExtractionModel):
    """Immutable application-owned evidence; data returns an isolated copy."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_id: str
    kind: Literal["assessment", "calculation", "csv", "filing", "prediction", "review"]
    borrower_id: str | None = None
    ticker: str | None = None
    period_end: str | None = None
    information_cutoff: str | None = None
    citation: str
    payload_json: str

    @property
    def data(self) -> dict:
        return json.loads(self.payload_json)


class MaterialClaim(ExtractionModel):
    """Facts select authoritative fields; interpretation explicitly names its evidence."""

    claim_id: str
    kind: Literal["fact", "quote", "narrative"]
    statement: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    field_path: str | None = Field(
        default=None, description="Dot path for a fact, never arithmetic."
    )
    value_json: str | None = Field(
        default=None, description="Optional copied JSON value to validate."
    )
    borrower_id: str | None = None
    ticker: str | None = None
    period_end: str | None = None
    information_cutoff: str | None = None
    unit: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class AnswerContent(ExtractionModel):
    """Generated content; defaults allow provisional streaming snapshots."""

    answer: str = Field(default="", description="Cited answer or clarification request.")
    confidence: Literal["low", "medium", "high"] | None = Field(
        default=None, description="Model-assessed evidence support, not a credit-risk probability."
    )
    confidence_explanation: str = Field(
        default="", description="Evidence and limitations supporting the confidence assessment."
    )
    schema_version: Literal["agent-answer-v2"] | None = Field(
        default=None, description="Answer contract version; null for historical captures."
    )
    answer_kind: (
        Literal[
            "assessment",
            "forecast",
            "evidence",
            "follow_up",
            "clarification",
            "scope",
            "unrelated",
            "discovery",
        ]
        | None
    ) = Field(default=None, description="Validated answer intent, owned by the application.")
    claims: list[MaterialClaim] = Field(
        default_factory=list,
        description="Material claims linked to actual evidence fields/passages.",
    )


class AgentAnswer(AnswerContent):
    evidence: list[EvidenceEntry] = Field(
        default_factory=list, description="Immutable executed and valid retained evidence registry."
    )
    usage: dict[str, int | float | None] = Field(
        default_factory=dict,
        description="Measured request/token usage; unknown tokens remain null.",
    )
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
