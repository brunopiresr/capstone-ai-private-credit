"""Validate the expansion ZIP; --apply publishes normalized app/evaluation assets."""

import argparse
import json
from pathlib import Path

from credit_monitoring.ingestion.loaders.bundle import import_bundle
from credit_monitoring.paths import DATA_ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive", type=Path, default=DATA_ROOT / "app/credit_monitoring_dataset_bundle_fixed.zip"
    )
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = import_bundle(args.archive, args.data_root, apply=args.apply)
    except (ValueError, KeyError, OSError) as error:
        parser.exit(1, f"Bundle import failed: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
