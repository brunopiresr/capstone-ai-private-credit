"""Manager and board UI over real stored submissions and controlled model responses."""

import json
from datetime import date
from pathlib import Path

import pytest
from portfolio_helpers import portfolio_inputs, review_model
from streamlit.testing.v1 import AppTest

from credit_monitoring.web import portfolio
from credit_monitoring.web.risk_review import get_manager

APP = Path(__file__).resolve().parents[3] / "src/credit_monitoring/web/preview.py"


def click(app, label):
    next(b for b in app.button if b.label == label).click().run()
    assert not app.exception


def page(app, label):
    app.radio(key="preview_page").set_value(label).run()
    assert not app.exception


def seed_submission(manager, borrower, period, *, with_review=False):
    from credit_monitoring.domain.credit_review import ExposureDecisionContext

    assessment = manager.analyst.assess(borrower, period, date(2025, 12, 31))
    rid = assessment.assessment_run_id
    if with_review:
        manager.portfolio.review(
            rid,
            ExposureDecisionContext(
                question="Review this exposure.", credit_criteria=("Headroom",)
            ),
        )
    manager.analyst.validate(rid, checks=(True, True, True), notes="Reviewed sources and gaps.")
    manager.analyst.flag(
        rid,
        category="Performance",
        severity="High",
        explanation=f"Monitor {borrower} performance.",
        action="Obtain an update.",
    )
    return manager.analyst.save_report(
        rid, text=f"Saved analyst report for {borrower}.", submit=True
    )


@pytest.fixture
def connected(monkeypatch, tmp_path):
    root = portfolio_inputs(tmp_path)
    monkeypatch.setattr(portfolio, "DEFAULT_DATA_ROOT", root)
    monkeypatch.setattr(portfolio, "DEFAULT_WORKING_DIR", tmp_path / "working")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    monkeypatch.setattr(
        "requests.sessions.Session.request", lambda *a, **k: pytest.fail("Unexpected HTTP")
    )
    model = review_model()
    factory = portfolio.create_portfolio_service

    def create(**kwargs):
        return factory(**{**kwargs, "model": model})

    monkeypatch.setattr(portfolio, "create_portfolio_service", create)
    manager = get_manager()
    first = seed_submission(manager, "SYN001", date(2025, 9, 30), with_review=True)
    second = seed_submission(manager, "SYN002", date(2025, 12, 31))
    app = AppTest.from_file(str(APP), default_timeout=25).run()
    assert not app.exception
    return app, model, first, second


def select_risk(app, borrower="SYN001"):
    page(app, "Risk review")
    app.selectbox(key="risk_borrower").select(borrower).run()
    assert not app.exception


def test_real_queue_cell_selection_review_and_feedback_persist(connected):
    app, model, first, _ = connected
    select_risk(app)
    assert app.dataframe[0].value["ID"].tolist() == ["SYN001", "SYN002"]
    assert app.dataframe[0].value["Severity"].tolist() == ["High", "High"]
    assert app.dataframe[0].value["Compliance"].tolist() == ["Compliant", "Breach"]
    assert not any("sample" in m.value.lower() for m in app.markdown)
    headings = [h.value for h in app.subheader]
    assert headings.index("Recommendation agent") < headings.index("Your review")

    def dispatch(rows, cells):
        table = app.dataframe[0]
        states = app._tree.get_widget_states()
        states.widgets.add(
            id=table.proto.id,
            string_value=json.dumps({"selection": {"rows": rows, "cells": cells, "columns": []}}),
        )
        app._run(states)
        assert not app.exception

    dispatch([], [[1, "Borrower"]])
    assert app.selectbox(key="risk_borrower").value == "SYN002"
    dispatch([0], [[1, "Borrower"]])
    assert app.selectbox(key="risk_borrower").value == "SYN001"
    click(app, "Mark reviewed")
    assert any("Add a manager observation" in item.value for item in app.warning)
    app.text_area(key=f"risk_comment_{first}").set_value("Reviewed performance.")
    click(app, "Save comment")
    app.text_area(key=f"risk_recommendation_{first}").set_value("Maintain with monthly updates.")
    click(app, "Mark reviewed")
    assert get_manager().state(get_manager().repository.submission(first)) == "Reviewed"
    app.radio(key="risk_queue_filter").set_value("Reviewed").run()
    assert app.dataframe[0].value["ID"].tolist() == ["SYN001"]
    click(app, "Open borrower analysis")
    assert app.selectbox(key="analysis_borrower").value == "SYN001"
    assert any(m.value == "Reviewed performance." for m in app.markdown)
    assert any(m.value == "Maintain with monthly updates." for m in app.markdown)
    fresh = AppTest.from_file(str(APP), default_timeout=25).run()
    select_risk(fresh)
    assert any(m.value == "Saved analyst report for SYN001." for m in fresh.markdown)
    assert model.respond.call_count == 4


def test_manager_context_rerun_compares_versions_and_needs_response_acceptance(connected):
    app, model, first, _ = connected
    select_risk(app)
    original_review = get_manager().repository.submission(first)["payload"]["review_id"]
    app.text_input(key=f"risk_question_{first}").set_value("Assess delayed collections.")
    app.text_area(key=f"risk_context_{first}").set_value(
        "Management expects collections in February."
    )
    app.text_input(key=f"risk_source_{first}").set_value("Management letter")
    app.date_input(key=f"risk_available_{first}").set_value(date(2026, 1, 10))
    app.date_input(key=f"risk_review_cutoff_{first}").set_value(date(2026, 1, 10))
    click(app, "Run context-only review")
    request = get_manager().repository.requests("SYN001")[0]
    assert request["state"] == "response_ready"
    assert request["payload"]["review_id"] != original_review
    assert model.respond.call_count == 8
    assert any("Review cutoff" in m.value or "Credit review cutoff" in m.value for m in app.caption)
    app.text_area(key=f"risk_recommendation_{first}").set_value("Monitor collections weekly.")
    click(app, "Mark reviewed")
    assert any("outstanding requests" in m.value for m in app.warning)
    click(app, "Accept response")
    click(app, "Mark reviewed")
    assert get_manager().state(get_manager().repository.submission(first)) == "Reviewed"
    assert len(get_manager().portfolio.repository.assessment_history("SYN001")) == 1


def test_correction_request_returns_to_analyst_and_back_to_manager(connected):
    app, _, first, _ = connected
    select_risk(app)
    app.selectbox(key=f"risk_request_kind_{first}").select("correction")
    app.text_input(key=f"risk_question_{first}").set_value("Recheck the reported financial inputs.")
    click(app, "Send analysis request")
    request = get_manager().repository.requests("SYN001")[0]
    rid = request["request_id"]
    click(app, "Open borrower analysis")
    click(app, "Run assessment")
    new_run = app.selectbox(key="analysis_version").value
    for checkbox in app.checkbox:
        if checkbox.label.startswith("I "):
            checkbox.check()
    app.text_area(key=f"analysis_validation_notes_{new_run}").set_value("Rechecked source figures.")
    click(app, "Mark validated")
    app.text_area(key=f"analysis_report_text_{new_run}").set_value("Recalculated and checked.")
    click(app, "Send to risk manager")
    app.text_area(key=f"request_response_text_{rid}").set_value(
        "New calculations and validation submitted."
    )
    click(app, "Submit response")
    assert get_manager().repository.request(rid)["state"] == "response_ready"
    select_risk(app)
    new_sid = app.selectbox(key="risk_submission_SYN001").value
    assert new_sid != first
    click(app, "Accept response")
    app.text_area(key=f"risk_recommendation_{new_sid}").set_value("Maintain with monitoring.")
    click(app, "Mark reviewed")
    assert get_manager().state(get_manager().repository.submission(new_sid)) == "Reviewed"


def test_board_draft_refresh_final_snapshot_and_direct_link(connected):
    app, _, _, _ = connected
    page(app, "Board report")
    click(app, "Generate report draft")
    draft_id = app.selectbox(key="board_report_selection").value
    app.text_area(key=f"board_summary_{draft_id}").set_value(
        "Portfolio exceptions require follow-up."
    )
    manager = get_manager()
    new = manager.analyst.assess("SYN007", date(2025, 9, 30), date(2025, 12, 31))
    manager.analyst.flag(
        new.assessment_run_id,
        category="Data quality",
        severity="Medium",
        explanation="Reconcile conflicting debt figures.",
        action="Obtain certificate.",
    )
    click(app, "Finalize report")
    assert any("Report sources changed" in m.value for m in app.warning)
    click(app, "Refresh draft sources")
    refreshed = app.selectbox(key="board_report_selection").value
    assert refreshed != draft_id
    assert any("Reconcile conflicting debt figures." in m.value for m in app.markdown)
    click(app, "Finalize report")
    final_id = app.selectbox(key="board_report_selection").value
    frozen = get_manager().repository.board_report(final_id)
    assert frozen["state"] == "final"
    assert len(frozen["payload"]["sources"]["items"]) == 3
    assert any("Finalized report" in m.value for m in app.success)
    manager.analyst.assess("SYN001", date(2025, 9, 30), date(2025, 12, 31))
    app.run()
    assert get_manager().repository.board_report(final_id) == frozen
    fresh = AppTest.from_file(str(APP), default_timeout=25)
    fresh.query_params["report_id"] = final_id
    fresh.run()
    assert not fresh.exception
    assert fresh.radio(key="preview_page").value == "Board report"
    assert fresh.selectbox(key="board_report_selection").value == final_id
    fresh.selectbox(key="board_report_selection").select("new").run()
    assert not fresh.exception
    assert any(b.label == "Generate report draft" for b in fresh.button)
