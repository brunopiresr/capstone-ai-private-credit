"""Connected navigation never launches calculations, downloads or agents implicitly."""

from pathlib import Path

import pytest
from portfolio_helpers import portfolio_inputs
from streamlit.testing.v1 import AppTest

from credit_monitoring.web import portfolio as portfolio_page

APP = Path(__file__).resolve().parents[3] / "src/credit_monitoring/web/preview.py"


def control(controls, label):
    return next(item for item in controls if item.label == label)


def click(app, label):
    control(app.button, label).click().run()
    assert not app.exception
    return app


def page(app, name):
    app.radio(key="preview_page").set_value(name).run()
    assert not app.exception
    return app


@pytest.fixture
def preview(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("UI preview must not invoke connected services or HTTP requests")

    for target in (
        "credit_monitoring.application.assessment_service.AssessmentService.assess",
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
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    return app


def test_all_pages_render_without_services_and_borrower_list_filters(preview):
    app = preview
    assert not any(item.label == "Workspace" for item in app.selectbox)
    assert len(app.dataframe[0].value) == 37
    app.text_input(key="portfolio_search").set_value("northstar").run()
    assert app.dataframe[0].value["Borrower"].tolist() == ["Northstar Packaging"]
    app.text_input(key="portfolio_search").set_value("")
    app.selectbox(key="portfolio_status_filter").select("Not assessed").run()
    assert len(app.dataframe[0].value) == 37
    assert "Pioneer Security" in app.dataframe[0].value["Borrower"].tolist()
    app.text_input(key="portfolio_search").set_value("no-such-borrower").run()
    assert any("No borrowers match" in item.value for item in app.info)
    for name in ("Borrower analysis", "Documents & data", "Risk review", "Board report"):
        page(app, name)
        assert not any("Illustrative" in item.value for item in app.markdown)
        if name == "Risk review":
            assert any("No cases match" in item.value for item in app.info)
        if name == "Board report":
            assert any(button.label == "Generate report draft" for button in app.button)
