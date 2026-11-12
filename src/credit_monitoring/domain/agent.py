"""Public agent outcomes contain executed tools and sources, never private reasoning."""

import json
from typing import Any, Literal

from pydantic import ConfigDict, Field

from .base import ExtractionModel
from .tool_results import ToolOutcome


class SourceReference(ExtractionModel):
    document_id: str = Field(
        description="Source document, calculation run/result, or CSV file/row ID from a tool."
    )
    citation: str = Field(
        description=(
            "Complete source citation copied verbatim from a tool result, including its "
            "identifier and URL when supplied; do not shorten it."
        )
    )


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
    """Historical v2 claim data retained for loading saved answers."""

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


type AnswerKind = Literal[
    "assessment",
    "forecast",
    "evidence",
    "follow_up",
    "clarification",
    "scope",
    "unrelated",
    "discovery",
]


class AnswerFinding(ExtractionModel):
    text: str = Field(description="Markdown finding, including relevant values and units.")
    citations: list[SourceReference] = Field(
        default_factory=list, description="Supplied source citations."
    )


class AnswerTableRow(ExtractionModel):
    cells: list[str] = Field(description="Plain text values, in column order.")
    citations: list[SourceReference] = Field(
        default_factory=list, description="Supplied source citations."
    )


class AnswerTable(ExtractionModel):
    title: str = Field(default="", description="Plain text table title.")
    columns: list[str] = Field(default_factory=list, description="Plain text column names.")
    rows: list[AnswerTableRow] = Field(
        default_factory=list, description="Table data and citations."
    )


class AnswerDraft(ExtractionModel):
    """Model-authored data; presentation belongs to the application."""

    summary: str = Field(
        default="",
        description=(
            "One or two concise Markdown sentences answering or clarifying the question. "
            "Put detailed findings in findings and schedule rows in structured tables."
        ),
    )
    answer_kind: AnswerKind | None = Field(default=None, description="Descriptive response kind.")
    findings: list[AnswerFinding] = Field(
        default_factory=list,
        description=(
            "Cited factual findings. For requested reported actuals, include each requested "
            "metric for every source reporting period found; put schedules in tables."
        ),
    )
    tables: list[AnswerTable] = Field(
        default_factory=list,
        description=(
            "Structured tables for requested schedules and matrices, with row citations. "
            "Complete schedules retain every explicitly named period and threshold."
        ),
    )
    gaps: list[str] = Field(
        default_factory=list, description="Missing data and material limitations, in Markdown."
    )
    diligence_questions: list[str] = Field(
        default_factory=list, description="Diligence questions in Markdown; one question per item."
    )
    confidence: Literal["low", "medium", "high"] | None = Field(
        default=None, description="Confidence in evidence support, independent of credit risk."
    )
    confidence_explanation: str = Field(default="", description="Evidence support and limitations.")


class AnswerContent(AnswerDraft):
    """Generated content; defaults allow provisional streaming snapshots."""

    answer: str = Field(
        default="", description="Backend-rendered Markdown answer or clarification."
    )
    schema_version: Literal["agent-answer-v2", "agent-answer-v3"] | None = Field(
        default=None, description="Answer contract version; null for historical captures."
    )
    claims: list[MaterialClaim] = Field(
        default_factory=list,
        description="Material claims linked to actual evidence fields/passages.",
    )


class AgentAnswer(AnswerContent):
    evidence: list[EvidenceEntry] = Field(
        default_factory=list, description="Copied executed and retained tool context."
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
