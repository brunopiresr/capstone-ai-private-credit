"""Native domain results exchanged by tools, progress events and execution traces."""

from datetime import date
from typing import Literal

from pydantic import Field

from .assessment import FinancialPeriod, RiskAssessment
from .base import ExtractionModel
from .documents import RetrievedRecord
from .processing import DocumentExtraction, DocumentSummary


class FinancialReview(ExtractionModel):
    """Available source financial periods for one analyst-specified review."""

    borrower_id: str = Field(description="Application-scoped borrower identifier.")
    period_end: date = Field(description="Analyst-supplied financial reporting period.")
    information_cutoff: date = Field(
        description="Analyst-supplied information availability cutoff."
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

    code: Literal["invalid_arguments", "unknown_tool", "service_error"] = Field(
        description="Recoverable dispatch or service failure category."
    )
    message: str = Field(
        description="Explanation from argument validation or the executed service."
    )


type ToolOutcome = (
    FinancialReview
    | RiskAssessment
    | DocumentExtraction
    | list[DocumentSummary]
    | list[RetrievedRecord]
    | ToolFailure
)
