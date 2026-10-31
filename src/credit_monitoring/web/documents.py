"""Connected source inventory, processing controls, and local database recreation."""

import os
from datetime import date

import pandas as pd
import streamlit as st

from credit_monitoring.agents.models import DEFAULT_MODEL
from credit_monitoring.application.bootstrap import create_document_service
from credit_monitoring.application.data_maintenance import recreate_database
from credit_monitoring.application.document_workspace import PROCESS_ID, DocumentWorkspace
from credit_monitoring.persistence.document_workspace_repository import DocumentWorkspaceRepository
from credit_monitoring.retrieval.lexical.local import LocalEvidenceSearch
from credit_monitoring.web.borrower_analysis import get_workflow
from credit_monitoring.web.user_guide import render_help


@st.cache_resource(show_spinner=False)
def get_evidence_search(working_dir: str) -> LocalEvidenceSearch:
    return LocalEvidenceSearch()


def get_document_workspace() -> DocumentWorkspace:
    workflow = get_workflow()
    working = workflow.portfolio.repository.database_path.parent
    cache = workflow.data_root / "cache" / "sec"
    processor = create_document_service(
        source_file=working / "documents" / "catalog.csv",
        html_dir=cache / "html",
        markdown_dir=cache / "markdown",
        database_path=working / "documents" / "extractions.sqlite3",
        model=os.getenv("LLM_MODEL") or DEFAULT_MODEL,
        user_agent=os.getenv("SEC_USER_AGENT", ""),
    )
    processor.evidence_search = get_evidence_search(str(working))
    return DocumentWorkspace(
        portfolio=workflow.portfolio,
        processor=processor,
        workflow=workflow.repository,
        repository=DocumentWorkspaceRepository(working / "workflow.sqlite3", process_id=PROCESS_ID),
        data_root=workflow.data_root,
        working_dir=working,
    )


def execute_documents(workspace: DocumentWorkspace, kind: str, ids: list[str], *, force=False):
    try:
        with st.status(
            f"{'Reprocessing' if force else kind + 'ing'} documents…", expanded=True
        ) as status:
            total_progress, section_progress, current = (
                st.progress(0.0),
                st.progress(0.0),
                st.empty(),
            )

            def progress(event):
                current.write(
                    f"{event.completed_documents}/{event.total_documents} completed · "
                    f"{event.document_id} · {event.stage}"
                )
                fraction = (
                    event.completed_sections / event.total_sections if event.total_sections else 0
                )
                total_progress.progress(event.total_fraction)
                section_progress.progress(fraction)

            outcomes = workspace.run_documents(
                kind,
                ids,
                force=force,
                progress=progress,
                max_workers=int(st.session_state.get("documents_workers", 4)),
            )
            failed = sum(item["status"] == "failed" for item in outcomes)
            total_progress.progress(1.0)
            status.update(
                label=f"{len(outcomes) - failed} completed · {failed} failed",
                state="error" if failed else "complete",
            )
        st.session_state.documents_outcomes = outcomes
    except Exception as error:
        st.error(str(error))
        return
    st.rerun()


def render_inventory(workspace: DocumentWorkspace, borrower_id: str) -> None:
    view = st.radio(
        "Show sources",
        ["Borrower and unlinked sources", "Borrower only", "All catalog sources"],
        horizontal=True,
        key="documents_view",
    )
    rows = [
        r
        for r in workspace.inventory()
        if view == "All catalog sources"
        or borrower_id in r["borrower_ids"]
        or (view == "Borrower and unlinked sources" and not r["borrower_ids"])
    ]
    metrics = st.columns(3)
    metrics[0].metric("Documents in view", len(rows))
    metrics[1].metric("Processed", sum(r["status"] == "complete" for r in rows))
    metrics[2].metric("Unlinked sources", sum(not r["borrower_ids"] for r in rows))
    st.caption(
        "Sources are linked only by an explicit selection. Names and tickers never create links."
    )
    if not rows:
        st.info("No sources in this view. Register a source or link an existing catalog document.")
        return
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Document": r.get("title") or r["document_id"],
                    "ID": r["document_id"],
                    "Issuer": r["company"],
                    "Borrowers": ", ".join(r["borrower_ids"]) or "Unlinked",
                    "Type": r["document_type"],
                    "Date": r.get("document_date") or r.get("period_end") or "Unknown",
                    "Source URL": r["source_url"],
                    "HTML": r["html_available"],
                    "Markdown": r["markdown_available"],
                    "Extraction": r["status"],
                    "Sections": f"{r['completed_sections']}/{r['total_sections']}",
                    "Issue": r["format_issue"] or r["error"] or "",
                }
                for r in rows
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    choices = {r["document_id"]: r.get("title") or r["document_id"] for r in rows}
    ids = st.multiselect(
        "Select documents",
        list(choices),
        format_func=choices.get,
        key=f"documents_selected_{borrower_id}",
    )
    user_agent = st.text_input(
        "Download identity (name / organization and email)",
        value=workspace.processor.user_agent,
        key="documents_user_agent",
    )
    workspace.processor.user_agent = user_agent
    st.number_input(
        "Documents processed at once",
        min_value=1,
        max_value=16,
        value=4,
        key="documents_workers",
        disabled=workspace.busy,
    )
    credentials = bool(os.getenv("OPENAI_API_KEY", "").strip())
    if not credentials:
        st.caption(
            "Set OPENAI_API_KEY to run extraction. Fetch, inspection and rebuilds work without it."
        )
    fetch, process, force = st.columns(3)
    if fetch.button("Fetch selected", disabled=not ids or workspace.busy, width="stretch"):
        execute_documents(workspace, "Fetch", ids)
    if process.button(
        "Process selected",
        disabled=not ids or workspace.busy or not credentials,
        type="primary",
        width="stretch",
    ):
        execute_documents(workspace, "Process", ids)
    if force.button(
        "Force reprocess selected",
        disabled=not ids or workspace.busy or not credentials,
        width="stretch",
    ):
        execute_documents(workspace, "Process", ids, force=True)
    missing_fetch = [
        r["document_id"] for r in rows if not r["html_available"] and not r["format_issue"]
    ]
    missing_process = [
        r["document_id"] for r in rows if r["status"] != "complete" and not r["format_issue"]
    ]
    one, two = st.columns(2)
    if one.button(
        f"Fetch missing in view ({len(missing_fetch)})",
        key="documents_fetch_missing",
        disabled=not missing_fetch or workspace.busy,
    ):
        execute_documents(workspace, "Fetch", missing_fetch)
    if two.button(
        f"Process missing / stale / failed in view ({len(missing_process)})",
        key="documents_process_missing",
        disabled=not missing_process or workspace.busy or not credentials,
    ):
        execute_documents(workspace, "Process", missing_process)
    st.caption(
        "Process may fetch missing HTML. Document and section caches are reused on retry. "
        "Force reprocess reruns every section. Keep this page open until the operation finishes."
    )
    if "documents_outcomes" in st.session_state:
        st.dataframe(
            pd.DataFrame(st.session_state.documents_outcomes), hide_index=True, width="stretch"
        )
    with st.expander("Inspect extracted facts and source text"):
        selected = st.selectbox(
            "Source document",
            list(choices),
            format_func=choices.get,
            key=f"documents_inspect_{borrower_id}",
        )
        record = next(r for r in rows if r["document_id"] == selected)
        st.link_button("Open source URL", record["source_url"])
        extraction = workspace.processor.get_document_extraction(selected)
        st.caption(
            f"State: {extraction.status} · Cache reuse: {extraction.cache_hit} · "
            f"Sections: {extraction.completed_sections}/{extraction.total_sections}"
        )
        if extraction.error:
            st.info(extraction.error)
        if record["format_issue"]:
            st.warning(record["format_issue"])
        if extraction.result:
            st.json(extraction.result.model_dump(mode="json"), expanded=False)
        if record["markdown_available"]:
            text = workspace.processor.read_source_text(selected)
            st.text_area(
                "Local source excerpt",
                text[:12000],
                height=180,
                disabled=True,
                key=f"documents_excerpt_{selected}",
            )
            st.caption(
                f"Showing up to 12,000 of {len(text):,} characters. "
                "Extraction uses the full source."
            )


def render_catalog_forms(workspace: DocumentWorkspace, borrower_id: str) -> None:
    names = workspace.borrowers
    st.subheader("Register a source")
    with st.form("documents_register"):
        issuer = st.text_input("Issuer / company", key="documents_issuer")
        title = st.text_input("Document title", key="documents_title")
        url = st.text_input("Source URL", key="documents_url")
        kind = st.selectbox(
            "Document type",
            ["Credit agreement", "Amendment", "10-Q", "10-K", "Financial statements", "Other"],
        )
        issued = st.date_input("Document date", date.today(), key="documents_date")
        ticker = st.text_input("Ticker (optional)")
        links = st.multiselect(
            "Explicit borrower links",
            list(names),
            default=[borrower_id],
            format_func=names.get,
            key="documents_register_links",
        )
        st.caption(
            "The current pipeline supports HTML. Other formats stay visible as unsupported sources."
        )
        if st.form_submit_button("Register document", disabled=workspace.busy):
            try:
                workspace.register(
                    company=issuer,
                    title=title,
                    url=url,
                    document_type=kind,
                    document_date=issued,
                    borrower_ids=links,
                    ticker=ticker,
                )
            except Exception as error:
                st.warning(str(error))
            else:
                st.toast("Document registered and links saved.")
                st.rerun()
    st.subheader("Link an existing catalog source")
    catalog = {r["document_id"]: r for r in workspace.repository.documents()}
    if not catalog:
        st.info("Register a document before editing links.")
        return
    selected = st.selectbox(
        "Document to link",
        list(catalog),
        key="documents_link_document",
        format_func=lambda did: f"{catalog[did]['company']} · {did}",
    )
    with st.form(f"documents_link_{selected}"):
        links = st.multiselect(
            "Linked borrowers",
            list(names),
            default=catalog[selected]["borrower_ids"],
            format_func=names.get,
            key=f"documents_links_{selected}",
        )
        if st.form_submit_button("Save borrower links", disabled=workspace.busy):
            try:
                workspace.link(selected, links)
            except Exception as error:
                st.warning(str(error))
            else:
                st.toast("Borrower links saved.")
                st.rerun()


def render_maintenance(workspace: DocumentWorkspace) -> None:
    st.subheader("Rebuild working data")
    target = st.selectbox(
        "Rebuild target",
        ["Retrieval index", "Financial database", "Extraction database", "Analytics database"],
        key="documents_rebuild_target",
    )
    sources = {
        "Retrieval index": "All locally available Markdown; includes unlinked sources.",
        "Financial database": str(
            workspace.data_root / "app/synthetic/synthetic_quarterly_financials.csv"
        ),
        "Extraction database": str(workspace.archive_path),
        "Analytics database": "Complete retained assessment snapshots in portfolio.sqlite3.",
    }
    st.write(f"Source: {sources[target]}")
    if target == "Retrieval index":
        st.caption(
            "Rebuilds the in-memory index and checks that a local source passage can be retrieved."
        )
    else:
        path = (
            workspace.processor.repository.database_path
            if target == "Extraction database"
            else workspace.working_dir
            / ("financials.sqlite3" if target == "Financial database" else "analytics.sqlite3")
        )
        st.code(str(path), language=None)
        st.caption(
            "Recreates this entire working database for all borrowers. A local backup is saved "
            "before replacement. Assessments, flags, submissions and reports are preserved."
        )
        if target == "Financial database":
            st.info(
                "Financial recreation restores the source CSV. Saved assessments will need review."
            )
    if st.button(
        "Rebuild selected target", type="primary", disabled=workspace.busy, key="documents_rebuild"
    ):
        try:
            with st.status(f"Rebuilding {target.lower()}…", expanded=True) as status:
                current = st.empty()
                indicator = st.progress(0.0)
                completed_stages = 0

                def on_stage(stage):
                    nonlocal completed_stages
                    completed_stages += 1
                    current.write(stage)
                    indicator.progress(min(0.95, completed_stages / 6))

                if target == "Retrieval index":
                    summary = workspace.rebuild_index(progress=on_stage)
                else:
                    summary = recreate_database(workspace, target, progress=on_stage)
                indicator.progress(1.0)
                status.update(label="Rebuild complete", state="complete")
            st.session_state.documents_rebuild_result = summary
        except Exception as error:
            st.error(str(error))
        else:
            st.rerun()
    if "documents_rebuild_result" in st.session_state:
        st.json(st.session_state.documents_rebuild_result)
    with st.form("documents_search"):
        query = st.text_input("Search local source text", key="documents_query")
        search = st.form_submit_button("Search evidence", disabled=workspace.busy)
    if search:
        if not query.strip():
            st.warning("Enter a search term.")
        else:
            for hit in workspace.processor.search_evidence(query):
                st.caption(hit["citation"])
                st.write(hit["content"])


def render_documents_page() -> None:
    st.title("Documents & data")
    render_help(
        "Documents, manager and board workflows", "How document operations affect saved work"
    )
    st.caption("Register evidence, inspect extraction and maintain the working data.")
    st.caption(
        "Extracted documents supply evidence. Financial inputs and covenant definitions "
        "change through explicit analyst updates."
    )
    try:
        workspace = get_document_workspace()
    except Exception as error:
        st.error(f"Could not open the document workspace ({type(error).__name__}): {error}")
        return
    names = workspace.borrowers
    if not names:
        st.info("No borrowers are registered in the input catalog.")
        return
    pending = st.session_state.pop("_documents_open_borrower", None)
    if pending in names:
        st.session_state.documents_borrower = pending
    if st.session_state.get("documents_borrower") not in names:
        selected = st.session_state.get("documents_saved_borrower") or st.session_state.get(
            "portfolio_borrower"
        )
        st.session_state.documents_borrower = selected if selected in names else next(iter(names))
    borrower = st.selectbox(
        "Borrower", list(names), format_func=names.get, key="documents_borrower"
    )
    st.session_state.documents_saved_borrower = borrower
    if workspace.busy:
        st.info("Another document or maintenance operation is running.")
    inventory, catalog, rebuild, history = st.tabs(
        ["Inventory & processing", "Register & link", "Rebuild working data", "Operation history"]
    )
    with inventory:
        render_inventory(workspace, borrower)
    with catalog:
        render_catalog_forms(workspace, borrower)
    with rebuild:
        render_maintenance(workspace)
    with history:
        operations = workspace.repository.operations()
        if not operations:
            st.info("No document or maintenance operations have run yet.")
        for operation in operations:
            with st.expander(
                f"{operation['kind']} · {operation['state']} · {operation['started_at']}"
            ):
                st.write("Scope: " + ", ".join(operation["scope"]))
                if operation["state"] == "interrupted":
                    st.warning(
                        "This operation did not finish before restart. "
                        "Retry explicitly to reuse saved sections."
                    )
                st.json(operation["outcomes"])
