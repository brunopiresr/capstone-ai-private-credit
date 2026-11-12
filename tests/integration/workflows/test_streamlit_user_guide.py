"""Help remains read-only and preserves the analyst's selected working context."""

from pathlib import Path

import pytest
from portfolio_helpers import portfolio_inputs
from streamlit.testing.v1 import AppTest
from workspace_ui_helpers import page, prediction_mode

from credit_monitoring.web import borrower_analysis, portfolio
from credit_monitoring.web.user_guide import TOPICS

APP = Path(__file__).resolve().parents[3] / "src/credit_monitoring/web/preview.py"


def click(app, label):
    button = (
        app.button(key="analysis_run")
        if label == "Run assessment"
        else next(b for b in app.button if b.label == label)
    )
    button.click().run()
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


def test_every_guide_topic_without_services_or_credentials(app, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("The user guide must not execute application services.")

    monkeypatch.setattr(portfolio, "create_portfolio_service", forbidden)
    monkeypatch.setattr(
        "credit_monitoring.agents.follow_up_questions.FollowUpQuestionAgent.generate", forbidden
    )
    page(app, "User guide")
    for topic in TOPICS:
        app.selectbox(key="guide_topic").select(topic).run()
        assert not app.exception
        assert any(s.value == topic for s in app.subheader)
    assert not app.chat_input
    assert "analysis_chats" not in app.session_state


def test_portfolio_selections_and_invitation_survive_guide_and_reset(app):
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
    page(app, "Settings")
    click(app, "Reset navigation")
    page(app, "User guide")
    click(app, "Open Borrower analysis")
    assert app.session_state.preview_page == "Borrower analysis"


def test_old_assessment_version_dates_prediction_chat_and_draft_survive_help(app):
    page(app, "Borrower analysis")
    app.selectbox(key="analysis_borrower").select("SYN001").run()
    app.selectbox(key="analysis_period").select("2025-09-30").run()
    prediction_mode(app, "Off")
    click(app, "Run assessment")
    original = app.selectbox(key="analysis_version").value
    click(app, "Run assessment")
    app.selectbox(key="analysis_version").select(original).run()
    app.toggle(key="analysis_show_chat").set_value(True).run()
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
    assert app.session_state.analysis_prediction == "Off"
    assert app.selectbox(key="analysis_period").value == "2025-09-30"
    assert app.text_area(key=key).value == "An unfinished question."
    assert app.session_state.analysis_chats[original]["messages"] == state["messages"]
    assert workflow.portfolio.repository.assessment_history("SYN001") == before
    click(app, "Expand")
    page(app, "User guide")
    click(app, "Back to previous page")
    assert not app.session_state.analysis_chat_expanded
    assert app.toggle(key="analysis_show_chat").value
    assert app.text_area(key=key).value == "An unfinished question."
