"""Generate simulated borrower histories and next-quarter training examples."""

import argparse
import json
from pathlib import Path

from credit_monitoring.ml.synthetic_dataset import generate_dataset
from credit_monitoring.paths import APP_SYNTHETIC_DIR, TRAINING_DIR


def main() -> None:
    """Write independent simulated data without modifying the original PoC fixtures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-directory", type=Path, default=APP_SYNTHETIC_DIR)
    parser.add_argument("--output-directory", type=Path, default=TRAINING_DIR)
    parser.add_argument("--borrowers-per-scenario", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    arguments = parser.parse_args()
    manifest = generate_dataset(
        arguments.source_directory,
        arguments.output_directory,
        seed=arguments.seed,
        borrowers_per_scenario=arguments.borrowers_per_scenario,
    )
    print(
        json.dumps(
            {
                name: manifest[name]
                for name in ("borrower_count", "observation_count", "split_counts", "label_counts")
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
