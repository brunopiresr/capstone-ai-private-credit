"""Metadata and checksums for locally trained, versioned model artifacts."""

import hashlib
import json
from importlib.metadata import version
from pathlib import Path

DEPENDENCY_NAMES = ("scikit-learn", "numpy", "scipy", "joblib")


def file_hash(path: Path) -> str:
    """Hash a file without depending on its location or modification time."""
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def dependency_versions() -> dict[str, str]:
    """Capture the numerical-library versions needed to reload a pipeline."""
    return {name: version(name) for name in DEPENDENCY_NAMES}


def write_json(path: Path, value: dict) -> None:
    """Write stable, readable metadata and reject nonfinite numeric values."""
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
