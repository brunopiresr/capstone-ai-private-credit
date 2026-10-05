"""Typed settings for the optional risk-model service."""

from pathlib import Path

from pydantic import Field

from credit_monitoring.domain.analytics_base import AssessmentModel


class RiskModelConfig(AssessmentModel):
    """Select a registered model without exposing its implementation to the workflow."""

    type: str = Field(default="stub", min_length=1)
    version: str = Field(default="v1", min_length=1)
    artifact_path: Path | None = None


class AssessmentSettings(AssessmentModel):
    """Assessment defaults leave ML disabled and source storage unchanged."""

    ml_enabled: bool = False
    analytics_database: Path = Path("data/processed/analytics.sqlite3")
    risk_model: RiskModelConfig = Field(default_factory=RiskModelConfig)
