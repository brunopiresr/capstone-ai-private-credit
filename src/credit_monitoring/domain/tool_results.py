"""Native domain results exchanged by tools, progress events and execution traces."""

from datetime import date
from typing import Literal

from pydantic import Field

from .assessment import FinancialPeriod, RiskAssessment
from .base import ExtractionModel
from .documents import RetrievedRecord
from .processing import DocumentExtraction, DocumentSummary


class FinancialPeriodSummary(ExtractionModel):
    period_end: date = Field(description="Reporting period stored in the active financial source.")
    available_at: date | None = Field(
        default=None, description="Known publication/availability date; null means unknown."
    )


class FinancialPeriodCatalog(ExtractionModel):
    """Discovery metadata only, without financial metrics or benchmark annotations."""

    borrower_id: str = Field(description="Application-selected borrower.")
    periods: list[FinancialPeriodSummary] = Field(
        default_factory=list, description="Stored reporting periods in ascending order."
    )
    source: Literal["financial_repository", "saved_assessment"] = Field(
        description="Whether discovery reads the repository or a selected saved snapshot."
    )
    source_assessment_run_id: str | None = Field(
        default=None,
        description="Selected snapshot ID when discovery is limited to saved evidence.",
    )


class FinancialReview(ExtractionModel):
    """Available source financial periods for one analyst-specified review."""

    borrower_id: str = Field(description="Application-scoped borrower identifier.")
    period_end: date = Field(description="Financial reporting period resolved for this read.")
    information_cutoff: date = Field(
        description="Information cutoff resolved from the request, context or disclosed default."
    )
    current: FinancialPeriod | None = Field(
        default=None, description="Available inputs for the exact requested period, or null."
    )
    history: list[FinancialPeriod] = Field(
        default_factory=list, description="Earlier financial periods available by the cutoff."
    )
    issues: list[str] = Field(
        default_factory=list, description="Missing inputs or unknown/excluded availability dates."
    )


class ToolFailure(ExtractionModel):
    """Recoverable dispatch or service failure, separate from successful domain results."""

    code: Literal["invalid_arguments", "unknown_tool", "service_error", "policy_rejection"] = Field(
        description="Recoverable dispatch or service failure category."
    )
    message: str = Field(
        description="Explanation from argument validation or the executed service."
    )
    terminal: bool = Field(default=False, description="True when policy requires ending the turn.")


type ToolOutcome = (
    FinancialPeriodCatalog
    | FinancialReview
    | RiskAssessment
    | DocumentExtraction
    | list[DocumentSummary]
    | list[RetrievedRecord]
    | ToolFailure
)
