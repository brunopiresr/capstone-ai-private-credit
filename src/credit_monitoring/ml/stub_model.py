"""An integration stub that does not pretend to forecast credit events."""

from credit_monitoring.domain.risk_features import BorrowerRiskFeatures
from credit_monitoring.domain.risk_prediction import RiskPrediction


class StubRiskModel:
    """Return unknown risk and null probabilities without a trained artifact."""

    def __init__(self, version: str = "v1") -> None:
        self.version = version

    def predict(self, features: BorrowerRiskFeatures) -> RiskPrediction:
        """Preserve borrower-period identity while establishing the service interface."""
        return RiskPrediction(
            borrower_id=features.borrower_id,
            period_end=features.period_end,
            model_name="stub",
            model_version=self.version,
            prediction_status="stub",
        )
