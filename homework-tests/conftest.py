"""Opt-in live-agent setup with real services and isolated synthetic data."""

import os
import tempfile
from pathlib import Path

import pytest
from dotenv import load_dotenv
from pydantic_ai import models

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.agents.models import DEFAULT_MODEL
from credit_monitoring.application.bootstrap import (
    create_assessment_service,
    create_document_service,
)
from credit_monitoring.config.settings import AssessmentSettings, RiskModelConfig
from credit_monitoring.covenants.structured import SyntheticCovenantReader
from credit_monitoring.financials.repositories import FinancialRepository
from credit_monitoring.ingestion.loaders.financials import load_financials

ROOT = Path(__file__).resolve().parents[1]


def pytest_addoption(parser):
    group = parser.getgroup("homework agent tests")
    group.addoption(
        "--run-live",
        "--run-llm-evals",
        dest="run_live",
        action="store_true",
        help="Run live homework agent and LLM-judge tests (requires credentials; API costs apply).",
    )
    group.addoption(
        "--homework-model",
        default=DEFAULT_MODEL,
        help=f"Provider-qualified model for the homework tests (default: {DEFAULT_MODEL}).",
    )


@pytest.fixture
def credit_agent(pytestconfig, tmp_path, monkeypatch):
    if not pytestconfig.getoption("run_live"):
        pytest.skip("Use --run-llm-evals (or --run-live) to run the agent and judge.")

    load_dotenv(ROOT / ".env", override=False)
    model = pytestconfig.getoption("--homework-model")
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        pytest.fail("Set OPENAI_API_KEY in the environment or the repository's .env file.")
    monkeypatch.setenv("PYDANTIC_AI_NO_BANNER", "1")

    financial_database = tmp_path / "financials.sqlite3"
    load_financials(ROOT / "data/synthetic_quarterly_financials.csv", financial_database)
    assessments = create_assessment_service(
        financial_repository=FinancialRepository(financial_database),
        covenant_reader=SyntheticCovenantReader(ROOT / "data/synthetic_covenant_terms.csv"),
        settings=AssessmentSettings(
            analytics_database=tmp_path / "analytics.sqlite3",
            risk_model=RiskModelConfig(type="stub"),
        ),
    )

    # These financial scenarios need no SEC documents or downloads.
    catalog = tmp_path / "catalog.csv"
    catalog.write_text("document_id,company,ticker,document_type,source_url\n", encoding="utf-8")
    documents = create_document_service(
        source_file=catalog,
        html_dir=tmp_path / "html",
        markdown_dir=tmp_path / "markdown",
        database_path=tmp_path / "documents.sqlite3",
        model=model,
    )
    with models.override_allow_model_requests(True):
        yield CreditAssessmentAgent(
            service=documents,
            assessment_service=assessments,
            model=model,
        )


@pytest.fixture
def scenario_artifacts(credit_agent, request):
    """Keep captures outside pytest's disposable temp databases, including on failure."""
    parent = ROOT / "data/processed"
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"judges-homework-{request.node.name}-", dir=parent))
