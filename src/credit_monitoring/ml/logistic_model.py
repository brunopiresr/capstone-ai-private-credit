"""Load a local baseline artifact and predict from the shared feature contract."""

import json
import platform

from credit_monitoring.config.settings import RiskModelConfig
from credit_monitoring.domain.risk_features import BorrowerRiskFeatures
from credit_monitoring.domain.risk_prediction import RiskPrediction
from credit_monitoring.features.model_features import (
    FEATURE_COLUMNS,
    MODEL_FEATURE_SCHEMA_VERSION,
    has_usable_current_inputs,
    model_feature_row,
)

from .artifacts import dependency_versions, file_hash


class LogisticRegressionRiskModel:
    """Predict next-quarter breaches using a locally generated synthetic artifact."""

    def __init__(self, config: RiskModelConfig) -> None:
        if config.artifact_path is None:
            raise ValueError("Logistic Regression requires an artifact directory.")
        directory = config.artifact_path.expanduser().resolve()
        manifest = json.loads((directory / "manifest.json").read_text())
        expected = {
            "artifact_format": "joblib",
            "model_type": "logistic_regression",
            "model_version": config.version,
            "feature_schema_version": "v1",
            "model_feature_schema_version": MODEL_FEATURE_SCHEMA_VERSION,
            "feature_columns": list(FEATURE_COLUMNS),
            "prediction_target": "any_covenant_breach",
            "horizon_quarters": 1,
            "training_data_origin": "synthetic",
        }
        for name, value in expected.items():
            if manifest.get(name) != value:
                raise ValueError(f"Incompatible model artifact: {name}")
        if manifest.get("dependency_versions") != dependency_versions():
            raise ValueError("Artifact numerical-library versions differ from this environment.")
        if (
            str(manifest.get("python_version", "")).split(".")[:2]
            != (platform.python_version().split(".")[:2])
        ):
            raise ValueError("Artifact Python version differs from this environment.")
        pipeline_path = directory / "pipeline.joblib"
        if file_hash(pipeline_path) != manifest.get("model_artifact_hash"):
            raise ValueError("Model artifact checksum does not match its manifest.")
        import joblib
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline

        self.pipeline = joblib.load(pipeline_path)
        if (
            not isinstance(self.pipeline, Pipeline)
            or not isinstance(self.pipeline.named_steps.get("classifier"), LogisticRegression)
            or list(self.pipeline.feature_names_in_) != list(FEATURE_COLUMNS)
            or list(self.pipeline.classes_) != [0, 1]
        ):
            raise ValueError("Loaded pipeline does not match the baseline contract.")
        self.manifest = manifest

    def predict(self, features: BorrowerRiskFeatures) -> RiskPrediction:
        """Apply saved preprocessing and preserve missing-input abstentions."""
        if features.feature_schema_version != self.manifest["feature_schema_version"]:
            raise ValueError("Input feature schema is incompatible with the model.")
        identity = {
            "borrower_id": features.borrower_id,
            "period_end": features.period_end,
            "model_name": "logistic_regression",
            "model_version": self.manifest["model_version"],
            "model_artifact_hash": self.manifest["model_artifact_hash"],
        }
        if not has_usable_current_inputs(features):
            return RiskPrediction(
                **identity,
                prediction_status="unavailable",
                error="No covenant has usable current numeric inputs.",
            )
        import pandas as pd

        row = model_feature_row(features)
        frame = pd.DataFrame([row], columns=FEATURE_COLUMNS).astype(float)
        probability = float(self.pipeline.predict_proba(frame)[0, 1])
        return RiskPrediction(
            **identity, prediction_status="complete", breach_probability=probability
        )
