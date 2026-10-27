"""Construct either of the two supported risk models."""

from credit_monitoring.config.settings import RiskModelConfig

from .base import RiskModel
from .logistic_model import LogisticRegressionRiskModel
from .stub_model import StubRiskModel


def create_risk_model(config: RiskModelConfig) -> RiskModel:
    """Reject unknown model types rather than falling back to a different model."""
    if config.type == "stub":
        return StubRiskModel(config.version)
    if config.type == "logistic_regression":
        return LogisticRegressionRiskModel(config)
    raise ValueError(f"Unknown risk model type: {config.type}")
