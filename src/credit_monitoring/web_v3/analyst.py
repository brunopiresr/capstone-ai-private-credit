"""Analyst queue and guided borrower workspace over existing workflow safeguards."""

from dataclasses import replace
from html import escape

import pandas as pd
import streamlit as st

from credit_monitoring.application.borrower_workflow import SavedFinancials
from credit_monitoring.config.settings import DEFAULT_APP_PREDICTION_MODE
from credit_monitoring.domain.credit_review import ExposureDecisionContext
from credit_monitoring.domain.financials import FINANCIAL_METRICS
from credit_monitoring.web.assessment import render_evidence, render_verification
from credit_monitoring.web.borrower_views import (
    render_covenant_table,
    render_saved_trend,
    render_summary_metrics,
)
from credit_monitoring.web.portfolio import (
    DEFAULT_CRITERIA,
    DEFAULT_REVIEW_QUESTION,
    formatted_time,
    render_agent_result,
)
from credit_monitoring.web_v3.readiness import FILTERS, project, submission_blockers
from credit_monitoring.web_v3.state import attempt, commit, go


def credentials() -> bool:
    import os

    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def render_queue(services, period, cutoff) -> None:
    st.title("Analyst work queue")
    st.caption(
        "Start with the next action. Evidence readiness, credit risk and "
        "review progress are separate."
    )
    entries = services.analyst.portfolio.snapshot(period_end=period, cutoff=cutoff)
    inventory = services.documents.inventory()
    projected = [
        (e, project(services, e, period or e.period_end or cutoff, inventory)) for e in entries
    ]
    counts = {name: sum(name in r.categories for _, r in projected) for name in FILTERS}
    columns = st.columns(4)
    for column, name in zip(
        columns,
        ["Needs action", "Missing documents", "Manager requests", "Ready to submit"],
        strict=True,
    ):
        column.metric(name, counts[name])
    st.caption("Counts overlap: one borrower may need more than one action.")
    left, right = st.columns([2, 1])
    search = (
        left.text_input(
            "Search borrowers", key="v3_search", placeholder="Borrower name, ID or sector"
        )
        .casefold()
        .strip()
    )
    selected = right.selectbox(
        "Work to do", FILTERS, key="v3_filter", format_func=lambda s: f"{s} ({counts[s]})"
    )
    selected_entries = [
        (e, r)
        for e, r in projected
        if selected in r.categories
        and (not search or search in f"{e.name} {e.borrower_id} {e.sector}".casefold())
    ]
    if not selected_entries:
        st.info("No borrowers match this queue. Choose another filter or All borrowers.")
    for entry, readiness in selected_entries:
        with st.container(border=True):
            details, action = st.columns([4, 1.5], vertical_alignment="center")
            details.subheader(entry.name)
            details.caption(
                f"{entry.borrower_id} · {entry.sector} · "
                f"{entry.period_end or 'No financial period'}"
            )
            details.write(
                f"**Compliance:** {entry.compliance} · **Evidence:** {readiness.evidence} "
                f"· **Review:** {readiness.review}"
            )
            details.write(" ".join(readiness.reasons[:3]))
            if action.button(
                readiness.action,
                key=f"v3btn_queue_{entry.borrower_id}",
                width="stretch",
                type="primary",
            ):
                st.session_state.v3_document_return = "Borrower"
                go(
                    "Documents" if readiness.section == "Documents" else "Borrower",
                    entry.borrower_id,
                    readiness.section,
                )
            if action.button(
                "Open borrower", key=f"v3btn_open_{entry.borrower_id}", width="stretch"
            ):
                go("Borrower", entry.borrower_id, "Overview")
    with st.expander("Full portfolio comparison table"):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Borrower": e.name,
                        "ID": e.borrower_id,
                        "Period": str(e.period_end or "Unavailable"),
                        "Compliance": e.compliance,
                        "Evidence": r.evidence,
                        "Review": r.review,
                        "Next action": r.action,
                    }
                    for e, r in projected
                ]
            ),
            hide_index=True,
            width="stretch",
        )


def selected_entry(services, period, cutoff):
    entries = services.analyst.portfolio.snapshot(period_end=period, cutoff=cutoff)
    if not entries:
        st.info("No borrowers are registered.")
        return None, []
    names = {e.borrower_id: e.name for e in entries}
    if st.session_state.get("v3_borrower") not in names:
        st.session_state.v3_borrower = entries[0].borrower_id
    bid = st.selectbox("Borrower", list(names), format_func=names.get, key="v3_borrower")
    entry = next(e for e in entries if e.borrower_id == bid)
    target = period or entry.period_end
    versions = [
        (a, t)
        for a, t in services.analyst.portfolio.repository.assessment_history(bid)
        if a.period_end == target and a.information_cutoff <= cutoff
    ]
    if versions:
        lookup = {a.assessment_run_id: (a, t) for a, t in versions}
        key = f"v3_version_{bid}_{target}"
        next_run = st.session_state.pop("v3_next_run", None)
        if next_run in lookup:
            st.session_state[key] = next_run
        if st.session_state.get(key) not in lookup:
            st.session_state[key] = versions[0][0].assessment_run_id
        chosen = st.selectbox(
            "Assessment version",
            list(lookup),
            key=key,
            format_func=lambda rid: (
                f"v{len(versions) - list(lookup).index(rid)} · {formatted_time(lookup[rid][1])}"
            ),
        )
        assessment = lookup[chosen][0]
        entry = replace(
            entry,
            assessment=assessment,
            review=services.analyst.portfolio.repository.latest_review(chosen),
        )
    return entry, versions


def render_borrower(services, period, cutoff, *, assistant=False) -> None:
    if st.button("← Back to analyst queue", key="v3btn_borrower_back"):
        go("Analyst queue")
    entry, versions = selected_entry(services, period, cutoff)
    if entry is None:
        return
    target = period or entry.period_end or cutoff
    assessment = entry.assessment
    readiness = project(services, entry, target, services.documents.inventory())
    st.title(entry.name)
    st.caption(f"{entry.borrower_id} · Reporting period {target} · Information cutoff {cutoff}")
    if assessment:
        st.caption(f"Saved information cutoff {assessment.information_cutoff}")
        if assessment.information_cutoff != cutoff:
            st.info(
                "This saved version uses an earlier cutoff. Run a new assessment "
                "to include the selected cutoff."
            )
    st.html(
        " ".join(
            f'<span class="v3-badge">{escape(label)}: {escape(value)}</span>'
            for label, value in [
                ("Evidence", readiness.evidence),
                ("Compliance", entry.compliance),
                ("Review", readiness.review),
            ]
        )
    )
    if assistant:
        from credit_monitoring.web_v3.assistant import render_assistant

        if st.button("← Back to borrower findings", key="v3btn_assistant_back"):
            go("Borrower")
        if assessment:
            render_assistant(services, assessment)
        else:
            st.info("Run a covenant assessment before asking about saved results.")
        return
    st.html(
        f'<div class="v3-next"><b>Next action: {escape(readiness.action)}</b><br>'
        f"{escape(' '.join(readiness.reasons[:2]))}</div>"
    )
    if st.button(readiness.action, key="v3btn_next_action", type="primary"):
        if readiness.section == "Documents":
            st.session_state.v3_document_return = "Borrower"
            go("Documents", entry.borrower_id)
        go("Borrower", section=readiness.section)
    progress = [
        (
            "Documents",
            "Not configured"
            if readiness.evidence == "Requirements not configured"
            else readiness.evidence,
        ),
        (
            "Assessment",
            "Outdated"
            if "Assessment needed / outdated" in readiness.categories and assessment
            else "Saved"
            if assessment
            else "Needed",
        ),
        ("Analyst review", "Validated" if readiness.validated else "Needed"),
        ("Submission", "Sent" if readiness.submission else "Not sent"),
        ("Manager decision", readiness.review if readiness.submission else "Awaiting submission"),
    ]
    st.write(" → ".join(f"**{name}:** {status}" for name, status in progress))
    actions = st.columns(4)
    if actions[0].button("Process documents", key="v3btn_docs", width="stretch"):
        st.session_state.v3_document_return = "Borrower"
        go("Documents", entry.borrower_id)
    if actions[1].button("Run covenant assessment", key="v3btn_assess", width="stretch"):
        mode = st.session_state.get("v3_prediction", DEFAULT_APP_PREDICTION_MODE)
        with st.spinner("Calculating covenants and saving a new version…"):
            new, success = attempt(
                lambda: services.analyst.assess(
                    entry.borrower_id, target, cutoff, prediction_mode=mode
                ),
                "Assessment saved. Inspect and validate this new version.",
            )
        if success:
            st.session_state.v3_next_run = new.assessment_run_id
            go("Borrower", section="Overview")
    if actions[2].button(
        "Generate AI credit analysis",
        key="v3btn_ai",
        width="stretch",
        disabled=not assessment or not credentials() or not assessment.verification.is_valid,
    ):
        go("Borrower", section="AI analysis")
    if actions[3].button(
        "Review and submit findings", key="v3btn_review", width="stretch", disabled=not assessment
    ):
        go("Borrower", section="Review and submit")
    if not assessment:
        st.caption("AI analysis and submission become available after an assessment is saved.")
    elif not credentials():
        st.caption(
            "AI analysis and assistant replies need model access configured "
            "by the operator. Saved results remain readable."
        )
    elif not assessment.verification.is_valid:
        st.caption(
            "AI analysis is unavailable until structured verification errors "
            "are resolved in Evidence."
        )
    if st.button("Ask credit assistant ↗", key="v3btn_assistant", disabled=not assessment):
        go("Assistant")
    if not assessment:
        st.info(
            "No saved assessment for this period. Process evidence as needed, "
            "then run the covenant assessment."
        )
        return
    if services.analyst.needs_review(assessment.assessment_run_id):
        st.warning("Sources changed. Run a new assessment before validating or submitting.")
    render_save_draft(services.analyst, assessment)
    sections = ["Overview", "Evidence", "AI analysis", "Review and submit", "History"]
    if st.session_state.get("v3_section") not in sections:
        st.session_state.v3_section = "Overview"
    section = st.radio("Borrower section", sections, horizontal=True, key="v3_section")
    if section == "Overview":
        render_summary_metrics(assessment)
        render_covenant_table(assessment, key="v3table_covenants")
        if assessment.narrative:
            st.write(assessment.narrative)
        if entry.review:
            st.subheader("AI recommendation · advisory")
            st.write(entry.review.recommendation.rationale)
            with st.expander("Supporting AI arguments and evidence"):
                render_agent_result(entry.review)
        render_saved_trend(assessment)
    elif section == "Evidence":
        render_verification(assessment)
        render_evidence(assessment)
        render_covenant_table(assessment, key="v3table_evidence_covenants")
        render_recalculation(services, assessment)
    elif section == "AI analysis":
        render_ai(services, assessment)
    elif section == "Review and submit":
        render_handoff(services, assessment, readiness)
    else:
        st.subheader("Saved assessment versions")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Run": a.assessment_run_id,
                        "Saved": formatted_time(t),
                        "Cutoff": str(a.information_cutoff),
                    }
                    for a, t in versions
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        for submission in services.analyst.repository.submissions(entry.borrower_id):
            with st.expander(f"Submission · {formatted_time(submission['created_at'])}"):
                st.write(submission["payload"]["text"])
                st.caption(f"Frozen assessment {submission['run_id']}")
                st.json(submission["payload"], expanded=False)


def render_save_draft(workflow, assessment) -> None:
    rid = assessment.assessment_run_id
    records = workflow.repository.events(rid, "draft") + [
        s for s in workflow.repository.submissions(assessment.borrower_id) if s["run_id"] == rid
    ]
    saved = max(records, key=lambda r: r["created_at"], default={}).get("payload", {})
    text = st.session_state.get(f"v3_findings_{rid}", saved.get("text", ""))
    with st.container(key="v3_actionbar", horizontal=True):
        if st.button("Save draft", key="v3btn_draft", disabled=not text.strip()):
            commit(
                lambda: workflow.save_report(
                    rid,
                    text=text,
                    analyst=st.session_state.get(f"v3_author_{rid}", saved.get("analyst", "")),
                    triage=st.session_state.get(f"v3_triage_{rid}", saved.get("triage", "")),
                ),
                "Draft saved.",
            )
        st.caption(
            "Record findings in Review and submit. Save draft stays available across sections."
        )


def render_ai(services, assessment) -> None:
    st.subheader("Generate AI credit analysis")
    st.caption(
        "Optional advisory analysis. Reads the selected saved assessment; provider usage applies."
    )
    with st.form(f"v3form_ai_{assessment.assessment_run_id}"):
        question = st.text_input(
            "Decision question",
            DEFAULT_REVIEW_QUESTION,
            key=f"v3_ai_question_{assessment.assessment_run_id}",
        )
        with st.expander("Criteria and constraints"):
            criteria = st.text_area(
                "Credit criteria",
                DEFAULT_CRITERIA,
                key=f"v3_ai_criteria_{assessment.assessment_run_id}",
            )
            constraints = st.text_area(
                "Additional constraints", key=f"v3_ai_constraints_{assessment.assessment_run_id}"
            )
        if st.form_submit_button(
            "Generate analysis", disabled=not credentials() or not assessment.verification.is_valid
        ):

            def run():
                if not question.strip() or not criteria.strip():
                    raise ValueError(
                        "Supply a decision question and at least one credit criterion."
                    )
                with st.spinner("Reviewing supporting and opposing arguments…"):
                    return services.analyst.portfolio.review(
                        assessment.assessment_run_id,
                        ExposureDecisionContext(
                            question=question.strip(),
                            credit_criteria=tuple(
                                c.strip() for c in criteria.splitlines() if c.strip()
                            ),
                            constraints=(constraints.strip(),) if constraints.strip() else (),
                        ),
                    )

            commit(run, "AI analysis saved. Complete fresh analyst validation before submitting.")
    review = services.analyst.portfolio.repository.latest_review(assessment.assessment_run_id)
    if review:
        render_agent_result(review)


def render_recalculation(services, assessment) -> None:
    with st.expander("Revise financial inputs and recalculate"):
        st.caption(
            "Values use the source currency and scale above. A cleared value "
            "records a missing input. A new version needs fresh validation."
        )
        rid = assessment.assessment_run_id
        metrics = st.multiselect(
            "Inputs to revise", FINANCIAL_METRICS, key=f"v3_revise_metrics_{rid}"
        )
        periods = SavedFinancials(assessment).get_period_history(assessment.borrower_id)
        current = next((p for p in periods if p.period_end == assessment.period_end), None)
        with st.form(f"v3form_revise_{rid}"):
            overrides = {
                m: st.number_input(
                    m.replace("_", " ").title(),
                    value=current.metrics.get(m) if current else None,
                    step=0.1,
                    key=f"v3_revise_{rid}_{m}",
                )
                for m in metrics
            }
            reason = st.text_input("Reason for recalculation", key=f"v3_revise_reason_{rid}")
            if st.form_submit_button("Recalculate and save new version"):

                def run():
                    if not overrides:
                        raise ValueError("Select at least one financial input to revise.")
                    return services.analyst.assess(
                        assessment.borrower_id,
                        assessment.period_end,
                        st.session_state.v3_cutoff,
                        parent_id=rid,
                        overrides=overrides,
                        reason=reason,
                        prediction_mode=st.session_state.get(
                            "v3_prediction", DEFAULT_APP_PREDICTION_MODE
                        ),
                    )

                new, success = attempt(run, "Recalculated version saved.")
                if success:
                    st.session_state.v3_next_run = new.assessment_run_id
                    st.rerun()


def render_handoff(services, assessment, readiness) -> None:
    from credit_monitoring.web_v3.manager import render_requests

    workflow = services.analyst
    rid = assessment.assessment_run_id
    st.subheader("Manager feedback and requests")
    for note in workflow.repository.notes(assessment.borrower_id)[:3]:
        st.write(note["payload"]["comment"] or note["payload"]["recommendation"])
    render_requests(services, assessment.borrower_id, analyst=True)
    if readiness.evidence != "No documents required":
        st.info(
            f"Document checklist warning / readiness: {readiness.evidence}. This "
            f"does not add submission blockers."
        )
    drafts = workflow.repository.events(rid, "draft")
    records = drafts + [
        s for s in workflow.repository.submissions(assessment.borrower_id) if s["run_id"] == rid
    ]
    previous = max(records, key=lambda r: r["created_at"], default={}).get("payload", {})
    validation = workflow.validation(rid)
    st.subheader("1 · Record findings")
    author = st.text_input(
        "Analyst name (optional)", value=previous.get("analyst", ""), key=f"v3_author_{rid}"
    )
    text = st.text_area(
        "Findings and proposed recommendation",
        value=previous.get("text", ""),
        height=180,
        key=f"v3_findings_{rid}",
    )
    st.caption(
        "Unsaved edits survive in-session navigation. Save draft to retain findings after restart."
    )
    st.subheader("2 · Address risks")
    triage = st.text_area(
        "Breach triage decision (required when this version has an unflagged breach)",
        value=previous.get("triage", ""),
        key=f"v3_triage_{rid}",
    )
    with st.expander("Add a risk flag"):
        with st.form(f"v3form_flag_{rid}"):
            category = st.selectbox(
                "Category",
                ["Covenant breach", "Data quality", "Liquidity", "Performance", "Other"],
                key=f"v3_flag_category_{rid}",
            )
            severity = st.selectbox(
                "Severity", ["Medium", "High", "Critical", "Low"], key=f"v3_flag_severity_{rid}"
            )
            explanation = st.text_area("Flag explanation", key=f"v3_flag_explanation_{rid}")
            proposed = st.text_input("Proposed action", key=f"v3_flag_action_{rid}")
            if st.form_submit_button("Add flag"):
                commit(
                    lambda: workflow.flag(
                        rid,
                        category=category,
                        severity=severity,
                        explanation=explanation,
                        action=proposed,
                    ),
                    "Flag saved.",
                )
    for flag in services.manager.active_flags(assessment.borrower_id):
        st.write(
            f"**{flag['payload']['severity']} · {flag['payload']['category']}** "
            f"— {flag['payload']['explanation']}"
        )
    st.subheader("3 · Check evidence and validate")
    if st.button("Open evidence to resolve issues", key="v3btn_review_evidence"):
        go("Borrower", section="Evidence")
    current_review = workflow.portfolio.repository.latest_review(rid)
    scope = f"{rid}_{current_review.review_id if current_review else 'none'}"
    checks = tuple(
        st.checkbox(label, value=bool(validation), key=f"v3_check_{scope}_{i}")
        for i, label in enumerate(
            [
                "I checked financial inputs and source references",
                "I checked applied terms and calculations",
                "I reviewed the analysis and documented exceptions",
            ]
        )
    )
    notes = st.text_area(
        "Validation notes / exceptions",
        value=validation["payload"]["notes"] if validation else "",
        key=f"v3_validation_notes_{rid}",
    )
    problems = []
    if not all(checks):
        problems.append("Complete all three human review checks.")
    if not assessment.verification.is_valid or any(
        i.severity == "error" for i in assessment.verification.issues
    ):
        problems.append("Resolve structured verification errors in Evidence.")
    if workflow.needs_review(rid):
        problems.append("Sources changed; run a new assessment.")
    if workflow.needs_exceptions(assessment) and not notes.strip():
        problems.append("Document missing inputs and unresolved exceptions in validation notes.")
    for problem in problems:
        st.warning(problem)
    if st.button("Validate selected version", key="v3btn_validate", disabled=bool(problems)):
        commit(
            lambda: workflow.validate(rid, checks=checks, notes=notes, analyst=author),
            "Validation saved.",
        )
    if validation:
        st.success(
            "Validated with exceptions."
            if validation["payload"]["with_exceptions"]
            else "Validated."
        )
    st.subheader("4 · Preview and submit")
    blockers = submission_blockers(workflow, assessment, text, triage)
    for blocker in blockers:
        st.warning(blocker)
    with st.expander("Submission preview", expanded=True):
        st.write(text or "No findings recorded yet.")
        st.caption(f"Analyst: {author or 'Unspecified'} · Assessment {rid} · Frozen at submission")
        if triage:
            st.write(f"Breach triage: {triage}")
        st.write(
            f"Validation: {('Complete' if validation else 'Needed')} · Open flags: "
            f"{len(services.manager.active_flags(assessment.borrower_id))}"
        )
    if st.button(
        "Submit to risk manager", key="v3btn_submit", type="primary", disabled=bool(blockers)
    ):
        commit(
            lambda: workflow.save_report(
                rid, text=text, analyst=author, triage=triage, submit=True
            ),
            "Submitted. The saved handoff is frozen.",
        )
    if readiness.submission:
        st.success(f"Submitted · {formatted_time(readiness.submission['created_at'])}")
        if st.button("Open manager case", key="v3btn_open_manager"):
            go("Risk case", assessment.borrower_id)
