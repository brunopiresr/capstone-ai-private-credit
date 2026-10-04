"""Contractual financial definitions and explicitly reported values; no calculations."""

from datetime import date

from pydantic import Field

from .base import ExtractionModel
from .evidence import SourceEvidence


class FinancialMetricDefinition(ExtractionModel):
    name: str = Field(description="Exact contractual metric name in the supporting excerpt.")
    definition: str | None = Field(
        default=None,
        description="Source-supported contractual definition; null when the full definition is "
        "unavailable, retaining adjustment-only records and recording the missing "
        "definition in gaps.",
    )
    adjustments: list[str] = Field(
        default_factory=list,
        description="Source-stated adjustments including caps, conditions, and periods; empty if "
        "unavailable. An adjustment cap is not a reported financial amount.",
    )
    exclusions: list[str] = Field(
        default_factory=list,
        description="Explicit contractual exclusions only; empty if unavailable.",
    )
    measurement_basis: str | None = Field(
        default=None, description="Explicit contractual measurement basis; null if unavailable."
    )
    amendment_reference: str | None = Field(
        default=None, description="Explicitly linked amendment identifier; null if unavailable."
    )
    evidence: SourceEvidence = Field(
        description=(
            "Excerpt supporting this definition or adjustment version; keep versions separate."
        )
    )


class ReportedFinancialValue(ExtractionModel):
    metric_name: str = Field(
        description="Exact reported financial metric name; distinguish GAAP and contractual terms."
    )
    reported_value: str = Field(
        description="Actual source-disclosed amount or ratio preserving precision and "
        "stated units; "
        "never calculate, normalize, or substitute an adjustment cap."
    )
    period_end: date | None = Field(
        default=None, description="Explicit reporting or test period end in ISO 8601; else null."
    )
    measurement_period: str | None = Field(
        default=None, description="Source-stated measurement period; null if unavailable."
    )
    accounting_basis: str | None = Field(
        default=None, description="Explicit GAAP, non-GAAP, or contractual basis only; else null."
    )
    evidence: SourceEvidence = Field(
        description="Excerpt supporting the exact value and stated period."
    )
