"""Default checkout paths; callers may still supply explicit input/output locations.

App inputs, evaluation expectations, and generated state have separate roots.
Importing this module does not create directories or load configuration.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data"
APP_SYNTHETIC_DIR = DATA_ROOT / "app" / "synthetic"
SEC_CATALOG = DATA_ROOT / "app" / "sec" / "public_sec_documents.csv"
EVALUATION_DIR = DATA_ROOT / "evaluation"
TRAINING_DIR = DATA_ROOT / "training" / "synthetic"
MODELS_DIR = DATA_ROOT / "models"
SEC_CACHE_DIR = DATA_ROOT / "cache" / "sec"
RUNTIME_DIR = DATA_ROOT / "runtime"
