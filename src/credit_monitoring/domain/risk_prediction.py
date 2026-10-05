"""Validated model outputs, distinct from deterministic covenant compliance."""

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from .analytics_base import AssessmentModel, new_identifier, utc_now


class RiskPrediction(AssessmentModel):
    """A prediction with its target, horizon, and feature-snapshot identity."""

    prediction_id: str = Field(
        default_factory=new_identifier, description="Immutable model-output identifier."
    )
    borrower_id: str = Field(description="Predicted borrower.")
    period_end: date = Field(description="Prediction reporting period.")
    snapshot_id: str | None = Field(default=None, description="Persisted feature input identifier.")
    model_name: str = Field(
        min_length=1, description="Explicit model name; stub outputs are identified as stub."
    )
    model_version: str = Field(
        min_length=1, description="Model implementation or artifact version."
    )
    model_artifact_hash: str | None = Field(
        default=None, description="Artifact checksum, when a trained artifact exists."
    )
    prediction_target: Literal["any_covenant_breach"] = Field(
        default="any_covenant_breach", description="Event whose probability is being predicted."
    )
    horizon_quarters: int = Field(
        default=1,
        gt=0,
        description="Prediction horizon in quarters; the initial workflow supports one.",
    )
    prediction_status: Literal["stub", "complete", "unavailable", "failed"] = Field(
        description="Distinguishes actual model output, stub output, and failures."
    )
    breach_probability: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Next-quarter breach probability in [0, 1]; null if unavailable.",
    )
    deterioration_probability: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Deterioration probability in [0, 1]; null if unavailable.",
    )
    anomaly_score: float | None = Field(
        default=None, description="Model-specific anomaly score; not a breach probability."
    )
    risk_level: Literal["low", "medium", "high", "unknown"] = Field(
        default="unknown",
        description="Predictive risk classification, independent of current compliance.",
    )
    top_drivers: list[str] = Field(
        default_factory=list, description="Model-provided drivers, when available."
    )
    error: str | None = Field(default=None, description="Prediction failure explanation.")
    generated_at: datetime = Field(
        default_factory=utc_now, description="UTC output generation timestamp."
    )
