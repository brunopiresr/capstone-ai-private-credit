"""Integration tests for the modern role-based Credit Monitor V2 interface."""

from pathlib import Path

import pytest
from portfolio_helpers import portfolio_inputs
from streamlit.testing.v1 import AppTest

from credit_monitoring.web import portfolio as portfolio_page

APP_V2 = Path(__file__).resolve().parents[3] / "src/credit_monitoring/web_v2/app.py"


@pytest.fixture
def app_v2(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("UI must not invoke unmocked backend services unexpectedly")

    for target in (
        "credit_monitoring.application.credit_review_service.CreditReviewService.review_assessment",
        "credit_monitoring.application.document_processing_service.DocumentProcessingService.process_document",
        "credit_monitoring.ingestion.loaders.sec.load_sec_html",
        "requests.sessions.Session.request",
    ):
        monkeypatch.setattr(target, forbidden)

    monkeypatch.setattr(portfolio_page, "DEFAULT_DATA_ROOT", portfolio_inputs(tmp_path))
    monkeypatch.setattr(portfolio_page, "DEFAULT_WORKING_DIR", tmp_path / "working")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    app = AppTest.from_file(str(APP_V2), default_timeout=20).run()
    assert not app.exception
    return app


def test_v2_default_view_is_credit_analyst(app_v2):
    """Verify web_v2 defaults to Credit Analyst role and renders the loan portfolio table."""
    app = app_v2
    assert not app.exception
    # Check that segmented control has Credit Analyst selected
    segmented = [c for c in app.segmented_control if c.key == "v2_active_role"]
    assert len(segmented) == 1
    assert segmented[0].value == "👤 Credit Analyst"

    # Loan portfolio dataframe should be loaded
    assert len(app.dataframe) > 0
    df = app.dataframe[0].value
    assert "Borrower" in df.columns
    assert len(df) == 37


def test_v2_loan_search_filter(app_v2):
    """Verify loan search filtering works smoothly."""
    app = app_v2
    app.text_input(key="v2_analyst_search").set_value("northstar").run()
    assert not app.exception
    assert len(app.dataframe) > 0
    filtered_df = app.dataframe[0].value
    assert filtered_df["Borrower"].tolist() == ["Northstar Packaging"]


def test_v2_role_switching_to_risk_manager_and_documents(app_v2):
    """Verify switching roles to Risk Manager and Documents renders without errors."""
    app = app_v2

    # Switch to Risk Manager
    app.segmented_control(key="v2_active_role").set_value("🛡️ Risk Manager").run()
    assert not app.exception
    # Risk manager view displays the priority exception queue
    assert any("Priority Exception Queue" in m.value for m in app.markdown)

    # Switch to Documents & Data
    app.segmented_control(key="v2_active_role").set_value("📁 Documents & Data").run()
    assert not app.exception
    assert any("Document & Evidence Workspace" in m.value for m in app.markdown)


def test_v2_analyst_run_assessment_and_chat_chips(app_v2):
    """Verify run assessment executes calculation and displays AI assistant with prompt chips."""
    app = app_v2
    # Click "⚡ Run Full Assessment" button
    run_btn = next((b for b in app.button if "Run Full Assessment" in b.label), None)
    assert run_btn is not None
    run_btn.click().run()
    assert not app.exception

    # Check for suggested prompt chips in the Analyst Assistant
    chip_labels = [b.label for b in app.button]
    assert any("Interest Coverage" in label for label in chip_labels)
    assert any("downside risks" in label for label in chip_labels)

    # Click a suggested prompt chip
    target_chip = next(b for b in app.button if "Interest Coverage" in b.label)
    target_chip.click().run()
    assert not app.exception
    # Check that answer was rendered
    assert len(app.chat_message) > 0
