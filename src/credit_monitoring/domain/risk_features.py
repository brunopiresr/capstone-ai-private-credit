"""Model-independent feature vectors and their immutable snapshots."""

from datetime import date, datetime

from pydantic import Field

from .analytics_base import AssessmentModel, ComplianceStatus, new_identifier, utc_now


class CovenantRiskFeatures(AssessmentModel):
    """Comparable current and prior values for one agreement-specific covenant."""

    covenant_id: str = Field(description="Stable agreement-specific covenant identifier.")
    covenant_type: str = Field(description="Metric family.")
    actual_value: float | None = Field(
        default=None, description="Current actual from the stored calculation result."
    )
    threshold: float | None = Field(default=None, description="Current applicable threshold.")
    headroom: float | None = Field(default=None, description="Current direction-aware headroom.")
    compliance_status: ComplianceStatus = Field(description="Current deterministic status.")
    metric_change_qoq: float | None = Field(
        default=None, description="Actual-value change from the exact comparable prior quarter."
    )
    headroom_change_qoq: float | None = Field(
        default=None, description="Headroom change from the exact comparable prior quarter."
    )
    threshold_change_qoq: float | None = Field(
        default=None,
        description="Contractual threshold change, separate from metric deterioration.",
    )
    basis_changed: bool = Field(
        default=False, description="True when prior and current calculation bases are incompatible."
    )
    previous_breach: bool | None = Field(
        default=None, description="Prior-quarter breach indicator; null if not established."
    )
    previous_waiver: bool | None = Field(
        default=None, description="Prior-quarter waiver indicator; null if not established."
    )


class BorrowerRiskFeatures(AssessmentModel):
    """A borrower-period vector that excludes source notes and outcome labels."""

    borrower_id: str = Field(description="Borrower represented by this model input.")
    period_end: date = Field(description="Feature reporting period.")
    information_cutoff: date = Field(
        description="Information cutoff used to construct the features."
    )
    feature_schema_version: str = Field(
        default="v1", description="Version of the model-independent feature contract."
    )
    covenants: list[CovenantRiskFeatures] = Field(
        default_factory=list, description="Separate feature records for all current covenants."
    )
    reported_ebitda_growth_qoq: float | None = Field(
        default=None, description="Fractional reported EBITDA growth from the exact prior quarter."
    )
    reported_ebitda_growth_yoy: float | None = Field(
        default=None, description="Fractional reported EBITDA growth from the exact prior year."
    )
    total_debt_growth_qoq: float | None = Field(
        default=None, description="Fractional total debt growth from the exact prior quarter."
    )
    total_debt_growth_yoy: float | None = Field(
        default=None, description="Fractional total debt growth from the exact prior year."
    )
    liquidity: float | None = Field(
        default=None,
        description="Explicit liquidity input; null when the source does not provide it.",
    )
    liquidity_change_qoq: float | None = Field(
        default=None, description="Comparable liquidity change; null without source data."
    )
    information_availability_known: bool = Field(
        default=False, description="Whether availability dates are known for all referenced inputs."
    )


class BorrowerFeatureSnapshot(AssessmentModel):
    """Exact feature input and calculation references used for a model invocation."""

    snapshot_id: str = Field(
        default_factory=new_identifier, description="Immutable feature snapshot identifier."
    )
    assessment_run_id: str = Field(description="Owning assessment run.")
    features: BorrowerRiskFeatures = Field(description="Exact typed vector supplied to the model.")
    source_result_ids: list[str] = Field(
        description="Stored current and historical calculations used for this vector."
    )
    created_at: datetime = Field(
        default_factory=utc_now, description="UTC snapshot creation timestamp."
    )
