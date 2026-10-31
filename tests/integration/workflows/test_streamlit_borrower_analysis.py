"""Connected analyst UI with real calculation/storage services and controlled agents."""

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from portfolio_helpers import portfolio_inputs, review_model
from streamlit.testing.v1 import AppTest

from credit_monitoring.domain.agent import AgentAnswer
from credit_monitoring.web import borrower_analysis, portfolio

APP = Path(__file__).resolve().parents[3] / "src/credit_monitoring/web/preview.py"


def click(app, label):
    next(b for b in app.button if b.label == label).click().run()
    assert not app.exception
    return app


def page(app, name):
    app.radio(key="preview_page").set_value(name).run()
    assert not app.exception


@pytest.fixture
def connected(monkeypatch, tmp_path):
    root = portfolio_inputs(tmp_path)
    monkeypatch.setattr(portfolio, "DEFAULT_DATA_ROOT", root)
    monkeypatch.setattr(portfolio, "DEFAULT_WORKING_DIR", tmp_path / "working")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    model = review_model()
    factory = portfolio.create_portfolio_service

    def create(**kwargs):
        return factory(**{**kwargs, "model": model})

    monkeypatch.setattr(portfolio, "create_portfolio_service", create)
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    return app, model


def assess(app, borrower="SYN001"):
    page(app, "Borrower analysis")
    app.selectbox(key="analysis_borrower").select(borrower).run()
    app.selectbox(key="analysis_period").select("2025-09-30").run()
    click(app, "Run assessment")
    return app.selectbox(key="analysis_version").value


def validate(app, rid, notes="Checked the inputs and source availability warnings."):
    for checkbox in app.checkbox:
        if checkbox.label.startswith("I "):
            checkbox.check()
    app.text_area(key=f"analysis_validation_notes_{rid}").set_value(notes)
    click(app, "Mark validated")


def test_ml_is_default_and_disabled_saved_versions_can_be_enabled(connected):
    app, _ = connected
    rid = assess(app)
    assert app.selectbox(key="analysis_prediction").value == "Logistic Regression"
    saved = borrower_analysis.get_workflow().portfolio.repository.get_assessment(rid)
    assert saved.ml_status == "complete"
    assert saved.prediction.breach_probability is not None
    app.selectbox(key="analysis_prediction").select("Off").run()
    click(app, "Run assessment")
    old_id = app.selectbox(key="analysis_version").value
    assert (
        borrower_analysis.get_workflow().portfolio.repository.get_assessment(old_id).ml_status
        == "disabled"
    )
    click(app, "Run assessment with ML")
    new_id = app.selectbox(key="analysis_version").value
    assert new_id != old_id
    assert app.selectbox(key="analysis_prediction").value == "Logistic Regression"
    assert (
        borrower_analysis.get_workflow().portfolio.repository.get_assessment(new_id).ml_status
        == "complete"
    )
    assert any(
        m.label == "Next-quarter breach probability" and m.value != "Unavailable"
        for m in app.metric
    )


def test_portfolio_opens_same_saved_borrower_and_refresh_retains_handoff(connected):
    app, model = connected
    app.selectbox(key="portfolio_borrower").select("SYN001").run()
    app.selectbox(key="portfolio_period").select("2025-09-30").run()
    click(app, "Run selected assessment")
    click(app, "Open borrower analysis")
    assert app.selectbox(key="analysis_borrower").value == "SYN001"
    rid = app.selectbox(key="analysis_version").value
    calculations = next(tab for tab in app.tabs if tab.label == "Calculations")
    table = calculations.dataframe[0].value
    assert table["Actual"].iloc[0] == pytest.approx(3.125)
    assert not any("Illustrative" in m.value for m in app.markdown)
    validate(app, rid)
    app.text_area(key=f"analysis_report_text_{rid}").set_value("Maintain monitoring.")
    click(app, "Save draft")
    click(app, "Send to risk manager")
    saved = borrower_analysis.get_workflow().repository.submissions()[0]
    assert saved["run_id"] == rid
    page(app, "Risk review")
    assert any(m.value == "Maintain monitoring." for m in app.markdown)
    app.button(key="preview_reset").click().run()
    assert not app.exception
    fresh = AppTest.from_file(str(APP), default_timeout=20).run()
    page(fresh, "Borrower analysis")
    fresh.selectbox(key="analysis_borrower").select("SYN001").run()
    fresh.selectbox(key="analysis_period").select("2025-09-30").run()
    assert fresh.selectbox(key="analysis_version").value == rid
    assert borrower_analysis.get_workflow().repository.submissions()[0] == saved
    assert model.respond.call_count == 0


def test_revised_inputs_create_new_version_and_preserve_validation_and_old_report(connected):
    app, _ = connected
    rid = assess(app)
    validate(app, rid)
    app.text_area(key=f"analysis_report_text_{rid}").set_value("Original assessment.")
    click(app, "Send to risk manager")
    original = borrower_analysis.get_workflow().repository.submissions()[0]
    app.multiselect(key=f"analysis_revision_metrics_{rid}").set_value(["reported_ebitda"]).run()
    app.number_input(key=f"analysis_revision_{rid}_reported_ebitda").set_value(10.0)
    app.text_input(key=f"analysis_reason_{rid}").set_value("Use corrected EBITDA.")
    click(app, "Recalculate")
    new_rid = app.selectbox(key="analysis_version").value
    assert new_rid != rid
    assert any("need validation" in m.value for m in app.info)
    app.text_area(key=f"analysis_report_text_{new_rid}").set_value("Revised assessment.")
    click(app, "Send to risk manager")
    assert any("Validate this assessment" in m.value for m in app.warning)
    assert borrower_analysis.get_workflow().repository.submissions()[0] == original
    app.selectbox(key="analysis_version").select(rid).run()
    assert any(m.value == "Validated." for m in app.success)


def test_breach_flag_and_handoff_are_saved_for_the_exact_assessment(connected):
    app, _ = connected
    page(app, "Borrower analysis")
    app.selectbox(key="analysis_borrower").select("SYN002").run()
    app.selectbox(key="analysis_period").select("2025-12-31").run()
    click(app, "Run assessment")
    rid = app.selectbox(key="analysis_version").value
    validate(app, rid)
    app.text_area(key=f"analysis_report_text_{rid}").set_value("Require a remediation plan.")
    click(app, "Send to risk manager")
    assert any("Flag this breach version" in m.value for m in app.warning)
    app.text_area(key=f"analysis_flag_explanation_{rid}").set_value("Leverage exceeds the limit.")
    app.text_input(key=f"analysis_flag_action_{rid}").set_value("Obtain a remediation plan.")
    click(app, "Add flag")
    click(app, "Send to risk manager")
    saved = borrower_analysis.get_workflow().repository.submissions()[0]
    assert saved["run_id"] == rid
    assert saved["payload"]["flags"][0]["payload"]["explanation"] == "Leverage exceeds the limit."


def test_missing_data_requires_exceptions_and_cutoff_errors_do_not_run(connected):
    app, _ = connected
    rid = assess(app, "SYN007")
    validate(app, rid, notes="")
    assert any("missing data" in m.value for m in app.warning)
    validate(app, rid, notes="Reconcile conflicting debt sources before a conclusion.")
    assert any(m.value == "Validated with exceptions." for m in app.success)
    app.date_input(key="analysis_cutoff").set_value(date(2025, 6, 30)).run()
    assert not app.exception
    assert any("cutoff must be on or after" in m.value for m in app.error)
    assert not any(b.label == "Run assessment" for b in app.button)


def test_credit_review_uses_selected_version_and_invalidates_previous_validation(
    connected, monkeypatch
):
    app, model = connected
    rid = assess(app)
    validate(app, rid)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    app.run()
    click(app, "Run agent review")
    assert model.respond.call_count == 4
    assert any("need validation" in m.value for m in app.info)
    validate(app, rid)
    app.text_area(key=f"analysis_report_text_{rid}").set_value("Reviewed the three perspectives.")
    click(app, "Send to risk manager")
    report = borrower_analysis.get_workflow().repository.submissions()[0]
    assert report["payload"]["review_id"]
    page(app, "Risk review")
    assert model.respond.call_count == 4
    assert any(m.value == "Reviewed the three perspectives." for m in app.markdown)


def test_chat_expand_hide_and_version_scope_share_real_conversation_object(connected, monkeypatch):
    app, _ = connected
    rid = assess(app)
    conversations = []

    class Conversation:
        closed = False

        def __init__(self, agent):
            self.service = agent.assessment_service
            self.questions = []

        def ask(self, question):
            self.questions.append(question)
            self.service.assess(
                "SYN001",
                self.service.assessment.period_end,
                self.service.assessment.information_cutoff,
                ml_enabled=False,
            )
            return AgentAnswer(answer="The saved leverage is 3.12x.", confidence="high")

        def close(self):
            self.closed = True

    def start(agent, **kwargs):
        conversation = Conversation(agent)
        conversations.append(conversation)
        return conversation

    monkeypatch.setattr(borrower_analysis.CreditAssessmentAgent, "start_conversation", start)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    app.run()
    app.chat_input(key=f"analysis_chat_input_panel_{rid}").set_value(
        "Explain the key concern using the saved assessment."
    ).run()
    assert not app.exception
    assert len(conversations) == 1
    assert len(app.session_state.analysis_chats[rid]["messages"]) == 2
    click(app, "Expand")
    app.chat_input(key=f"analysis_chat_input_expanded_{rid}").set_value(
        "What about headroom?"
    ).run()
    assert not app.exception
    assert len(conversations) == 1
    assert len(conversations[0].questions) == 2
    click(app, "Back to analysis")
    click(app, "Hide")
    assert not app.chat_input
    app.toggle(key="analysis_show_chat").set_value(True).run()
    assert len(app.session_state.analysis_chats[rid]["messages"]) == 4
    assert (
        len(borrower_analysis.get_workflow().portfolio.repository.assessment_history("SYN001")) == 1
    )
    app.checkbox(key=f"analysis_chat_recalc_panel_{rid}").check().run()
    app.chat_input(key=f"analysis_chat_input_panel_{rid}").set_value("Please recalculate.").run()
    assert not app.exception
    new_rid = app.selectbox(key="analysis_version").value
    assert new_rid != rid
    assert app.session_state.analysis_chats[new_rid]["messages"] == []
    assert borrower_analysis.get_workflow().validation(new_rid) is None
    app.selectbox(key="analysis_version").select(rid).run()
    assert len(app.session_state.analysis_chats[rid]["messages"]) == 6


def test_generated_suggestions_edit_send_and_review_context_without_extra_generation(
    connected, monkeypatch
):
    app, model = connected
    rid = assess(app)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    app.run()
    click(app, "Run agent review")
    assert model.respond.call_count == 4
    workflow = borrower_analysis.get_workflow()
    review = workflow.portfolio.repository.latest_review(rid)
    saved = workflow.portfolio.follow_up_service.load(
        workflow.portfolio.repository.get_assessment(rid), review
    )
    suggestion = saved.output.questions[0].question
    key = f"analysis_question_draft_{rid}"
    click(app, suggestion)
    assert app.text_area(key=key).value == suggestion
    assert model.respond.call_count == 4
    app.text_area(key=key).set_value("Explain the qualified argument in more detail.").run()
    click(app, suggestion)
    assert app.text_area(key=key).value == "Explain the qualified argument in more detail."
    click(app, "Expand")
    assert app.text_area(key=key).value == "Explain the qualified argument in more detail."
    click(app, "Back to analysis")
    questions = []

    class Conversation:
        closed = False

        def ask(self, question):
            questions.append(question)
            return AgentAnswer(
                answer="The recommendation qualifies both perspectives.", confidence="medium"
            )

    monkeypatch.setattr(
        borrower_analysis.CreditAssessmentAgent,
        "start_conversation",
        lambda *a, **k: Conversation(),
    )
    click(app, "Send question")
    assert len(questions) == 1
    assert review.review_id in questions[0]
    assert review.bearish.analysis.thesis in questions[0]
    assert review.recommendation.rationale in questions[0]
    assert app.text_area(key=key).value == ""
    assert model.respond.call_count == 4
    page(app, "User guide")
    click(app, "Back to previous page")
    assert model.respond.call_count == 4
    click(app, "Regenerate questions")
    assert model.respond.call_count == 5
    click(app, suggestion)
    click(app, "Run agent review")
    assert model.respond.call_count == 9
    assert app.text_area(key=key).value == ""
    assert workflow.portfolio.repository.latest_review(rid).review_id != review.review_id


def test_question_generation_failure_keeps_saved_analysis_and_needs_explicit_retry(
    connected, monkeypatch
):
    app, model = connected
    rid = assess(app)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    app.run()
    monkeypatch.setattr(
        "credit_monitoring.agents.follow_up_questions.FollowUpQuestionAgent.generate",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Provider unavailable")),
    )
    click(app, "Run agent review")
    assert model.respond.call_count == 3
    workflow = borrower_analysis.get_workflow()
    assert workflow.portfolio.repository.latest_review(rid).status == "complete"
    assert any(b.label == "Generate follow-up questions" for b in app.button)
    click(app, "Generate follow-up questions")
    assert any("Question generation failed" in w.value for w in app.warning)
    assert model.respond.call_count == 3
    assert len(workflow.portfolio.repository.assessment_history("SYN001")) == 1


def test_borrower_tables_restore_saved_results_input_trace_and_version_history(connected):
    app, model = connected
    first = assess(app)
    click(app, "Run assessment")
    app.selectbox(key="analysis_version").select(first).run()
    assert [tab.label for tab in app.tabs] == [
        "Overview",
        "Calculations",
        "Credit analysis",
        "Analyst handoff",
        "History",
    ]
    calculations = next(tab for tab in app.tabs if tab.label == "Calculations")
    summary = calculations.dataframe[0].value
    assert {"Covenant", "Actual", "Threshold", "Headroom", "Compliance"} <= set(summary.columns)
    saved = borrower_analysis.get_workflow().portfolio.repository.get_assessment(first)
    assert summary["Actual"].tolist() == [r.actual_value for r in saved.results]
    assert summary["Headroom"].tolist() == [r.headroom for r in saved.results]
    overview = next(tab for tab in app.tabs if tab.label == "Overview")
    pd.testing.assert_frame_equal(summary, overview.dataframe[0].value)
    trace = next(t.value for t in calculations.dataframe if "Input" in t.value.columns).set_index(
        "Input"
    )
    financials = saved.results[0].financial_inputs["financial_period"]
    assert trace.loc["Total Debt", "Value"] == financials["metrics"]["total_debt"]
    assert financials["source_file"] in trace.loc["Total Debt", "Source"]
    history = next(tab for tab in app.tabs if tab.label == "History").dataframe[0].value
    assert len(history) == 2
    assert history.loc[history["State"] == "Selected", "Version"].tolist() == ["Assessment v1"]
    assert any(
        e.label == "Suggested follow-up questions" and not e.proto.expanded for e in app.expander
    )
    assert any(p.proto.popover.label == "Assessment settings" for p in app.get("popover"))
    assert not any(e.label.startswith("How to") for e in app.expander)
    assert model.respond.call_count == 0


@pytest.mark.parametrize(
    "borrower,period",
    [("SYN007", "2025-09-30"), ("SYN006", "2025-09-30"), ("SYN010", "2025-06-30")],
)
def test_restored_tables_keep_missing_waived_and_inactive_outcomes(connected, borrower, period):
    app, model = connected
    page(app, "Borrower analysis")
    app.selectbox(key="analysis_borrower").select(borrower).run()
    app.selectbox(key="analysis_period").select(period).run()
    click(app, "Run assessment")
    rid = app.selectbox(key="analysis_version").value
    saved = borrower_analysis.get_workflow().portfolio.repository.get_assessment(rid)
    calculations = next(tab for tab in app.tabs if tab.label == "Calculations")
    table = calculations.dataframe[0].value
    for row, result in zip(table.to_dict("records"), saved.results, strict=True):
        assert row["Compliance"] == portfolio.STATUS_LABELS[result.compliance_status]
        if result.actual_value is None:
            assert pd.isna(row["Actual"])
        else:
            assert row["Actual"] == result.actual_value
        if result.headroom is None:
            assert pd.isna(row["Headroom"])
    assert model.respond.call_count == 0


def select_directory(app, *, rows=(), cells=()):
    table = next(t for t in app.dataframe if t.key and "analysis_directory_" in t.key)
    states = app._tree.get_widget_states()
    states.widgets.add(
        id=table.proto.id,
        string_value=json.dumps(
            {"selection": {"rows": list(rows), "cells": list(cells), "columns": []}}
        ),
    )
    app._run(states)
    assert not app.exception


def test_borrower_list_is_visible_before_assessment_and_with_invalid_dates(connected):
    app, model = connected
    page(app, "Borrower analysis")
    directory = app.dataframe[0].value
    assert len(directory) == 12
    assert {"Borrower", "ID", "Compliance"} <= set(directory.columns)
    assert set(directory["Compliance"]) == {"Not assessed"}
    assert not app.selectbox(key="analysis_borrower").value == ""
    assert any("Not assessed" in item.value for item in app.info)
    app.selectbox(key="analysis_period").select("2025-09-30").run()
    app.date_input(key="analysis_cutoff").set_value(date(2025, 6, 30)).run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 12
    assert {"Borrower", "ID", "Sector"} == set(app.dataframe[0].value.columns)
    assert any("cutoff must be" in item.value for item in app.error)
    assert model.respond.call_count == 0
    assert borrower_analysis.get_workflow().portfolio.repository.all_assessments() == []


def test_borrower_directory_cell_row_search_and_manual_selection_share_saved_analysis(connected):
    app, model = connected
    run_id = assess(app, "SYN001")
    directory = app.dataframe[0].value
    row = directory.index[directory["ID"] == "SYN002"][0]
    select_directory(app, cells=[[int(row), "Borrower"]])
    assert app.selectbox(key="analysis_borrower").value == "SYN002"
    assert any("Not assessed" in item.value for item in app.info)
    row = app.dataframe[0].value.index[app.dataframe[0].value["ID"] == "SYN001"][0]
    select_directory(app, rows=[int(row)])
    assert app.selectbox(key="analysis_borrower").value == "SYN001"
    assert app.selectbox(key="analysis_version").value == run_id
    app.text_input(key="analysis_directory_search").set_value("elmwood").run()
    assert app.dataframe[0].value["ID"].tolist() == ["SYN003"]
    select_directory(app, cells=[[0, "Borrower"]])
    assert app.selectbox(key="analysis_borrower").value == "SYN003"
    app.selectbox(key="analysis_borrower").select("SYN008").run()
    app.run()
    assert app.selectbox(key="analysis_borrower").value == "SYN008"
    app.text_input(key="analysis_directory_search").set_value("no-matching-borrower").run()
    assert any("No borrowers match" in item.value for item in app.info)
    assert model.respond.call_count == 0
    assert len(borrower_analysis.get_workflow().portfolio.repository.all_assessments()) == 1
