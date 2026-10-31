"""Help remains read-only and preserves the analyst's selected working context."""

from pathlib import Path

import pytest
from portfolio_helpers import portfolio_inputs
from streamlit.testing.v1 import AppTest

from credit_monitoring.web import borrower_analysis, portfolio
from credit_monitoring.web.user_guide import TOPICS

APP = Path(__file__).resolve().parents[3] / "src/credit_monitoring/web/preview.py"


def click(app, label):
    next(b for b in app.button if b.label == label).click().run()
    assert not app.exception


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(portfolio, "DEFAULT_DATA_ROOT", portfolio_inputs(tmp_path))
    monkeypatch.setattr(portfolio, "DEFAULT_WORKING_DIR", tmp_path / "working")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    return app


def page(app, name):
    app.radio(key="preview_page").set_value(name).run()
    assert not app.exception


def test_every_guide_topic_without_services_or_credentials(app, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("The user guide must not execute application services.")

    monkeypatch.setattr(portfolio, "create_portfolio_service", forbidden)
    monkeypatch.setattr(
        "credit_monitoring.agents.follow_up_questions.FollowUpQuestionAgent.generate", forbidden
    )
    click(app, "Open user guide")
    for topic in TOPICS:
        app.selectbox(key="guide_topic").select(topic).run()
        assert not app.exception
        assert any(s.value == topic for s in app.subheader)
    assert not app.chat_input
    assert "analysis_chats" not in app.session_state


def test_portfolio_selections_and_invitation_survive_guide_and_reset(app):
    click(app, "Dismiss")
    assert not any(b.label == "Dismiss" for b in app.button)
    app.selectbox(key="portfolio_borrower").select("SYN001").run()
    app.selectbox(key="portfolio_period").select("2025-09-30").run()
    app.text_input(key="portfolio_search").set_value("northstar").run()
    page(app, "User guide")
    app.selectbox(key="guide_topic").select("Ask the assistant").run()
    click(app, "Back to previous page")
    assert app.selectbox(key="portfolio_borrower").value == "SYN001"
    assert app.selectbox(key="portfolio_period").value == "2025-09-30"
    assert app.text_input(key="portfolio_search").value == "northstar"
    assert not any(b.label == "Dismiss" for b in app.button)
    click(app, "Reset navigation")
    page(app, "User guide")
    click(app, "Open Borrower analysis")
    assert app.radio(key="preview_page").value == "Borrower analysis"


def test_old_assessment_version_dates_prediction_chat_and_draft_survive_help(app):
    page(app, "Borrower analysis")
    app.selectbox(key="analysis_borrower").select("SYN001").run()
    app.selectbox(key="analysis_period").select("2025-09-30").run()
    app.selectbox(key="analysis_prediction").select("Off").run()
    click(app, "Run assessment")
    original = app.selectbox(key="analysis_version").value
    click(app, "Run assessment")
    app.selectbox(key="analysis_version").select(original).run()
    state = app.session_state.analysis_chats[original]
    state["messages"] = [{"role": "user", "content": "Keep my conversation."}]
    key = f"analysis_question_draft_{original}"
    app.text_area(key=key).set_value("An unfinished question.").run()
    workflow = borrower_analysis.get_workflow()
    before = workflow.portfolio.repository.assessment_history("SYN001")
    page(app, "User guide")
    app.selectbox(key="guide_topic").select("Get started").run()
    click(app, "Back to previous page")
    assert app.selectbox(key="analysis_version").value == original
    assert app.selectbox(key="analysis_prediction").value == "Off"
    assert app.selectbox(key="analysis_period").value == "2025-09-30"
    assert app.text_area(key=key).value == "An unfinished question."
    assert app.session_state.analysis_chats[original]["messages"] == state["messages"]
    assert workflow.portfolio.repository.assessment_history("SYN001") == before
    click(app, "Expand")
    page(app, "User guide")
    click(app, "Back to previous page")
    assert app.session_state.analysis_chat_expanded
    assert any(b.label == "Back to analysis" for b in app.button)
