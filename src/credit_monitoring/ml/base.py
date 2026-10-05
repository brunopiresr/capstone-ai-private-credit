"""The monitoring workflow's model-independent prediction boundary."""

from typing import Protocol

from credit_monitoring.domain.risk_features import BorrowerRiskFeatures
from credit_monitoring.domain.risk_prediction import RiskPrediction


class RiskModel(Protocol):
    """Predict from typed features without performing extraction or covenant calculations."""

    def predict(self, features: BorrowerRiskFeatures) -> RiskPrediction:
        """Return an explicitly identified prediction or raise a model-service error."""
        ...
