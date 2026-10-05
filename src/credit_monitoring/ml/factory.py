"""An extensible registry for risk-model constructors."""

from collections.abc import Callable

from credit_monitoring.config.settings import RiskModelConfig

from .base import RiskModel
from .logistic_model import LogisticRegressionRiskModel
from .stub_model import StubRiskModel


class RiskModelFactory:
    """Create configured services; callers can register trained models later."""

    def __init__(self) -> None:
        self._constructors: dict[str, Callable[[RiskModelConfig], RiskModel]] = {
            "stub": lambda config: StubRiskModel(config.version),
            "logistic_regression": LogisticRegressionRiskModel,
        }

    def register(
        self, model_type: str, constructor: Callable[[RiskModelConfig], RiskModel]
    ) -> None:
        """Register a model constructor without editing the assessment workflow."""
        if not model_type.strip() or model_type in self._constructors:
            raise ValueError("A model type must be nonempty and registered only once.")
        self._constructors[model_type] = constructor

    def create(self, config: RiskModelConfig) -> RiskModel:
        """Create the requested model, rejecting unknown types rather than falling back."""
        if config.type not in self._constructors:
            raise ValueError(f"Unknown risk model type: {config.type}")
        return self._constructors[config.type](config)
