"""V3 board reporting and operator settings, using shared domain services."""

import streamlit as st

from credit_monitoring.application.board_reporting import BoardReporting
from credit_monitoring.application.borrower_workflow import PREDICTION_MODES
from credit_monitoring.application.data_maintenance import recreate_database
from credit_monitoring.config.settings import DEFAULT_APP_PREDICTION_MODE
from credit_monitoring.web.board_report import render_report_content
from credit_monitoring.web_v3.state import attempt, commit


def render_board(services, period, cutoff) -> None:
    st.title("Board reports")
    reporting = BoardReporting(services.manager)
    reports = {r["report_id"]: r for r in reporting.repository.board_reports()}
    requested = st.session_state.pop("v3_next_report", None)
    linked = st.query_params.get("report_id")
    if linked and linked != st.session_state.get("v3_report_link_seen"):
        st.session_state.v3_report_link_seen = linked
        requested = linked
        if linked not in reports:
            st.warning("The linked report was not found in shared saved data.")
    if requested in reports:
        st.session_state.v3_report = requested
    options = ["new", *reports]
    if st.session_state.get("v3_report") not in options:
        st.session_state.v3_report = "new"
    selected = st.selectbox(
        "Report version",
        options,
        key="v3_report",
        format_func=lambda r: (
            "New report draft"
            if r == "new"
            else f"{reports[r]['payload']['title']} · {reports[r]['state']} · {r}"
        ),
    )
    if selected == "new":
        st.query_params.pop("report_id", None)
        st.session_state.v3_report_link_seen = None
        title = st.text_input("Report title", "Quarterly credit risk review", key="v3_board_title")
        if st.button("Generate report draft", key="v3btn_board_generate", type="primary"):
            rid, success = attempt(
                lambda: reporting.generate(period, cutoff, title=title), "Board report draft saved."
            )
            if success:
                st.session_state.v3_next_report = rid
                st.rerun()
        return
    st.query_params["report_id"] = selected
    st.session_state.v3_report_link_seen = selected
    report = reports[selected]
    render_report_content(report)
    if report["state"] == "final":
        st.success("Final report · frozen snapshot. Generate a new draft for later changes.")
        return
    st.subheader("Edit draft")
    payload = report["payload"]
    with st.form(f"v3form_board_{selected}"):
        title = st.text_input("Title", payload["title"], key=f"v3_board_title_{selected}")
        summary = st.text_area(
            "Executive summary", payload["summary"], height=180, key=f"v3_board_summary_{selected}"
        )
        recommendations = {
            i["borrower_id"]: st.text_input(
                f"Recommendation · {i['name']}",
                payload["recommendations"].get(i["borrower_id"], i.get("recommendation", "")),
                key=f"v3_board_rec_{selected}_{i['borrower_id']}",
            )
            for i in payload["sources"]["items"]
        }
        save, refresh, finalize = st.columns(3)
        draft = save.form_submit_button("Save report draft")
        update = refresh.form_submit_button("Refresh draft sources")
        final = finalize.form_submit_button("Finalize report", type="primary")
        if draft or update or final:
            rid, success = attempt(
                lambda: reporting.save(
                    selected,
                    title=title,
                    summary=summary,
                    recommendations=recommendations,
                    finalize=final,
                    refresh=update,
                ),
                "Report version saved.",
            )
            if success:
                st.session_state.v3_next_report = rid
                st.rerun()
    st.caption(
        "Every save creates a version. Changed sources must be refreshed "
        "and inspected before finalization."
    )


def render_settings(services) -> None:
    import os

    st.title("Settings")
    st.selectbox(
        "Prediction mode for new assessments",
        PREDICTION_MODES,
        index=PREDICTION_MODES.index(DEFAULT_APP_PREDICTION_MODE),
        key="v3_prediction",
    )
    st.write(
        "AI access: "
        + (
            "Configured"
            if os.getenv("OPENAI_API_KEY", "").strip()
            else "Not configured — ask the operator to enable model access"
        )
    )
    st.text_input(
        "SEC download identity (name / organization and email)",
        value=services.documents.processor.user_agent,
        key="v3_download_identity",
    )
    st.number_input(
        "Documents processed at once", min_value=1, max_value=16, value=4, key="v3_workers"
    )
    st.caption(
        "These preferences last for the browser session. Shared saved assessments "
        "retain their original settings."
    )
    with st.expander("Working data maintenance"):
        workspace = services.documents
        target = st.selectbox(
            "Rebuild target",
            ["Retrieval index", "Financial database", "Extraction database", "Analytics database"],
            key="v3_rebuild_target",
        )
        sources = {
            "Retrieval index": "Locally processed Markdown sources",
            "Financial database": str(
                workspace.data_root / "app/synthetic/synthetic_quarterly_financials.csv"
            ),
            "Extraction database": str(workspace.archive_path),
            "Analytics database": "Retained assessments in portfolio.sqlite3",
        }
        destinations = {
            "Financial database": workspace.working_dir / "financials.sqlite3",
            "Extraction database": workspace.processor.repository.database_path,
            "Analytics database": workspace.working_dir / "analytics.sqlite3",
        }
        st.write("Recovery source: " + sources[target])
        if target in destinations:
            st.code(str(destinations[target]), language=None)
            st.caption(
                "Replaces this shared database for all borrowers after saving a "
                "backup. Financial recreation restores source inputs and marks saved "
                "assessments for review."
            )
        if st.button("Rebuild selected target", key="v3btn_rebuild", disabled=workspace.busy):

            def rebuild():
                with st.spinner("Rebuilding and checking working data…"):
                    result = (
                        workspace.rebuild_index()
                        if target == "Retrieval index"
                        else recreate_database(workspace, target)
                    )
                st.session_state.v3_rebuild_result = result

            commit(rebuild, "Working data rebuilt.")
        if result := st.session_state.get("v3_rebuild_result"):
            st.json(result)
