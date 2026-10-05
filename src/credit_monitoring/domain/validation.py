"""Caller-facing extraction results; never sent as the LLM extraction schema."""

from typing import Literal

from pydantic import Field

from .base import ExtractionModel
from .covenant import AllCompanyCovenantExtraction, CovenantExtraction

RESULT_SCHEMA_VERSION = "2.1"


class ValidationIssue(ExtractionModel):
    severity: Literal["error", "warning"] = Field(
        description="Verification error or review warning."
    )
    code: str = Field(description="Stable machine-readable issue code.")
    path: str = Field(description="Path to the affected extracted field or supplied input record.")
    message: str = Field(description="Reason for failure or review; no repaired or inferred facts.")


class ValidationReport(ExtractionModel):
    is_valid: bool = Field(default=True, description="False when a verification error exists.")
    issues: list[ValidationIssue] = Field(
        default_factory=list, description="Errors and warnings; empty if none."
    )

    def add(
        self, severity: Literal["error", "warning"], code: str, path: str, message: str
    ) -> None:
        self.issues.append(
            ValidationIssue(severity=severity, code=code, path=path, message=message)
        )
        if severity == "error":
            self.is_valid = False


class ExtractionResult(ExtractionModel):
    schema_version: str = Field(
        default=RESULT_SCHEMA_VERSION, description="Version of the extraction JSON contract."
    )
    prompt_version: str = Field(description="Version of the prompt used for this extraction.")
    extraction: CovenantExtraction = Field(description="Unmodified extraction, even if unverified.")
    validation: ValidationReport | None = Field(
        default=None, description="Verification report; null when verification has not run."
    )


class AllCompanyExtractionResult(ExtractionModel):
    schema_version: str = Field(
        default=RESULT_SCHEMA_VERSION, description="Version of the batch JSON contract."
    )
    prompt_version: str = Field(
        description="Versions of extraction and batch grouping instructions."
    )
    extraction: AllCompanyCovenantExtraction = Field(description="Unmodified batch extraction.")
    validation: ValidationReport | None = Field(
        default=None, description="Batch verification report; null when verification has not run."
    )
