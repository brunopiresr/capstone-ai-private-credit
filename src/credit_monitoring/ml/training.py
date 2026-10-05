"""Train and evaluate the baseline offline, retaining all preprocessing in its artifact."""

import json
import platform
from pathlib import Path

from credit_monitoring.features.model_features import FEATURE_COLUMNS, MODEL_FEATURE_SCHEMA_VERSION

from .artifacts import dependency_versions, file_hash, write_json


def _evaluate(labels, probabilities, prevalence: float) -> dict:
    """Report held-out performance and undefined metrics without inventing scores."""
    import numpy as np
    from sklearn.metrics import (
        average_precision_score,
        brier_score_loss,
        log_loss,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    if len(labels) == 0:
        return {"count": 0, "reason": "No eligible observations."}
    classifications = probabilities >= 0.5
    both_classes = len(set(labels)) == 2
    return {
        "count": len(labels),
        "breach_prevalence": float(np.mean(labels)),
        "precision": float(precision_score(labels, classifications, zero_division=0)),
        "recall": float(recall_score(labels, classifications, zero_division=0)),
        "pr_auc": float(average_precision_score(labels, probabilities)) if both_classes else None,
        "roc_auc": float(roc_auc_score(labels, probabilities)) if both_classes else None,
        "log_loss": float(log_loss(labels, probabilities, labels=[0, 1])),
        "brier_score": float(brier_score_loss(labels, probabilities)),
        "constant_baseline_brier_score": float(
            brier_score_loss(labels, np.full(len(labels), prevalence))
        ),
        "constant_baseline_log_loss": float(
            log_loss(labels, np.full(len(labels), prevalence), labels=[0, 1])
        ),
        "classification_threshold": 0.5,
    }


def train_model(
    dataset_directory: Path,
    artifact_directory: Path,
    *,
    version: str = "v1",
    seed: int = 42,
) -> dict:
    """Fit a baseline using only the training partition and save a local pipeline.

    Validation and test observations are evaluated after fitting. They never update
    preprocessing, model coefficients, or classification thresholds.
    """
    import joblib
    import numpy as np
    import pandas as pd
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    if not version.strip():
        raise ValueError("A nonempty model version is required.")
    dataset_directory = dataset_directory.resolve()
    artifact_directory = artifact_directory.resolve()
    if artifact_directory == dataset_directory:
        raise ValueError("Save model artifacts separately from training inputs.")
    dataset_manifest = json.loads((dataset_directory / "manifest.json").read_text())
    expected = {
        "feature_schema_version": "v1",
        "model_feature_schema_version": MODEL_FEATURE_SCHEMA_VERSION,
        "feature_columns": list(FEATURE_COLUMNS),
        "prediction_target": "any_covenant_breach",
        "horizon_quarters": 1,
        "training_data_origin": "synthetic",
    }
    for name, value in expected.items():
        if dataset_manifest.get(name) != value:
            raise ValueError(f"Unsupported dataset metadata: {name}")
    dataset_path = dataset_directory / "training.csv"
    if file_hash(dataset_path) != dataset_manifest.get("output_hashes", {}).get("training.csv"):
        raise ValueError("Training dataset checksum does not match its manifest.")
    frame = pd.read_csv(dataset_path)
    if list(frame.columns) != [
        "sample_id",
        "borrower_id",
        "period_end",
        "split",
        "target",
        *FEATURE_COLUMNS,
    ]:
        raise ValueError("Training columns do not match the feature contract.")
    if (
        frame["sample_id"].duplicated().any()
        or frame.duplicated(["borrower_id", "period_end"]).any()
    ):
        raise ValueError("Duplicate borrower-quarter observations cannot be training examples.")
    if not frame["split"].isin(["train", "validation", "test", "unused"]).all():
        raise ValueError("Unknown evaluation partition.")
    if not frame["target"].dropna().isin([0, 1]).all():
        raise ValueError("Observed targets must be zero or one.")
    features = frame.loc[:, list(FEATURE_COLUMNS)].astype(float)
    if np.isinf(features.to_numpy()).any():
        raise ValueError("Training features must be finite or missing.")
    partitions = {}
    borrowers_seen = set()
    permitted_periods = {
        "train": {"2025-03-31", "2025-06-30", "2025-09-30"},
        "validation": {"2026-03-31", "2026-06-30"},
        "test": {"2026-09-30"},
    }
    for partition in ("train", "validation", "test"):
        selected = frame["split"] == partition
        rows = frame[selected]
        if rows["target"].isna().any():
            raise ValueError("Unobserved outcomes cannot enter an evaluation partition.")
        if not rows["period_end"].isin(permitted_periods[partition]).all():
            raise ValueError("Evaluation periods violate temporal boundaries.")
        borrower_ids = set(rows["borrower_id"])
        if borrower_ids & borrowers_seen:
            raise ValueError("Borrowers cannot appear in multiple evaluation partitions.")
        borrowers_seen.update(borrower_ids)
        partitions[partition] = (features[selected], rows["target"].astype(int))
    training_features, training_labels = partitions["train"]
    if set(training_labels) != {0, 1}:
        raise ValueError("Training requires observed breaches and non-breaches.")
    pipeline = Pipeline(
        [
            (
                "imputer",
                SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
            ),
            ("scaler", StandardScaler()),
            ("classifier", LogisticRegression(C=1, max_iter=1000, random_state=seed)),
        ]
    )
    pipeline.fit(training_features, training_labels)
    prevalence = float(training_labels.mean())
    evaluation = {}
    for partition, (partition_features, labels) in partitions.items():
        probabilities = (
            pipeline.predict_proba(partition_features)[:, 1] if len(labels) else np.array([])
        )
        evaluation[partition] = _evaluate(labels, probabilities, prevalence)
    artifact_directory.mkdir(parents=True, exist_ok=True)
    pipeline_path = artifact_directory / "pipeline.joblib"
    joblib.dump(pipeline, pipeline_path, compress=3)
    manifest = {
        "artifact_format": "joblib",
        "model_type": "logistic_regression",
        "model_version": version,
        **expected,
        "seed": seed,
        "python_version": platform.python_version(),
        "dependency_versions": dependency_versions(),
        "dataset_fingerprint": file_hash(dataset_directory / "manifest.json"),
        "training_csv_hash": file_hash(dataset_path),
        "model_artifact_hash": file_hash(pipeline_path),
        "evaluation": evaluation,
        "risk_level_policy": "unknown; no validated risk thresholds",
    }
    write_json(artifact_directory / "manifest.json", manifest)
    return manifest
