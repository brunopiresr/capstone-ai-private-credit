"""Connected Documents & data interactions with real SQLite, conversion and extraction graphs."""

from pathlib import Path

import pytest
from document_workspace_helpers import document_inputs, local_markdown
from model_helpers import ScriptedModel, model_response
from streamlit.testing.v1 import AppTest

from credit_monitoring.domain import CovenantExtraction
from credit_monitoring.web import documents, portfolio

APP = Path(__file__).resolve().parents[3] / "src/credit_monitoring/web/preview.py"


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception


def page(app, name):
    app.radio(key="preview_page").set_value(name).run()
    assert not app.exception


@pytest.fixture
def connected(tmp_path, monkeypatch):
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
    fresh.button(key="preview_reset").click().run()
    assert not fresh.exception
    assert len(documents.get_document_workspace().repository.documents()) == 3


def test_fetch_process_cache_force_and_history_are_real(connected, monkeypatch):
    app, model, downloaded = connected
    borrower = app.selectbox(key="documents_borrower").value
    app.multiselect(key=f"documents_selected_{borrower}").set_value(["DOC_ONE"]).run()
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
    app.multiselect(key="documents_selected_SYN001").set_value(["DOC_ONE"]).run()
    click(app, "Fetch selected")
    page(app, "Borrower analysis")
    assert any("Sources changed" in item.value for item in app.warning)
    assert app.selectbox(key="analysis_version").value == rid
    page(app, "Documents & data")
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
    app.run()
    click(app, "Rebuild selected target")
    assert app.session_state.documents_rebuild_result["verification_hits"] > 0
    app.text_input(key="documents_query").set_value("leverage")
    click(app, "Search evidence")
    assert any("Maximum leverage covenant" in item.value for item in app.markdown)
    app.selectbox(key="documents_rebuild_target").select("Extraction database").run()
    click(app, "Rebuild selected target")
    assert any("Extraction archive is missing" in item.value for item in app.error)
    assert documents.get_document_workspace().repository.operations()[0]["state"] == "failed"
