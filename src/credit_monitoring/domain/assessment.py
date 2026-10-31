"""Typed inputs, calculation history, and analyst assessment outputs."""

import json
from datetime import date, datetime
from typing import Literal

from pydantic import Field, field_validator

from .analytics_base import (
    AssessmentModel,
    CalculationFormula,
    ComparisonOperator,
    ComplianceStatus,
    TestingStatus,
    new_identifier,
    utc_now,
)
from .financials import FINANCIAL_METRICS
from .risk_features import BorrowerFeatureSnapshot, BorrowerRiskFeatures
from .risk_prediction import RiskPrediction
from .validation import ValidationReport


class FinancialPeriod(AssessmentModel):
    """Allowlisted source metrics and provenance, without benchmark notes."""

    borrower_id: str = Field(description="Explicit borrower identifier.")
    period_end: date = Field(description="Reporting period end.")
    metrics: dict[str, float | None] = Field(
        default_factory=dict, description="Allowlisted source metrics; missing values remain null."
    )
    source_file: str | None = Field(
        default=None, description="Source financial file, when supplied."
    )
    source_row: int | None = Field(default=None, description="Source CSV line number.")
    loaded_at: str | None = Field(
        default=None, description="Repository load timestamp; not a publication timestamp."
    )
    available_at: date | None = Field(
        default=None, description="Known source availability date; null when unknown."
    )
    currency: str | None = Field(
        default=None, description="Explicit source currency; never inferred."
    )
    scale: str | None = Field(default=None, description="Explicit monetary scale; never inferred.")
    debt_source_status: Literal["CONFLICTING", "RECONCILED"] | None = Field(
        default=None, description="Explicit source reconciliation state; never inferred."
    )

    @field_validator("metrics")
    @classmethod
    def validate_metric_names(cls, metrics: dict[str, float | None]) -> dict[str, float | None]:
        """Keep annotations and benchmark fields out of calculation inputs."""
        if unknown := set(metrics) - set(FINANCIAL_METRICS):
            raise ValueError(f"Unknown financial metrics: {sorted(unknown)}")
        return metrics


class ResolvedCovenant(AssessmentModel):
    """Terms selected for one covenant and period, retaining their source evidence."""

    borrower_id: str = Field(description="Mapped borrower identifier.")
    agreement_id: str = Field(description="Explicit agreement identifier.")
    covenant_id: str = Field(description="Stable agreement-specific covenant identifier.")
    covenant_name: str = Field(description="Source covenant name.")
    covenant_type: str = Field(
        description="Metric family, retaining net and total leverage distinctions."
    )
    covenant_version: str = Field(description="Fingerprint of the applied source term version.")
    period_end: date = Field(description="Resolved reporting period.")
    threshold: float = Field(description="Applicable normalized threshold.")
    operator: ComparisonOperator = Field(description="Source-supported comparison operator.")
    unit: str = Field(default="x", description="Threshold and metric unit.")
    formula: CalculationFormula | None = Field(
        default=None, description="Allowlisted calculation formula; null if unsupported."
    )
    calculation_contract: Literal["legacy_v1", "bundle_v1"] = Field(
        default="legacy_v1", description="Versioned economic definitions for these terms."
    )
    measurement_basis: str | None = Field(
        default=None, description="Explicit contractual measurement basis."
    )
    cash_netting_cap: float | None = Field(
        default=None,
        ge=0,
        description="Maximum eligible cash deduction, when contractually specified.",
    )
    addback_cap_fraction: float | None = Field(
        default=None, ge=0, description="Addback cap as a fraction of reported EBITDA."
    )
    synergy_cap_fraction: float | None = Field(
        default=None,
        ge=0,
        description="Synergy cap against acquired EBITDA (legacy) or base EBITDA (bundle).",
    )
    testing_status: TestingStatus = Field(
        default="active", description="Whether the covenant is actively tested for this period."
    )
    reported_actual: float | None = Field(
        default=None,
        description="Period-matched source-disclosed actual; not independently calculated.",
    )
    reported_evidence: list[dict] = Field(
        default_factory=list, description="Evidence supporting the source-disclosed actual."
    )
    evidence: list[dict] = Field(
        default_factory=list,
        description="Source evidence supporting applied terms and testing events.",
    )
    available_at: date | None = Field(
        default=None, description="Known availability date for the applied terms."
    )

    @property
    def basis_key(self) -> str:
        """Identify comparable formulas independently of threshold changes."""
        return json.dumps(
            {
                "formula": self.formula,
                "calculation_contract": self.calculation_contract,
                "measurement_basis": self.measurement_basis,
                "cash_netting_cap": self.cash_netting_cap,
                "addback_cap_fraction": self.addback_cap_fraction,
                "synergy_cap_fraction": self.synergy_cap_fraction,
                "unit": self.unit,
            },
            sort_keys=True,
        )


class CovenantResolution(AssessmentModel):
    """A resolved term or an explicit reason why it cannot be selected."""

    covenant_id: str = Field(description="Stable identifier of the requested covenant.")
    covenant_type: str = Field(description="Source covenant family.")
    covenant: ResolvedCovenant | None = Field(
        default=None, description="Unique applicable terms, or null when unresolved."
    )
    issues: list[str] = Field(
        default_factory=list, description="Reasons applicability or terms could not be resolved."
    )
    evidence: list[dict] = Field(
        default_factory=list, description="Available source references for this resolution."
    )


class CovenantResult(AssessmentModel):
    """An immutable calculation record with enough inputs to reproduce its result."""

    result_id: str = Field(
        default_factory=new_identifier, description="Immutable calculation record identifier."
    )
    assessment_run_id: str = Field(description="Owning assessment run identifier.")
    borrower_id: str = Field(description="Borrower represented by this result.")
    agreement_id: str | None = Field(
        default=None, description="Resolved agreement identifier, if known."
    )
    covenant_id: str = Field(description="Stable agreement-specific covenant identifier.")
    covenant_version: str | None = Field(default=None, description="Applied source version.")
    covenant_type: str = Field(description="Calculated or reported metric family.")
    period_end: date = Field(description="Calculation reporting period.")
    information_cutoff: date = Field(
        description="Requested information cutoff; not proof of source availability."
    )
    actual_value: float | None = Field(
        default=None, description="Calculated or explicitly reported actual; null if unavailable."
    )
    threshold: float | None = Field(
        default=None, description="Applied threshold; null if unresolved."
    )
    operator: ComparisonOperator | None = Field(
        default=None, description="Applied comparison operator."
    )
    unit: str | None = Field(default=None, description="Metric and threshold unit.")
    headroom: float | None = Field(
        default=None, description="Direction-aware headroom for active tests."
    )
    compliance_status: ComplianceStatus = Field(
        description="Deterministic compliance or explicit abstention status."
    )
    calculation_version: str = Field(
        default="v1", description="Version of the deterministic calculation implementation."
    )
    resolved_covenant: ResolvedCovenant | None = Field(
        default=None, description="Exact applied terms and their source evidence."
    )
    financial_inputs: dict = Field(
        default_factory=dict,
        description="Exact sanitized financial inputs and calculated/reported result basis.",
    )
    evidence: list[dict] = Field(
        default_factory=list, description="Source provenance for this result."
    )
    issues: list[str] = Field(
        default_factory=list, description="Missing-data and calculation issues."
    )
    created_at: datetime = Field(default_factory=utc_now, description="UTC creation timestamp.")


class RiskAssessment(AssessmentModel):
    """Deterministic results and optional model output returned to the application."""

    assessment_run_id: str = Field(
        description="Identifier for this complete assessment invocation."
    )
    borrower_id: str = Field(description="Assessed borrower.")
    period_end: date = Field(description="Requested reporting period.")
    information_cutoff: date = Field(description="Requested information cutoff.")
    results: list[CovenantResult] = Field(description="Current deterministic covenant results.")
    history: list[CovenantResult] = Field(
        default_factory=list, description="Earlier results from the same bounded assessment run."
    )
    trends: BorrowerRiskFeatures | None = Field(
        default=None,
        description="Current values and comparable trends, independent of prediction.",
    )
    feature_snapshot: BorrowerFeatureSnapshot | None = Field(
        default=None, description="Exact persisted model input, when feature construction succeeds."
    )
    prediction: RiskPrediction | None = Field(
        default=None, description="Validated model output or persisted failure metadata."
    )
    ml_status: Literal["disabled", "stub", "complete", "unavailable", "failed"] = Field(
        default="disabled", description="Whether ML is disabled, available, a stub, or failed."
    )
    narrative: str | None = Field(
        default=None, description="Optional description; never overrides deterministic results."
    )
    issues: list[str] = Field(
        default_factory=list, description="Application-level availability or service errors."
    )
    verification: ValidationReport = Field(
        default_factory=ValidationReport,
        description="Structured verification errors and source-availability warnings.",
    )
