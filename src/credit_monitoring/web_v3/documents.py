"""Borrower-first document checklist, processing and catalog discovery."""

import streamlit as st

from credit_monitoring.web_v3.analyst import credentials
from credit_monitoring.web_v3.checklist import DOCUMENT_TYPES, checklist_states, document_state
from credit_monitoring.web_v3.state import attempt, commit, go


def render_checklist(services, bid, period, inventory) -> None:
    saved = services.checklists.load(bid, period)
    scope = f"{bid}_{period}"
    if saved is None:
        st.warning(
            "Requirements not configured. Define the document checklist for this reporting period."
        )
    else:
        states = checklist_states(saved, bid, inventory)
        if states:
            for item in states:
                st.write(f"**{item['document_type']}** · {item['state']}")
        else:
            st.info("Checklist configured: no required documents for this period.")
    st.caption(
        "Advisory checklist: missing documents warn only. Processing does "
        "not replace human validation."
    )
    types = st.multiselect(
        "Required document types",
        DOCUMENT_TYPES,
        default=[i["document_type"] for i in saved or []],
        key=f"v3_required_{scope}",
    )
    previous = {i["document_type"]: i.get("document_id") for i in saved or []}
    items = []
    with st.form(f"v3form_checklist_{scope}"):
        for kind in types:
            records = {
                r["document_id"]: r
                for r in inventory
                if bid in r["borrower_ids"] and r["document_type"] == kind
            }
            options = [None, *records]
            selected = previous.get(kind)
            key = f"v3_attachment_{scope}_{kind}"
            if st.session_state.get(key) not in options:
                st.session_state[key] = None
            did = st.selectbox(
                f"Attach {kind}",
                options,
                index=options.index(selected) if selected in options else 0,
                format_func=lambda d, records=records: (
                    f"{records[d].get('title') or d} · {d}"
                    if d
                    else "Missing — choose a linked source"
                ),
                key=key,
            )
            items.append({"document_type": kind, "document_id": did})
        st.caption(
            "Older credit agreements may be reused by explicitly selecting them. "
            "Names and dates never create links."
        )
        if st.form_submit_button("Save document checklist"):
            commit(
                lambda: services.checklists.save(bid, period, items, inventory), "Checklist saved."
            )


def run_documents(services, ids, *, kind="Process", force=False):
    with st.status(
        "Processing documents…" if kind == "Process" else "Fetching HTML…", expanded=True
    ) as status:
        progress, current = st.progress(0.0), st.empty()

        def report(event):
            progress.progress(event.total_fraction)
            current.write(
                f"{event.completed_documents}/{event.total_documents} · {event.document_id} "
                f"· {event.stage} · Sections {event.completed_sections}/{event.total_sections}"
            )

        outcomes, success = attempt(
            lambda: services.documents.run_documents(
                kind,
                ids,
                force=force,
                max_workers=int(st.session_state.get("v3_workers", 4)),
                progress=report,
            ),
            "Document operation finished. Inspect the outcomes below.",
        )
        if success:
            st.session_state.v3_document_outcomes = outcomes
            failed = sum(o["status"] == "failed" for o in outcomes)
            status.update(
                label=f"{len(outcomes) - failed} completed · {failed} failed",
                state="error" if failed else "complete",
            )
    if success:
        st.rerun()


def render_documents(services, period, cutoff) -> None:
    if st.button("← Back to workspace", key="v3btn_documents_back"):
        go(st.session_state.get("v3_document_return", "Analyst queue"))
    st.title("Documents")
    st.caption("Add or link → Process → Inspect evidence → Reassess borrower")
    names = services.documents.borrowers
    if not names:
        st.info("No borrowers are registered.")
        return
    if st.session_state.get("v3_borrower") not in names:
        st.session_state.v3_borrower = next(iter(names))
    bid = st.selectbox("Borrower", list(names), format_func=names.get, key="v3_borrower")
    target = period or services.analyst.portfolio.target_period(bid, None, cutoff) or cutoff
    st.caption(f"Checklist period {target} · Information cutoff {cutoff}")
    inventory = services.documents.inventory()
    linked = [r for r in inventory if bid in r["borrower_ids"]]
    tab = st.radio(
        "Document workspace",
        ["Borrower evidence", "Add or link sources", "Operation history"],
        horizontal=True,
        key="v3_documents_tab",
    )
    if tab == "Borrower evidence":
        with st.expander("Required document checklist", expanded=True):
            render_checklist(services, bid, target, inventory)
        if not linked:
            st.info(
                "No sources linked to this borrower. Open Add or link sources to attach evidence."
            )
            if st.button("Add or link source", key="v3btn_add_source"):
                st.session_state["_v3_route"] = {"v3_documents_tab": "Add or link sources"}
                st.rerun()
        else:
            st.subheader("Linked evidence")
            rows = [
                {
                    "Document": r.get("title") or r["document_id"],
                    "ID": r["document_id"],
                    "Type": r["document_type"],
                    "State": document_state(r),
                    "Sections": f"{r['completed_sections']}/{r['total_sections']}",
                    "Issue": r.get("format_issue") or r.get("error") or "",
                }
                for r in linked
            ]
            st.dataframe(rows, hide_index=True, width="stretch")
            lookup = {r["document_id"]: r for r in linked}
            eligible = [r["document_id"] for r in linked if not r.get("format_issue")]
            key = f"v3_process_selection_{bid}"
            if key in st.session_state:
                st.session_state[key] = [d for d in st.session_state[key] if d in eligible]
            ids = st.multiselect(
                "Documents to process",
                eligible,
                key=key,
                format_func=lambda d: lookup[d].get("title") or d,
            )
            st.caption(
                "Processing fetches missing HTML and reuses completed sections. "
                "Unsupported formats need replacement HTML sources."
            )
            if not credentials():
                st.info(
                    "Processing needs configured model access. You can still link and "
                    "inspect saved documents."
                )
            if not services.documents.processor.user_agent:
                st.caption(
                    "Downloading missing SEC HTML also needs a download identity in Settings."
                )
            process, retry = st.columns(2)
            if process.button(
                "Process selected documents",
                key="v3btn_process",
                type="primary",
                disabled=not ids or not credentials() or services.documents.busy,
            ):
                run_documents(services, ids)
            failed = [
                r["document_id"]
                for r in linked
                if not r.get("format_issue")
                and (
                    r["status"] in {"failed", "partial", "interrupted"}
                    or (r.get("error") and r["status"] != "complete")
                )
            ]
            if retry.button(
                f"Retry failed documents ({len(failed)})",
                key="v3btn_retry",
                disabled=not failed or not credentials() or services.documents.busy,
            ):
                run_documents(services, failed)
            with st.expander("Advanced fetch and reprocess"):
                if st.button(
                    "Fetch selected HTML",
                    key="v3btn_fetch",
                    disabled=not ids or services.documents.busy,
                ):
                    run_documents(services, ids, kind="Fetch")
                if st.button(
                    "Force reprocess selected",
                    key="v3btn_force",
                    disabled=not ids or not credentials() or services.documents.busy,
                ):
                    run_documents(services, ids, force=True)
            st.subheader("Inspect extracted evidence")
            inspect_key = f"v3_inspect_{bid}"
            if st.session_state.get(inspect_key) not in lookup:
                st.session_state[inspect_key] = next(iter(lookup))
            did = st.selectbox(
                "Source to inspect",
                list(lookup),
                key=inspect_key,
                format_func=lambda d: lookup[d].get("title") or d,
            )
            record = lookup[did]
            st.link_button("Open original source", record["source_url"])
            extraction = services.documents.processor.get_document_extraction(did)
            if extraction.error:
                st.warning(extraction.error)
            if extraction.result:
                facts = extraction.result.extraction
                for gap in [*facts.gaps, *facts.conflicts, *facts.extraction_warnings]:
                    st.warning(gap)
                for covenant in facts.covenants:
                    with st.container(border=True):
                        st.write(f"**{covenant.covenant_name}**")
                        st.write(covenant.metric or "Metric not stated")
                        st.caption(covenant.evidence.citation)
                        st.write(covenant.evidence.evidence_quote)
                if facts.reported_financial_values:
                    st.dataframe(
                        [
                            {
                                "Metric": value.metric_name,
                                "Reported value": value.reported_value,
                                "Period": str(value.period_end or "Not stated"),
                                "Source": value.evidence.citation,
                            }
                            for value in facts.reported_financial_values
                        ],
                        hide_index=True,
                        width="stretch",
                    )
                if not facts.covenants and not facts.reported_financial_values:
                    st.info(
                        "No covenant terms or reported financial values were extracted. "
                        "Inspect the source and recorded gaps."
                    )
                with st.expander("Complete extracted facts and source references"):
                    st.json(extraction.result.model_dump(mode="json"), expanded=False)
            if record["markdown_available"]:
                with st.expander("Source text", expanded=True):
                    st.text(services.documents.processor.read_source_text(did)[:12000])
                    st.caption("Showing up to 12,000 characters. Extraction reads the full source.")
        if outcomes := st.session_state.get("v3_document_outcomes"):
            st.subheader("Last operation outcomes")
            st.dataframe(outcomes, hide_index=True, width="stretch")
        st.info(
            "Extraction supplies evidence. Update financial inputs and calculation "
            "rules explicitly; reassess and validate after changes."
        )
        if st.button("Review borrower evidence / reassess", key="v3btn_docs_reassess"):
            go("Borrower", bid, "Evidence")
        st.caption(
            "Keep this page open until processing finishes. Interrupted work "
            "can be retried from saved sections."
        )
    elif tab == "Add or link sources":
        render_catalog(services, bid, inventory)
    else:
        for operation in services.documents.repository.operations():
            with st.expander(
                f"{operation['kind']} · {operation['state']} · {operation['started_at']}"
            ):
                st.write("Scope: " + ", ".join(operation["scope"]))
                st.json(operation["outcomes"])


def render_catalog(services, bid, inventory) -> None:
    from datetime import date

    st.subheader("Register an HTML source")
    st.caption(
        "Sources are linked to the selected borrower explicitly. PDF and "
        "local file uploads are not supported in this release."
    )
    with st.form(f"v3form_register_{bid}"):
        company = st.text_input("Issuer / company", key=f"v3_source_company_{bid}")
        title = st.text_input("Document title", key=f"v3_source_title_{bid}")
        url = st.text_input("HTML source URL", key=f"v3_source_url_{bid}")
        kind = st.selectbox("Document type", DOCUMENT_TYPES, key=f"v3_source_type_{bid}")
        issued = st.date_input("Document date", date.today(), key=f"v3_source_date_{bid}")
        if st.form_submit_button("Register and link to borrower", disabled=services.documents.busy):
            if services.documents.format_issue({"source_url": url}):
                st.warning(
                    "Use an HTML URL. This release does not process PDFs or other file formats."
                )
            else:
                commit(
                    lambda: services.documents.register(
                        company=company,
                        title=title,
                        url=url,
                        document_type=kind,
                        document_date=issued,
                        borrower_ids=[bid],
                    ),
                    "Source registered and linked.",
                )
    st.subheader("Discover existing catalog sources")
    search = st.text_input("Search catalog", key="v3_catalog_search").strip().casefold()
    records = {
        r["document_id"]: r
        for r in inventory
        if not search
        or search in f"{r.get('title', '')} {r['company']} {r['document_id']}".casefold()
    }
    if not records:
        st.info("No catalog sources match.")
        return
    key = "v3_catalog_document"
    if st.session_state.get(key) not in records:
        st.session_state[key] = next(iter(records))
    did = st.selectbox(
        "Catalog source",
        list(records),
        key=key,
        format_func=lambda d: f"{records[d]['company']} · {records[d].get('title') or d}",
    )
    record = records[did]
    st.write(f"{record['document_type']} · {document_state(record)}")
    st.link_button("Inspect source URL", record["source_url"])
    if st.button(
        "Link source to this borrower",
        key="v3btn_link",
        disabled=bid in record["borrower_ids"] or services.documents.busy,
    ):
        commit(
            lambda: services.documents.link(did, [*record["borrower_ids"], bid]),
            "Source explicitly linked.",
        )
    if bid in record["borrower_ids"] and st.button(
        "Remove this borrower link", key="v3btn_unlink", disabled=services.documents.busy
    ):
        commit(
            lambda: services.documents.link(did, [b for b in record["borrower_ids"] if b != bid]),
            "Link removed. Checklist attachments will show missing where applicable.",
        )
