"""Connected Documents & data interactions with real SQLite, conversion and extraction graphs."""

import json
from pathlib import Path

import pytest
from document_workspace_helpers import document_inputs, local_markdown
from model_helpers import ScriptedModel, model_response
from streamlit.proto.WidgetStates_pb2 import WidgetState
from streamlit.testing.v1 import AppTest, element_tree
from workspace_ui_helpers import page

from credit_monitoring.domain import CovenantExtraction
from credit_monitoring.web import documents, portfolio

APP = Path(__file__).resolve().parents[3] / "src/credit_monitoring/web/preview.py"


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception


def select_documents(app, document_ids, *, table="inventory"):
    frame = next(d for d in app.dataframe if f"documents_{table}_" in d.proto.id)
    rows = [i for i, did in enumerate(frame.value["ID"]) if did in document_ids]
    states = app._tree.get_widget_states()
    for i in range(len(states.widgets) - 1, -1, -1):
        if states.widgets[i].id == frame.proto.id:
            del states.widgets[i]
    states.widgets.add(
        id=frame.proto.id,
        string_value=json.dumps({"selection": {"rows": rows, "columns": []}}),
    )
    app._run(states)
    assert not app.exception


@pytest.fixture
def connected(tmp_path, monkeypatch):
    # AppTest renders dataframes but does not serialize their selections on later
    # button/input events. Forward the selection state just as the browser does.
    original_widget_state = element_tree.get_widget_state

    def widget_state(node):
        if isinstance(node, element_tree.Dataframe) and node.proto.id:
            return WidgetState(
                id=node.proto.id,
                string_value=json.dumps(node.root.session_state[node.proto.id]),
            )
        return original_widget_state(node)

    monkeypatch.setattr(element_tree, "get_widget_state", widget_state)
    root = document_inputs(tmp_path)
    monkeypatch.setattr(portfolio, "DEFAULT_DATA_ROOT", root)
    monkeypatch.setattr(portfolio, "DEFAULT_WORKING_DIR", tmp_path / "working")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("SEC_USER_AGENT", "Offline test test@example.invalid")
    monkeypatch.setattr("requests.sessions.Session.request", lambda *a, **k: pytest.fail("Network"))
    downloaded = []

    def download(url, **kwargs):
        downloaded.append(url)
        return "<html><body><p>Maximum leverage covenant is 4.0x.</p></body></html>"

    monkeypatch.setattr("credit_monitoring.ingestion.loaders.sec.download_sec_filing", download)
    model = ScriptedModel(model_name="documents-ui-offline")
    model.respond.return_value = model_response(extraction=CovenantExtraction())
    factory = documents.create_document_service

    def create(**kwargs):
        return factory(**{**kwargs, "model": model})

    monkeypatch.setattr(documents, "create_document_service", create)
    app = AppTest.from_file(str(APP), default_timeout=25).run()
    page(app, "Documents & data")
    return app, model, downloaded


def test_opening_inventory_runs_nothing_and_registration_survives_reload(connected):
    app, model, downloaded = connected
    assert len(app.dataframe[0].value) == 2
    assert set(app.dataframe[0].value["Borrowers"]) == {"Unlinked"}
    assert model.respond.call_count == len(downloaded) == 0
    app.text_input(key="documents_issuer").set_value("Registered issuer")
    app.text_input(key="documents_title").set_value("New amendment")
    app.text_input(key="documents_url").set_value("https://example.invalid/amendment.html")
    app.multiselect(key="documents_register_links").set_value(["SYN001"])
    click(app, "Register document")
    workspace = documents.get_document_workspace()
    registered = next(r for r in workspace.repository.documents() if r["origin"] == "registered")
    assert registered["borrower_ids"] == ["SYN001"]
    assert "DOC_" in registered["document_id"]
    fresh = AppTest.from_file(str(APP), default_timeout=25).run()
    page(fresh, "Documents & data")
    fresh.radio(key="documents_view").set_value("All catalog sources").run()
    assert len(fresh.dataframe[0].value) == 3
    assert model.respond.call_count == len(downloaded) == 0
    page(fresh, "Settings")
    fresh.button(key="preview_reset").click().run()
    assert not fresh.exception
    assert len(documents.get_document_workspace().repository.documents()) == 3


def test_fetch_process_cache_force_and_history_are_real(connected, monkeypatch):
    app, model, downloaded = connected
    select_documents(app, ["DOC_ONE"])
    assert next(b for b in app.button if b.label == "Process selected").disabled
    click(app, "Fetch selected")
    assert len(downloaded) == 1

    assert app.dataframe[0].value.loc[0, "HTML"]
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    app.run()
    click(app, "Process selected")
    assert model.respond.call_count == 1
    assert app.dataframe[0].value.loc[0, "Extraction"] == "complete"
    assert documents.get_document_workspace().archive_path.is_file()
    click(app, "Process selected")
    assert model.respond.call_count == 1
    click(app, "Force reprocess selected")
    assert model.respond.call_count == 2
    operations = documents.get_document_workspace().repository.operations()
    assert all(o["state"] == "complete" for o in operations)
    app.run()
    page(app, "Portfolio")
    page(app, "Documents & data")
    assert model.respond.call_count == 2
    assert len(downloaded) == 1


def test_bulk_process_uses_isolated_workers_and_publishes_complete_archive(connected, monkeypatch):
    import json

    app, model, downloaded = connected
    original = documents.create_document_service

    def create(**kwargs):
        service = original(**kwargs)

        def fresh_model():
            child = ScriptedModel(model_name="documents-ui-offline")
            child.respond.side_effect = model.respond
            return child

        service.model_factory = fresh_model
        return service

    monkeypatch.setattr(documents, "create_document_service", create)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    app.run()
    select_documents(app, ["DOC_ONE", "DOC_TWO"])
    assert app.number_input(key="documents_workers").value == 4
    click(app, "Process selected")
    assert model.respond.call_count == 2 and len(downloaded) == 2
    assert set(app.dataframe[0].value["Extraction"]) == {"complete"}
    workspace = documents.get_document_workspace()
    archive = json.loads(workspace.archive_path.read_text())
    assert len(archive["document_extractions"]) == 2
    assert all(row["status"] == "complete" for row in archive["document_extractions"])
    assert workspace.repository.operations()[0]["state"] == "complete"


def test_explicit_link_reassessment_warning_and_financial_recreation(connected):
    app, _, _ = connected
    app.selectbox(key="documents_link_document").select("DOC_ONE").run()
    app.multiselect(key="documents_links_DOC_ONE").set_value(["SYN001"])
    click(app, "Save borrower links")
    page(app, "Borrower analysis")
    app.selectbox(key="analysis_borrower").select("SYN001").run()
    click(app, "Run assessment")
    rid = app.selectbox(key="analysis_version").value
    click(app, "Source documents")
    assert app.selectbox(key="documents_borrower").value == "SYN001"
    select_documents(app, ["DOC_ONE"])
    click(app, "Fetch selected")
    page(app, "Borrower analysis")
    assert any("Sources changed" in item.value for item in app.warning)
    assert app.selectbox(key="analysis_version").value == rid
    page(app, "Documents & data")
    page(app, "Settings")
    app.selectbox(key="documents_rebuild_target").select("Financial database").run()
    click(app, "Rebuild selected target")
    operation = documents.get_document_workspace().repository.operations()[0]
    assert operation["state"] == "complete"
    assert Path(operation["outcomes"][0]["backup"]).is_file()
    assert documents.get_document_workspace().portfolio.repository.get_assessment(rid)


def test_index_rebuild_search_and_failed_recreation_show_actual_outcomes(connected):
    app, _, _ = connected
    workspace = documents.get_document_workspace()
    local_markdown(workspace)
    page(app, "Settings")
    click(app, "Rebuild selected target")
    assert app.session_state.documents_rebuild_result["verification_hits"] > 0
    app.text_input(key="documents_query").set_value("leverage")
    click(app, "Search evidence")
    assert any("Maximum leverage covenant" in item.value for item in app.markdown)
    app.selectbox(key="documents_rebuild_target").select("Extraction database").run()
    click(app, "Rebuild selected target")
    assert any("Extraction archive is missing" in item.value for item in app.error)
    assert documents.get_document_workspace().repository.operations()[0]["state"] == "failed"


def test_table_selection_controls_actions_and_resets_with_scope(connected):
    app, model, downloaded = connected
    assert not any(w.label in {"Select documents", "Source document"} for w in app.multiselect)
    assert next(b for b in app.button if b.label == "Fetch selected").disabled
    select_documents(app, ["DOC_ONE", "DOC_TWO"])
    assert not next(b for b in app.button if b.label == "Fetch selected").disabled
    select_documents(app, [])
    assert next(b for b in app.button if b.label == "Fetch selected").disabled
    select_documents(app, ["DOC_TWO"])
    click(app, "Fetch selected")
    assert downloaded == ["https://example.invalid/two.html"]
    app.radio(key="documents_view").set_value("All catalog sources").run()
    assert next(b for b in app.button if b.label == "Fetch selected").disabled
    assert model.respond.call_count == 0


def test_evidence_index_browse_search_and_saved_extraction(connected, monkeypatch):
    app, model, downloaded = connected
    assert "Evidence index" in [tab.label for tab in app.tabs]
    select_documents(app, ["DOC_ONE"], table="index")
    assert any("No complete extraction" in item.value for item in app.info)
    assert model.respond.call_count == len(downloaded) == 0

    model.respond.return_value = model_response(
        extraction=CovenantExtraction(gaps=["Saved extraction gap for document two"])
    )
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    select_documents(app, ["DOC_TWO"])
    click(app, "Process selected")
    assert model.respond.call_count == len(downloaded) == 1
    app.text_input(key="documents_index_query").set_value("leverage")
    click(app, "Search index")
    select_documents(app, ["DOC_TWO"], table="index")
    assert any("Maximum leverage covenant" in item.value for item in app.text)
    assert any("Saved extraction gap for document two" in item.value for item in app.warning)
    assert any("DOC_TWO" in item.value for item in app.caption)
    assert len(app.json) >= 1
    app.run()
    assert any("Saved extraction gap for document two" in item.value for item in app.warning)
    assert model.respond.call_count == len(downloaded) == 1

    app.text_input(key="documents_index_query").set_value("nonexistentword")
    click(app, "Search index")
    assert any("No matching local passages" in item.value for item in app.info)
    app.text_input(key="documents_index_query").set_value("")
    click(app, "Search index")
    index = next(d for d in app.dataframe if "documents_index_" in d.proto.id)
    assert index.value["ID"].tolist() == ["DOC_ONE", "DOC_TWO"]
