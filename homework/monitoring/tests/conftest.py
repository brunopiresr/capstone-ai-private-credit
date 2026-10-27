"""Offline prototype tests: real graphs and services, scripted provider boundaries."""

import sys
from pathlib import Path

import pytest
from pydantic_ai import models

from credit_monitoring.paths import APP_SYNTHETIC_DIR

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent.parent / "tests"))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("LOGFIRE_SEND_TO_LOGFIRE", "false")
    monkeypatch.setenv("PYDANTIC_AI_NO_BANNER", "1")
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


@pytest.fixture
def data_root(tmp_path):
    import shutil

    data = tmp_path / "data"
    synthetic = data / "app" / "synthetic"
    synthetic.mkdir(parents=True)
    for name in (
        "synthetic_borrowers.csv",
        "synthetic_quarterly_financials.csv",
        "synthetic_covenant_terms.csv",
    ):
        shutil.copyfile(APP_SYNTHETIC_DIR / name, synthetic / name)
    markdown = data / "cache" / "sec" / "markdown"
    markdown.mkdir(parents=True)
    (markdown / "SYN.md").write_text("# Credit agreement\nMaximum leverage ratio is 4.0.\n")
    (data / "app" / "sec").mkdir(parents=True)
    (data / "app" / "sec" / "public_sec_documents.csv").write_text(
        "document_id,company,ticker,document_type,document_date,source_url\n"
        "SYN,Synthetic Issuer,SYN,Agreement,2025-09-30,https://example.invalid/synthetic\n"
    )
    return data
