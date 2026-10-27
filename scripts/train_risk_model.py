"""Train the offline synthetic Logistic Regression baseline."""

import argparse
import json
from pathlib import Path

from credit_monitoring.ml.training import train_model
from credit_monitoring.paths import MODELS_DIR, TRAINING_DIR


def main() -> None:
    """Save the fitted pipeline and its evaluation manifest to a versioned directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-directory", type=Path, default=TRAINING_DIR)
    parser.add_argument(
        "--artifact-directory", type=Path, default=MODELS_DIR / "logistic_regression" / "v1"
    )
    parser.add_argument("--version", default="v1")
    parser.add_argument("--seed", type=int, default=42)
    arguments = parser.parse_args()
    manifest = train_model(
        arguments.dataset_directory,
        arguments.artifact_directory,
        version=arguments.version,
        seed=arguments.seed,
    )
    print(json.dumps(manifest["evaluation"], indent=2))


if __name__ == "__main__":
    main()
