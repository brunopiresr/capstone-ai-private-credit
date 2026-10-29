"""Exercise the disconnected UX, including the complete analyst/manager handoff."""

import json
from copy import deepcopy
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
    assert len(app.dataframe[0].value) == 12
    app.text_input(key="portfolio_search").set_value("northstar").run()
    assert app.dataframe[0].value["Borrower"].tolist() == ["Northstar Packaging"]
    app.text_input(key="portfolio_search").set_value("")
    app.selectbox(key="portfolio_status_filter").select("Not assessed").run()
    assert len(app.dataframe[0].value) == 12
    assert "Pioneer Security" in app.dataframe[0].value["Borrower"].tolist()
    app.text_input(key="portfolio_search").set_value("no-such-borrower").run()
    assert any("No borrowers match" in item.value for item in app.info)
    for name in ("Borrower analysis", "Documents & data", "Risk review", "Board report"):
        page(app, name)
        if name == "Risk review":
            assert any(item.value == "Credit analysis snapshot" for item in app.header)
            subheaders = [item.value for item in app.subheader]
            assert subheaders.index("Recommendation agent") < subheaders.index("Your review")
            assert {"Bullish agent", "Bearish agent", "Recommendation agent"} <= set(subheaders)
            assert any("4.85x is below the 5.00x limit" in item.value for item in app.markdown)
            assert any("0.15x of leverage headroom" in item.value for item in app.markdown)
            assert any("Increase monitoring" in item.value for item in app.markdown)


def test_queue_click_updates_top_selector_analysis_and_manager_form(preview):
    app = page(preview, "Risk review")
    picker = app.selectbox(key="preview_risk_borrower")
    assert picker.value == "SYN002"
    # The selector is rendered before the metric/queue columns.
    elements = list(app.main)
    assert elements.index(picker) < elements.index(app.metric[0])

    def select_event(rows, cells):
        # AppTest has no dataframe click helper; dispatch the native selection event.
        table = app.dataframe[0]
        assert table.proto.SINGLE_CELL in table.proto.selection_mode
        assert table.proto.SINGLE_ROW in table.proto.selection_mode
        states = app._tree.get_widget_states()
        states.widgets.add(
            id=table.proto.id,
            string_value=json.dumps({"selection": {"rows": rows, "columns": [], "cells": cells}}),
        )
        app._run(states)
        assert not app.exception

    # A regular name-cell click supplies cells, not a row-checkbox selection.
    select_event([], [[1, "Borrower"]])
    assert app.selectbox(key="preview_risk_borrower").value == "SYN003"
    assert app.session_state.preview_selected_borrower == "SYN003"
    assert any(item.value == "Elmwood Services" for item in app.subheader)
    assert any("5.20x exceeds the 4.50x" in item.value for item in app.markdown)
    assert app.text_area(key="preview_manager_note_SYN003")

    # Alternating the selection types must use the latest click, not the old one.
    select_event([3], [[1, "Borrower"]])
    assert app.selectbox(key="preview_risk_borrower").value == "SYN008"
    select_event([3], [[0, "Reason"]])
    assert app.selectbox(key="preview_risk_borrower").value == "SYN002"

    # Repeating the same cell click after navigation must not look like stale input.
    page(app, "Borrower analysis")
    app.selectbox(key="preview_analysis_borrower").select("SYN001").run()
    page(app, "Risk review")
    select_event([], [[0, "Reason"]])
    assert app.selectbox(key="preview_risk_borrower").value == "SYN002"

    # Manual selection must not be reverted by an old table highlight.
    previous_key = app.dataframe[0].key
    app.selectbox(key="preview_risk_borrower").select("SYN007").run()
    assert app.dataframe[0].key != previous_key
    assert app.selectbox(key="preview_risk_borrower").value == "SYN007"
    app.run()
    assert app.selectbox(key="preview_risk_borrower").value == "SYN007"

    # Filtering changes row positions: resolve clicks against the visible rows.
    app.text_area(key="preview_manager_recommendation_SYN007").set_value("Reconcile the debt.")
    click(app, "Mark reviewed")
    app.radio(key="preview_queue_filter").set_value("Reviewed").run()
    assert app.dataframe[0].value["Borrower"].tolist() == ["Riverside Foods"]
    app.selectbox(key="preview_risk_borrower").select("SYN002").run()
    select_event([], [[0, "Reason"]])
    assert app.selectbox(key="preview_risk_borrower").value == "SYN007"
    assert any("Defer the compliance conclusion" in item.value for item in app.markdown)


def test_analyst_manager_request_and_board_report_workflow(preview):
    app = page(preview, "Borrower analysis")
    app.selectbox(key="preview_analysis_borrower").select("SYN001").run()
    click(app, "Recalculate")
    borrower = app.session_state.preview_data["borrowers"]["SYN001"]
    assert borrower["version"] == 2
    assert not borrower["validated"]
    click(app, "Send to risk manager")
    assert any("Validate this assessment" in item.value for item in app.warning)
    for checkbox in app.checkbox:
        checkbox.check()
    click(app, "Mark validated")
    assert app.session_state.preview_data["borrowers"]["SYN001"]["validated"]
    control(app.text_area, "Short explanation").set_value("Monitor customer concentration.")
    control(app.text_input, "Proposed action").set_value("Obtain customer retention figures.")
    click(app, "Add flag")
    assert app.session_state.preview_data["flags"][-1]["status"] == "Analyst draft"
    app.text_area(key="preview_analyst_report_SYN001_2").set_value(
        "Calculations reviewed. Customer concentration merits additional monitoring."
    )
    click(app, "Send to risk manager")
    assert app.session_state.preview_data["flags"][-1]["status"] == "Pending review"
    page(app, "Risk review")
    assert app.radio(key="preview_page").value == "Risk review"
    control(app.text_input, "Analysis question").set_value("Assess the largest customer loss.")
    control(app.text_area, "Additional context / data").set_value(
        "Largest customer is 20% of sales."
    )
    click(app, "Send analysis request")
    assert app.session_state.preview_data["requests"][0]["status"] == "Open"
    page(app, "Borrower analysis")
    app.text_area(key="preview_context_SYN001").set_value(
        "Assess loss of a customer representing 20% of sales. This is an assumption."
    )
    click(app, "Run review with this context")
    app.text_area(key="preview_response_REQ-001").set_value(
        "Reviewed downside assumptions and recorded the additional context."
    )
    click(app, "Submit response")
    assert app.session_state.preview_data["requests"][0]["status"] == "Response ready"
    page(app, "Risk review")
    app.text_area(key="preview_manager_note_SYN001").set_value("Concentration risk reviewed.")
    app.text_area(key="preview_manager_recommendation_SYN001").set_value(
        "Maintain exposure with monthly customer reporting."
    )
    click(app, "Mark reviewed")
    assert app.session_state.preview_data["requests"][0]["status"] == "Accepted"
    assert app.session_state.preview_data["flags"][-1]["status"] == "Reviewed"
    page(app, "Board report")
    click(app, "Finalize sample report")
    report = app.session_state.preview_data["reports"][0]
    assert app.selectbox(key="preview_report_selection").value == report["id"]
    entries = {item["borrower_id"]: item for item in report["items"]}
    assert {"SYN001", "SYN002", "SYN003", "SYN007", "SYN008", "SYN009"} == set(entries)
    assert (
        entries["SYN001"]["recommendation"] == "Maintain exposure with monthly customer reporting."
    )
    assert entries["SYN009"]["review_state"] == "Untriaged breach"
    frozen = deepcopy(report)
    page(app, "Borrower analysis")
    click(app, "Recalculate")
    assert app.session_state.preview_data["reports"][0] == frozen


def test_document_registration_processing_and_rebuild_are_only_simulations(preview):
    app = page(preview, "Documents & data")
    control(app.text_input, "Document title").set_value("New management pack")
    control(app.text_input, "Source URL").set_value("https://example.com/new-pack.html")
    click(app, "Register document")
    registered = app.session_state.preview_data["documents"][-1]
    assert registered["borrower_id"] == "SYN002"
    assert registered["status"] == "Not fetched"
    app.multiselect(key="preview_document_selection_SYN002").set_value([registered["id"]]).run()
    click(app, "Process selected")
    assert "Skipped" in app.session_state.preview_data["operations"][0]["outcomes"][0]["Outcome"]
    click(app, "Fetch selected")
    assert app.session_state.preview_data["documents"][-1]["status"] == "Ready to process"
    click(app, "Process selected")
    assert app.session_state.preview_data["documents"][-1]["status"] == "Processed"
    assert app.session_state.preview_data["borrowers"]["SYN002"]["needs_review"]
    click(app, "Simulate rebuild")
    operation = app.session_state.preview_data["operations"][0]
    assert operation["Status"] == "Simulated"
    assert operation["Operation"] == "Rebuild retrieval index"


def test_chat_expansion_scope_and_reset(preview):
    app = page(preview, "Borrower analysis")
    click(app, "Explain the key concern")
    assert len(app.session_state.preview_data["chats"]["SYN002:1"]) == 2
    click(app, "Expand")
    assert any("expanded" in item.key for item in app.chat_input)
    app.chat_input(key="preview_chat_input_expanded_SYN002:1").set_value("What changed?").run()
    assert not app.exception
    assert len(app.session_state.preview_data["chats"]["SYN002:1"]) == 4
    # A page rerun closes the dialog; changing borrower starts an independent conversation.
    page(app, "Portfolio")
    page(app, "Borrower analysis")
    app.selectbox(key="preview_analysis_borrower").select("SYN003").run()
    assert app.session_state.preview_data["chats"]["SYN003:1"] == []
    app.button(key="preview_reset").click().run()
    assert not app.exception
    assert app.radio(key="preview_page").value == "Portfolio"
    assert app.session_state.preview_data["chats"] == {}


def test_missing_data_requires_exceptions_and_unassessed_results_cannot_be_validated(preview):
    app = page(preview, "Borrower analysis")
    app.selectbox(key="preview_analysis_borrower").select("SYN007").run()
    click(app, "Recalculate")
    assert app.metric[0].value == "—"
    for checkbox in app.checkbox:
        checkbox.check()
    app.text_area(key="preview_validation_note_SYN007_2").set_value("")
    click(app, "Mark validated")
    assert not app.session_state.preview_data["borrowers"]["SYN007"]["validated"]
    assert any("Document the data exception" in item.value for item in app.warning)
    app.text_area(key="preview_validation_note_SYN007_2").set_value(
        "Debt is unresolved; request a reconciled certificate."
    )
    click(app, "Mark validated")
    assert app.session_state.preview_data["borrowers"]["SYN007"]["validated"]
    app.selectbox(key="preview_analysis_borrower").select("SYN012").run()
    click(app, "Mark validated")
    assert not app.session_state.preview_data["borrowers"]["SYN012"]["validated"]
    assert any("no sample calculation results" in item.value for item in app.warning)
