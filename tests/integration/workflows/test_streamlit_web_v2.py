"""Integration tests for the modern role-based Credit Monitor V2 interface."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from portfolio_helpers import portfolio_inputs, review_model
from streamlit.runtime.scriptrunner_utils.script_run_context import ScriptRunContext
from streamlit.testing.v1 import AppTest

from credit_monitoring.application.bootstrap import create_portfolio_service
from credit_monitoring.web import portfolio as portfolio_page
from credit_monitoring.web_v2.components import chat as chat_ui

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


@pytest.fixture
def review_app(monkeypatch, tmp_path):
    model = review_model()
    data_root = portfolio_inputs(tmp_path)
    portfolio = create_portfolio_service(
        data_root=data_root, working_dir=tmp_path / "working", model=model
    )
    monkeypatch.setattr(portfolio_page, "DEFAULT_DATA_ROOT", data_root)
    monkeypatch.setattr(portfolio_page, "DEFAULT_WORKING_DIR", tmp_path / "working")
    monkeypatch.setattr(portfolio_page, "get_portfolio_service", lambda *args: portfolio)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = AppTest.from_file(str(APP_V2), default_timeout=20).run()
    assert not app.exception
    return app, portfolio, model


def test_v2_ai_review_saves_and_displays_selected_assessment_review(review_app):
    app, portfolio, model = review_app
    review_button = next(b for b in app.button if "AI Credit Review" in b.label)
    assert review_button.disabled
    next(b for b in app.button if "Run Full Assessment" in b.label).click().run()
    assert not app.exception
    selected_id = app.session_state.v2_selected_borrower
    assessment = next(
        e.assessment
        for e in portfolio.snapshot(period_end=None, cutoff=app.date_input[0].value)
        if e.borrower_id == selected_id
    )
    rid = assessment.assessment_run_id
    next(b for b in app.button if "AI Credit Review" in b.label).click().run()
    assert model.respond.call_count == 0
    app.text_input(key=f"v2_review_question_{rid}").set_value("Review the existing exposure.")
    app.text_area(key=f"v2_review_criteria_{rid}").set_value(
        " Assess covenant compliance. \n\n Assess headroom trends. "
    )
    next(b for b in app.button if b.label == "Submit Review").click().run()
    assert not app.exception
    review = portfolio.repository.latest_review(rid)
    assert review is not None and review.status == "complete"
    assert review.snapshot.assessment_run_id == rid
    assert review.decision_context.question == "Review the existing exposure."
    assert review.decision_context.credit_criteria == (
        "Assess covenant compliance.",
        "Assess headroom trends.",
    )
    assert model.respond.call_count == 4  # Bull, bear, recommendation, follow-up questions.
    assert any("AI Credit Review Results" in m.value for m in app.markdown)
    assert any("AI Credit Review" in s.value and "Complete" in s.value for s in app.success)
    app.run()
    assert not app.exception
    assert portfolio.repository.latest_review(rid) == review
    assert model.respond.call_count == 4


@pytest.mark.parametrize("field", ["question", "criteria"])
def test_v2_ai_review_requires_question_and_criteria(app_v2, monkeypatch, field):
    app = app_v2
    next(b for b in app.button if "Run Full Assessment" in b.label).click().run()
    assert not app.exception
    review = Mock()
    monkeypatch.setattr(
        "credit_monitoring.application.portfolio_service.PortfolioService.review", review
    )
    next(b for b in app.button if "AI Credit Review" in b.label).click().run()
    controls = app.text_input if field == "question" else app.text_area
    next(c for c in controls if c.key and c.key.startswith(f"v2_review_{field}_")).set_value(
        " \n " if field == "criteria" else " "
    )
    next(b for b in app.button if b.label == "Submit Review").click().run()
    assert not app.exception
    assert any("Supply a review question" in w.value for w in app.error)
    review.assert_not_called()


def test_v2_ai_review_failure_keeps_assessment_visible(app_v2, monkeypatch):
    app = app_v2
    next(b for b in app.button if "Run Full Assessment" in b.label).click().run()
    assert not app.exception
    monkeypatch.setattr(
        "credit_monitoring.application.portfolio_service.PortfolioService.review",
        Mock(side_effect=RuntimeError("Private provider details")),
    )
    next(b for b in app.button if "AI Credit Review" in b.label).click().run()
    next(b for b in app.button if b.label == "Submit Review").click().run()
    assert not app.exception
    assert any("Agent review failed (RuntimeError)" in e.value for e in app.error)
    assert all("Private provider details" not in e.value for e in app.error)
    assert any("Covenant Compliance & Headroom" in m.value for m in app.markdown)


def button(app, label):
    return next(b for b in app.button if label in b.label)


def assess(app):
    button(app, "Run Full Assessment").click().run()
    assert not app.exception


def test_v2_shared_borrower_selection_is_independent_of_table_filters(app_v2):
    app = app_v2
    borrowers = app.dataframe[0].value
    selected = borrowers.iloc[-1]
    app.selectbox(key="v2_selected_borrower").set_value(selected["ID"]).run()
    assert any(f"Analysis for {selected['Borrower']}" in m.value for m in app.markdown)
    assert any(selected["ID"] in c.value and "Information cutoff:" in c.value for c in app.caption)
    app.text_input(key="v2_analyst_search").set_value("northstar").run()
    assert app.session_state.v2_selected_borrower == selected["ID"]
    assert len(app.selectbox(key="v2_selected_borrower").options) == len(borrowers)
    app.selectbox(key="v2_analyst_status_filter").set_value("Compliant").run()
    assert app.session_state.v2_selected_borrower == selected["ID"]
    assess(app)
    # Both Analysis and Flag & Triage use the newly selected borrower's assessment.
    assert selected["Borrower"] in next(s.value for s in app.success if "Assessment" in s.value)
    run_id = app.chat_input[0].key.removeprefix("analyst_input_")
    assert app.text_input(key=f"v2_analyst_{run_id}") is not None
    assert any(c.type == "selectbox" for c in app.main.children.values())


def test_v2_assessment_feedback_persists_and_can_be_dismissed(app_v2):
    app = app_v2
    assess(app)
    original = [s.value for s in app.success]
    assert any("covenant tests saved" in message for message in original)
    app.run()
    assert [s.value for s in app.success] == original
    button(app, "Dismiss message").click().run()
    assert not app.success
    assert any("Covenant Compliance & Headroom" in m.value for m in app.markdown)


def test_v2_assessment_failure_retains_saved_results_and_feedback(app_v2, monkeypatch):
    app = app_v2
    assess(app)
    previous_input_key = app.chat_input[0].key
    failing = Mock(side_effect=RuntimeError("private assessment details"))
    monkeypatch.setattr(
        "credit_monitoring.application.borrower_workflow.BorrowerWorkflow.assess", failing
    )
    assess(app)
    assert app.chat_input[0].key == previous_input_key
    assert any("Assessment failed" in e.value and "retry" in e.value for e in app.error)
    assert all("private assessment details" not in e.value for e in app.error)
    app.run()
    assert any("Assessment failed" in e.value for e in app.error)
    failing.assert_called_once()


def test_v2_no_eligible_period_disables_assessment(app_v2, monkeypatch):
    app = app_v2
    run = Mock()
    monkeypatch.setattr(
        "credit_monitoring.application.borrower_workflow.BorrowerWorkflow.assess", run
    )
    cutoff = app.date_input(key="v2_cutoff_select")
    cutoff.set_value(date.fromisoformat(cutoff.proto.min)).run()
    assert not app.exception
    assert button(app, "Run Full Assessment").disabled
    assert any("No eligible financial reporting period" in i.value for i in app.info)
    run.assert_not_called()


def test_v2_review_open_cancel_and_borrower_drafts_make_no_service_calls(app_v2, monkeypatch):
    app = app_v2
    assess(app)
    review = Mock()
    monkeypatch.setattr(
        "credit_monitoring.application.portfolio_service.PortfolioService.review", review
    )
    borrower = app.session_state.v2_selected_borrower
    other = next(bid for bid in app.dataframe[0].value["ID"] if bid != borrower)
    button(app, "AI Credit Review").click().run()
    next(c for c in app.text_input if c.label == "Credit review question").set_value("Only A")
    button(app, "Cancel").click().run()
    assert not any(c.label == "Credit review question" for c in app.text_input)
    app.selectbox(key="v2_selected_borrower").set_value(other).run()
    assess(app)
    button(app, "AI Credit Review").click().run()
    assert next(c.value for c in app.text_input if c.label == "Credit review question") != "Only A"
    review.assert_not_called()


def test_v2_review_failure_identifies_earlier_saved_result(review_app, monkeypatch):
    app, portfolio, model = review_app
    assess(app)
    button(app, "AI Credit Review").click().run()
    button(app, "Submit Review").click().run()
    run_id = app.chat_input[0].key.removeprefix("analyst_input_")
    earlier = portfolio.repository.latest_review(run_id)
    monkeypatch.setattr(portfolio, "review", Mock(side_effect=RuntimeError("private details")))
    button(app, "AI Credit Review").click().run()
    button(app, "Submit Review").click().run()
    assert not app.exception
    assert portfolio.repository.latest_review(run_id) == earlier
    assert any("Showing the earlier saved review" in c.value for c in app.caption)
    app.run()
    assert any("Agent review failed" in e.value for e in app.error)
    assert model.respond.call_count == 4


@pytest.mark.parametrize("status", ["incomplete", "blocked"])
def test_v2_review_order_tabs_and_collapsed_diagnostics(review_app, monkeypatch, status):
    app, portfolio, _ = review_app
    original_review = portfolio.review

    def partial_review(run_id, context):
        complete = original_review(run_id, context)
        unavailable = complete.bullish.model_copy(
            update={
                "analysis": None,
                "execution": complete.bullish.execution.model_copy(
                    update={"status": "failed", "error_code": "provider_unavailable"}
                ),
            }
        )
        partial = complete.model_copy(
            update={
                "review_id": str(uuid4()),
                "status": status,
                "bullish": unavailable,
                "recommendation": complete.recommendation.model_copy(update={"action": "defer"}),
                "issues": ("Evidence availability is limited.",),
            }
        )
        portfolio.repository.save_review(partial)
        return partial

    monkeypatch.setattr(portfolio, "review", partial_review)
    assess(app)
    button(app, "AI Credit Review").click().run()
    button(app, "Submit Review").click().run()
    assert not app.exception
    assert [t.label for t in app.tabs if t.label in {"Recommendation", "Bullish", "Bearish"}] == [
        "Recommendation",
        "Bullish",
        "Bearish",
    ]
    assert any(f"Status: {status.title()}" in c.value for c in app.caption)
    assert any(m.value == "**Defer**" for m in app.markdown)
    assert any(status.title() in i.value and "AI Credit Review" in i.value for i in app.info)
    assert not app.warning
    warning = next(e for e in app.expander if "⚠ Warnings (" in e.label)
    assert warning.proto.expanded is False
    assert any("provider_unavailable" in m.value for m in warning.markdown)
    elements = list(app.tabs[1])
    covenant_index = next(
        i
        for i, e in enumerate(elements)
        if e.type == "markdown" and "Covenant Compliance & Headroom" in e.value
    )
    review_index = next(
        i
        for i, e in enumerate(elements)
        if e.type == "markdown" and "AI Credit Review Results" in e.value
    )
    trend_index = next(
        i
        for i, e in enumerate(elements)
        if e.type == "expander" and "Historical Headroom Trends" in e.label
    )
    chat_index = next(
        i
        for i, e in enumerate(elements)
        if e.type == "subheader" and "Analyst Assistant" in e.value
    )
    assert covenant_index < review_index < trend_index < chat_index


@pytest.mark.parametrize("input_method", ["typed", "suggested"])
@pytest.mark.parametrize("outcome", ["success", "fallback", "failure"])
def test_v2_chat_controls_lock_before_answer_and_restore(
    app_v2, monkeypatch, input_method, outcome
):
    app = app_v2
    assess(app)
    run_id = app.chat_input[0].key.removeprefix("analyst_input_")
    busy_key = f"analyst_{run_id}_chat_busy"
    history_key = f"analyst_chat_history_{run_id}"
    controls = {}
    enqueue = ScriptRunContext.enqueue

    def capture(context, message):
        if message.HasField("delta") and message.delta.HasField("new_element"):
            element = message.delta.new_element
            if element.HasField("button"):
                controls[element.button.label] = element.button.disabled
            if element.HasField("chat_input"):
                controls["input"] = element.chat_input.disabled
        return enqueue(context, message)

    monkeypatch.setattr(ScriptRunContext, "enqueue", capture)
    original_answer = chat_ui._answer_question

    def answer(workflow, assessment, question):
        import streamlit as st

        assert st.session_state[busy_key] is True
        assert st.session_state[history_key][-1] == {"role": "user", "content": question}
        assert controls["input"] is True
        assert controls["Clear Chat"] is True
        assert controls["Why did Interest Coverage decline?"] is True
        if outcome == "failure":
            raise RuntimeError("private provider details")
        if outcome == "fallback":
            return original_answer(workflow, assessment, question)
        return {"role": "assistant", "content": "A completed answer with evidence."}

    backend = Mock(side_effect=answer)
    monkeypatch.setattr(chat_ui, "_answer_question", backend)
    if input_method == "typed":
        app.chat_input[0].set_value("Explain covenant headroom").run()
    else:
        button(app, "Interest Coverage").click().run()
    assert not app.exception
    backend.assert_called_once()
    assert len(app.chat_message) == 2
    assert not app.chat_input[0].disabled
    assert not button(app, "Clear Chat").disabled
    assert app.session_state[busy_key] is False
    assert all("private provider details" not in m.value for m in app.markdown)
    app.run()
    backend.assert_called_once()
    app.chat_input[0].set_value("What are the key risks?").run()
    assert not app.exception
    assert backend.call_count == 2
    assert len(app.chat_message) == 4
    button(app, "Clear Chat").click().run()
    assert not app.chat_message


def test_v2_chat_context_switch_discards_pending_work_and_keeps_history(app_v2, monkeypatch):
    app = app_v2
    assess(app)
    button(app, "Interest Coverage").click().run()
    borrower = app.session_state.v2_selected_borrower
    run_id = app.chat_input[0].key.removeprefix("analyst_input_")
    app.session_state[f"analyst_{run_id}_pending_question"] = "Stale question for A"
    app.session_state[f"analyst_{run_id}_chat_busy"] = True
    backend = Mock()
    monkeypatch.setattr(chat_ui, "_answer_question", backend)
    other = next(bid for bid in app.dataframe[0].value["ID"] if bid != borrower)
    app.selectbox(key="v2_selected_borrower").set_value(other).run()
    assert not app.chat_input
    assess(app)
    assert not app.chat_message
    app.selectbox(key="v2_selected_borrower").set_value(borrower).run()
    assert not app.exception
    assert len(app.chat_message) == 2
    backend.assert_not_called()
    assess(app)
    assert not app.chat_message  # A new assessment gets a new conversation.


def test_v2_risk_copilot_keeps_default_layout_and_separate_history(app_v2):
    from credit_monitoring.web_v2.app import get_workflow

    app = app_v2
    assess(app)
    button(app, "Interest Coverage").click().run()
    run_id = app.chat_input[0].key.removeprefix("analyst_input_")
    workflow = get_workflow()
    workflow.validate(run_id, checks=(True, True, True), notes="Reviewed the saved assessment.")
    workflow.flag(
        run_id,
        category="Performance",
        severity="High",
        explanation="Monitor performance.",
        action="Obtain an update.",
    )
    workflow.save_report(run_id, text="Analyst report ready for review.", submit=True)

    def transcript_heights():
        return [
            node.proto.height_config.pixel_height
            for node in app.main
            if node.type == "flex_container" and node.proto.HasField("height_config")
        ]

    assert 500 in transcript_heights()
    app.segmented_control(key="v2_active_role").set_value("🛡️ Risk Manager").run()
    assert not app.exception
    assert 320 in transcript_heights()
    assert 500 not in transcript_heights()
    assert not app.chat_message
    app.chat_input[0].set_value("Explain the covenant headroom").run()
    assert not app.exception
    assert len(app.chat_message) == 2
    assert len(app.session_state[f"risk_copilot_chat_history_{run_id}"]) == 2
    assert len(app.session_state[f"analyst_chat_history_{run_id}"]) == 2
    app.segmented_control(key="v2_active_role").set_value("👤 Credit Analyst").run()
    assert not app.exception
    assert len(app.chat_message) == 2


@pytest.fixture
def manager_app(app_v2):
    from credit_monitoring.web_v2.app import get_workflow

    app = app_v2
    workflow = get_workflow()
    period = app.date_input(key="v2_cutoff_select").value
    for borrower_id, severity in (("SYN001", "Low"), ("SYN002", "Critical"), ("SYN003", "High")):
        assessment = workflow.assess(borrower_id, period, period, prediction_mode="Off")
        run_id = assessment.assessment_run_id
        workflow.validate(run_id, checks=(True, True, True), notes="Reviewed the saved assessment.")
        workflow.flag(
            run_id,
            category="Performance",
            severity=severity,
            explanation=f"Review performance of {borrower_id}.",
            action="Obtain an update.",
        )
        workflow.save_report(
            run_id, text=f"Saved analyst observations for {borrower_id}.", submit=True
        )
    app.segmented_control(key="v2_active_role").set_value("🛡️ Risk Manager").run()
    assert not app.exception
    return app


def click_queue_review(app, row):
    queue = app.tabs[0].dataframe[0]
    states = app._tree.get_widget_states()
    trigger = states.widgets.add(id=queue.proto.button_click_widgets["Review"])
    trigger.string_trigger_value.data = json.dumps({"row": row, "label": "Review"})
    app._run(states)
    assert not app.exception


def test_v2_manager_queue_review_actions_open_the_correct_priority_sorted_borrower(manager_app):
    app = manager_app
    queue = app.tabs[0].dataframe[0]
    assert queue.value["ID"].tolist() == ["SYN002", "SYN003", "SYN001"]
    assert queue.value["Review"].tolist() == ["Review"] * 3
    config = json.loads(queue.proto.columns)["Review"]
    assert config["type_config"]["type"] == "button"
    assert config["pinned"] is True
    assert not app.tabs[0].selectbox
    assert app.tabs[1].selectbox[0].key == "v2_risk_selected_borrower"

    for row, borrower_id in enumerate(queue.value["ID"]):
        click_queue_review(app, row)
        assert app.session_state.v2_risk_tabs == "✍️ Review & Sign-Off"
        assert app.selectbox(key="v2_risk_selected_borrower").value == borrower_id
        assert any(
            f"Saved analyst observations for {borrower_id}." in m.value for m in app.markdown
        )
        app.run()
        assert app.selectbox(key="v2_risk_selected_borrower").value == borrower_id


def test_v2_manager_can_change_borrower_inside_review_and_leave_the_tab(manager_app):
    app = manager_app
    click_queue_review(app, 0)
    app.selectbox(key="v2_risk_selected_borrower").set_value("SYN001").run()
    assert not app.exception
    assert app.session_state.v2_risk_tabs == "✍️ Review & Sign-Off"
    assert any("Saved analyst observations for SYN001." in m.value for m in app.markdown)
    # A consumed row action must not redirect the manager again on unrelated reruns.
    app.session_state.v2_risk_tabs = "📑 Board Report Studio"
    app.run()
    assert app.session_state.v2_risk_tabs == "📑 Board Report Studio"
    assert app.selectbox(key="v2_risk_selected_borrower").value == "SYN001"


def test_v2_manager_date_change_clears_unavailable_borrower_and_empty_queue(manager_app):
    app = manager_app
    click_queue_review(app, 1)
    cutoff = app.date_input(key="v2_cutoff_select")
    cutoff.set_value(date.fromisoformat(cutoff.proto.min)).run()
    assert not app.exception
    assert app.session_state.v2_risk_selected_borrower == ""
    assert not app.tabs[0].dataframe
    assert not app.tabs[1].selectbox
    assert any("No flagged borrowers are available for review" in i.value for i in app.info)


def test_v2_board_draft_generation_selects_saved_report_and_does_not_repeat(manager_app):
    from credit_monitoring.web_v2.app import get_workflow

    app = manager_app
    repository = get_workflow().repository
    assert not repository.board_reports()

    for title in ("First committee report", "Second committee report"):
        app.selectbox(key="v2_board_report_select").set_value("new").run()
        app.text_input(key="v2_new_title").set_value(title)
        button(app, "Generate Draft from Current Portfolio").click().run()
        assert not app.exception
        saved = repository.board_reports()[0]
        report_id = saved["report_id"]
        assert app.selectbox(key="v2_board_report_select").value == report_id
        assert saved["payload"]["title"] == title
        assert saved["state"] == "draft"
        assert app.text_area(key=f"v2_rep_sum_{report_id}").value == saved["payload"]["summary"]
        assert len(app.tabs[2].dataframe[0].value) == 3
        assert any(f"Report draft {report_id} generated!" in s.value for s in app.success)

        reports_before_rerun = repository.board_reports()
        app.run()
        assert not app.exception
        assert repository.board_reports() == reports_before_rerun
        assert app.selectbox(key="v2_board_report_select").value == report_id

    assert len(repository.board_reports()) == 2
