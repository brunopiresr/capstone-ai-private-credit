"""Connected portfolio page; calculations and agent reviews are explicit user actions."""

import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import dotenv
import pandas as pd
import streamlit as st

from credit_monitoring.agents.models import DEFAULT_MODEL
from credit_monitoring.application.bootstrap import create_portfolio_service
from credit_monitoring.application.portfolio_service import (
    STATUS_LABELS,
    PortfolioEntry,
    PortfolioService,
)
from credit_monitoring.domain.credit_review import CreditReviewResult, ExposureDecisionContext
from credit_monitoring.paths import DATA_ROOT, RUNTIME_DIR
from credit_monitoring.web.assessment import render_evidence, render_results, render_verification
from credit_monitoring.web.user_guide import render_help, render_invitation

DEFAULT_DATA_ROOT = DATA_ROOT
DEFAULT_WORKING_DIR = RUNTIME_DIR / "portfolio"
DEFAULT_REVIEW_QUESTION = "What action is appropriate for this existing exposure?"
DEFAULT_CRITERIA = (
    "Assess covenant compliance, headroom and comparable performance trends.\n"
    "Consider liquidity, data conflicts and material evidence gaps.\n"
    "Recommend an action for the existing exposure and explain both perspectives."
)


def get_portfolio_service(data_root: str, working_dir: str, model: str) -> PortfolioService:
    # These are lightweight service/repository handles; the results live in SQLite.
    # A resource cache can retain an old class instance when imported service code changes.
    return create_portfolio_service(
        data_root=Path(data_root), working_dir=Path(working_dir), model=model
    )


def selected_from_table(widget_key: str, borrower_ids: tuple[str, ...]) -> None:
    selection = st.session_state[widget_key]["selection"]
    rows = tuple(selection.get("rows", []))
    cells = tuple(tuple(cell) for cell in selection.get("cells", []))
    previous = st.session_state.get("portfolio_table_selection", {})
    if previous.get("key") != widget_key:
        previous = {}
    if cells and cells != previous.get("cells", ()):
        row = cells[0][0]
    elif rows and rows != previous.get("rows", ()):
        row = rows[0]
    else:
        return
    if 0 <= row < len(borrower_ids):
        st.session_state.portfolio_borrower = borrower_ids[row]


def change_borrower() -> None:
    st.session_state.portfolio_table_revision = (
        st.session_state.get("portfolio_table_revision", 0) + 1
    )


def formatted_time(value: str | None) -> str:
    if not value:
        return "—"
    return (
        datetime.fromisoformat(value)
        .astimezone(ZoneInfo("Europe/Lisbon"))
        .strftime("%d %b %Y %H:%M")
    )


def metric_value(value: float | None, unit: str | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}{unit or ''}"


def entry_row(entry: PortfolioEntry) -> dict:
    assessment = entry.assessment
    results = assessment.results if assessment else []
    # The displayed metric always names its covenant; other results remain in the detail view.
    primary = next((result for result in results if result.compliance_status == "breach"), None)
    primary = primary or (results[0] if results else None)
    digits = 6 if primary and primary.calculation_version == "bundle_v1" else 2
    return {
        "Borrower": entry.name,
        "ID": entry.borrower_id,
        "Sector": entry.sector,
        "Period": entry.period_end.isoformat() if entry.period_end else "No financials",
        "Compliance": entry.compliance,
        "Source review": "Needs reassessment" if entry.needs_review else "—",
        "Covenant": primary.covenant_type.replace("_", " ") if primary else "—",
        "Actual": metric_value(primary.actual_value, primary.unit, digits) if primary else "—",
        "Threshold": (
            f"{primary.operator or ''} "
            f"{metric_value(primary.threshold, primary.unit, digits)}".strip()
        )
        if primary
        else "—",
        "Headroom": metric_value(primary.headroom, primary.unit, digits) if primary else "—",
        "Agent review": entry.review.status.title() if entry.review else "Not run",
        "Last assessment (Lisbon)": formatted_time(entry.created_at),
        "Last attempt": ("Failed — saved result retained" if entry.assessment else "Failed")
        if entry.last_error
        else "—",
    }


def run_assessments(
    service: PortfolioService,
    borrower_ids: list[str],
    period_end: date | None,
    cutoff: date,
    review_context: ExposureDecisionContext | None = None,
) -> None:
    with st.status("Running covenant assessments…", expanded=True) as status:
        progress = st.progress(0.0)
        current = st.empty()

        def on_progress(index, total, outcome):
            review_state = f" · Agent review: {outcome.review.status}" if outcome.review else ""
            current.write(
                f"{index}/{total} · {outcome.borrower_id} · "
                + (outcome.error or "Assessment saved")
                + (f" · {outcome.review_error}" if outcome.review_error else review_state)
                + (f" · {outcome.follow_up_error}" if outcome.follow_up_error else "")
            )
            progress.progress(index / total)

        def on_stage(index, total, borrower_id, stage):
            current.write(f"{index}/{total} · {borrower_id} · {stage}…")

        outcomes = service.assess(
            borrower_ids,
            period_end=period_end,
            cutoff=cutoff,
            progress=on_progress,
            review_context=review_context,
            stage_progress=on_stage,
        )
        failed = sum(outcome.error is not None for outcome in outcomes)
        review_attention = sum(
            bool(outcome.review_error or (outcome.review and outcome.review.status != "complete"))
            for outcome in outcomes
        )
        summary = f"{len(outcomes) - failed} assessments saved · {failed} failed"
        if review_context is not None:
            completed = sum(bool(o.review and o.review.status == "complete") for o in outcomes)
            summary += f" · {completed} reviews complete · {review_attention} need attention"
            question_failures = sum(bool(o.follow_up_error) for o in outcomes)
            if question_failures:
                summary += (
                    f" · {question_failures} question sets unavailable; retry in the assistant"
                )
        status.update(
            label=summary,
            state="error" if failed or review_attention else "complete",
        )
    st.session_state.portfolio_outcomes = [
        {
            "Borrower": outcome.borrower_id,
            "Period": outcome.period_end.isoformat() if outcome.period_end else "Unavailable",
            "Outcome": outcome.error or "Saved",
            "Agent review": outcome.review.status.title()
            if outcome.review
            else (
                "Failed"
                if outcome.review_error
                else (
                    "Skipped — assessment failed" if review_context is not None else "Not requested"
                )
            ),
            "Review issue": outcome.review_error or "",
            "Follow-up questions": outcome.follow_up_error
            or ("Generated" if outcome.review and service.follow_up_service else "Not requested"),
        }
        for outcome in outcomes
    ]
    st.rerun()


def render_agent_result(review: CreditReviewResult) -> None:
    st.subheader("Credit analysis snapshot")
    st.caption(f"Review {review.review_id} · {review.created_at.isoformat()} · {review.status}")
    if review.status != "complete":
        st.warning(
            "This review is incomplete or blocked. "
            "Available perspectives and the deferral remain visible."
        )
    for issue in review.issues:
        st.warning(issue)
    columns = st.columns(3)
    for column, name, perspective in (
        (columns[0], "Bullish agent", review.bullish),
        (columns[1], "Bearish agent", review.bearish),
    ):
        with column:
            with st.container(border=True):
                st.subheader(name)
                if perspective.analysis is None:
                    st.warning(
                        f"{perspective.execution.status}: "
                        f"{perspective.execution.error_code or 'Unavailable'}"
                    )
                else:
                    analysis = perspective.analysis
                    st.markdown(f"**{analysis.thesis}**")
                    for argument in analysis.arguments:
                        st.markdown(f"- {argument.statement}")
                    st.caption(f"Evidence confidence: {analysis.confidence}")
                    st.caption(analysis.confidence_explanation)
                st.caption(f"Model: {perspective.execution.model}")
    with columns[2]:
        with st.container(border=True):
            st.subheader("Recommendation agent")
            st.markdown(f"**{review.recommendation.action.title()}**")
            st.write(review.recommendation.rationale)
            for judgment in review.recommendation.argument_judgments[:3]:
                st.markdown(
                    f"- **{judgment.perspective.title()} · {judgment.disposition}:** "
                    f"{judgment.rationale}"
                )
            for condition in review.recommendation.conditions:
                st.markdown(f"- {condition}")
            st.caption(f"Evidence confidence: {review.recommendation.confidence}")
            st.caption(review.recommendation.confidence_explanation)
            st.caption(f"Model: {review.recommendation_execution.model}")
            st.caption("Advisory result; analyst and manager decisions remain separate.")
    with st.expander("Argument rationales, evidence and limitations"):
        for perspective in (review.bullish, review.bearish):
            if perspective.analysis:
                st.subheader(perspective.perspective.title())
                for argument in perspective.analysis.arguments:
                    st.markdown(f"**{argument.argument_id} · {argument.statement}**")
                    st.write(argument.rationale)
                    st.write(argument.credit_implication)
                    st.caption("Evidence: " + ", ".join(argument.evidence_ids))
                    for assumption in argument.assumptions:
                        st.caption(f"Assumption: {assumption}")
                st.json(perspective.analysis.model_dump(mode="json"))
        st.subheader("Recommendation judgments and open questions")
        st.json(review.recommendation.model_dump(mode="json"))
        st.caption("News is explicitly unavailable unless an actual provider supplied it.")
        st.json(review.snapshot.model_dump(mode="json"), expanded=False)


def render_selected(
    entry: PortfolioEntry, service: PortfolioService, credentials_available: bool
) -> None:
    st.divider()
    st.header(entry.name)
    st.caption(f"{entry.borrower_id} · {entry.sector} · Connected service results")
    if entry.last_error:
        st.error(entry.last_error)
    assessment = entry.assessment
    if assessment is None:
        st.info(
            "No saved assessment for this reporting period and cutoff. "
            "Run the selected borrower assessment above."
        )
        return
    st.caption(
        f"Reporting period {assessment.period_end}"
        f" · Saved information cutoff {assessment.information_cutoff}"
        f" · Run {assessment.assessment_run_id}"
    )
    st.caption("Saved results are shown as recorded; rerunning creates a new assessment version.")
    results, reviews = st.tabs(["Assessment & evidence", "Agent analysis"])
    with results:
        render_results(assessment)
        with st.expander("Verification and data limitations", expanded=entry.needs_data):
            render_verification(assessment)
        with st.expander("Source financial inputs and applied terms"):
            render_evidence(assessment)
    with reviews:
        render_review_controls(entry, service, credentials_available)


def render_review_controls(
    entry: PortfolioEntry, service: PortfolioService, credentials_available: bool
) -> None:
    assessment = entry.assessment
    render_help("Credit reviews and forecasts", "How credit reviews and forecasts work")
    if assessment is None:
        st.info("Run and save an assessment before requesting a credit review.")
        return
    st.caption(
        "The bullish, bearish and recommendation agents read this exact saved assessment. "
        "A follow-up agent then generates questions from the calculations and their analyses. "
        "These model requests incur provider usage."
    )
    if not credentials_available:
        st.info(
            "Set OPENAI_API_KEY in .env or the environment to run agent reviews. "
            "Saved reviews remain available."
        )
    if not assessment.verification.is_valid:
        st.warning("Resolve the structured verification errors before requesting an agent review.")
    with st.form(f"portfolio_review_form_{assessment.assessment_run_id}"):
        question = st.text_input("Credit review question", DEFAULT_REVIEW_QUESTION)
        criteria = st.text_area("Credit criteria", DEFAULT_CRITERIA, height=130)
        context = st.text_area(
            "Additional context / constraints",
            placeholder="Provide decision criteria or explicit assumptions; "
            "sources are limited to the saved assessment.",
        )
        requested = st.form_submit_button(
            "Run agent review",
            type="primary",
            disabled=not credentials_available or not assessment.verification.is_valid,
        )
        if requested:
            if not question.strip() or not criteria.strip():
                st.warning("Supply a review question and at least one credit criterion.")
            else:
                try:
                    decision = ExposureDecisionContext(
                        question=question.strip(),
                        credit_criteria=tuple(
                            line.strip() for line in criteria.splitlines() if line.strip()
                        ),
                        constraints=(context.strip(),) if context.strip() else (),
                    )
                    with st.status(
                        "Running bullish, bearish and recommendation agents…", expanded=True
                    ):
                        review = service.review(
                            assessment.assessment_run_id,
                            decision,
                            follow_up_progress=lambda: st.write("Generating follow-up questions…"),
                        )
                        st.write(f"Review saved · {review.status}")
                        if issue := service.follow_up_errors.get(review.review_id):
                            st.warning(issue)
                    st.rerun()
                except Exception as error:
                    st.error(
                        f"Agent review failed ({type(error).__name__}). "
                        "The assessment and earlier reviews are retained."
                    )
    if entry.review:
        render_agent_result(entry.review)
    else:
        st.info("No agent review is saved for this assessment version.")


def render_portfolio_page() -> None:
    st.markdown(
        '<div class="preview-eyebrow">Credit analyst / Portfolio</div>', unsafe_allow_html=True
    )
    st.title("Your portfolio, at a glance")
    render_invitation()
    render_help("Portfolio and dates", "How to choose dates and run assessments")
    st.caption(
        "Calculated from the loaded borrower financials and covenant terms. "
        "Synthetic inputs · Explicit assessment and review actions."
    )
    dotenv.load_dotenv(DEFAULT_DATA_ROOT.parent / ".env")
    try:
        service = get_portfolio_service(
            str(DEFAULT_DATA_ROOT),
            str(DEFAULT_WORKING_DIR),
            os.getenv("LLM_MODEL") or DEFAULT_MODEL,
        )
        periods = service.periods()
    except Exception as error:
        st.error(f"Could not open the portfolio workspace ({type(error).__name__}).")
        return
    if not service.borrowers:
        st.info("No borrowers are registered in the input catalog.")
        return
    date_col, cutoff_col = st.columns(2)
    selected_period = date_col.selectbox(
        "Reporting period",
        ["latest", *[value.isoformat() for value in reversed(periods)]],
        format_func=lambda value: "Latest available per borrower" if value == "latest" else value,
        key="portfolio_period",
    )
    cutoff = cutoff_col.date_input(
        "Information cutoff", periods[-1] if periods else date.today(), key="portfolio_cutoff"
    )
    period_end = None if selected_period == "latest" else date.fromisoformat(selected_period)
    if period_end and cutoff < period_end:
        st.error("Information cutoff must be on or after the reporting period.")
        return
    entries = service.snapshot(period_end=period_end, cutoff=cutoff)
    if period_end is None:
        st.caption(
            "Each row shows its actual latest source period at this cutoff. "
            "Borrowers can have different periods."
        )
    metrics = st.columns(4)
    metrics[0].metric("Borrowers", len(entries))
    metrics[1].metric("Assessed", sum(entry.assessment is not None for entry in entries))
    metrics[2].metric("Covenant breaches", sum("breach" in entry.statuses for entry in entries))
    metrics[3].metric("Assessments with data gaps", sum(entry.needs_data for entry in entries))
    search_col, status_col, sector_col = st.columns([2, 1, 1])
    search = (
        search_col.text_input(
            "Search borrowers", placeholder="Name or borrower ID", key="portfolio_search"
        )
        .strip()
        .casefold()
    )
    status = status_col.selectbox(
        "Compliance",
        ["All statuses", "Not assessed", *STATUS_LABELS.values()],
        key="portfolio_status_filter",
    )
    sector = sector_col.selectbox(
        "Sector",
        ["All sectors", *sorted({entry.sector for entry in entries})],
        key="portfolio_sector_filter",
    )
    filtered = [
        entry
        for entry in entries
        if (not search or search in entry.name.casefold() or search in entry.borrower_id.casefold())
        and (status == "All statuses" or status in entry.compliance.split(" / "))
        and (sector == "All sectors" or sector == entry.sector)
    ]
    st.subheader("Borrower directory")
    st.caption(
        f"{len(filtered)} of {len(entries)} borrowers "
        "· Click any cell to inspect that borrower's saved results."
    )
    if filtered:
        table_key = (
            f"portfolio_table_{st.session_state.get('portfolio_table_revision', 0)}_"
            + "_".join(entry.borrower_id for entry in filtered)
        )
        ids = tuple(entry.borrower_id for entry in filtered)
        event = st.dataframe(
            pd.DataFrame([entry_row(entry) for entry in filtered]),
            key=table_key,
            hide_index=True,
            width="stretch",
            row_height=43,
            selection_mode=["single-row", "single-cell"],
            on_select=lambda: selected_from_table(table_key, ids),
        )
        st.session_state.portfolio_table_selection = {
            "key": table_key,
            "rows": tuple(event.selection.rows),
            "cells": tuple(tuple(cell) for cell in event.selection.cells),
        }
    else:
        st.info("No borrowers match these filters.")
    names = {entry.borrower_id: entry.name for entry in entries}
    if st.session_state.get("portfolio_borrower") not in names:
        st.session_state.portfolio_borrower = (
            "SYN002" if "SYN002" in names else entries[0].borrower_id
        )
    selected_id = st.selectbox(
        "Select borrower",
        list(names),
        format_func=names.get,
        key="portfolio_borrower",
        on_change=change_borrower,
    )
    selected = next(entry for entry in entries if entry.borrower_id == selected_id)
    if st.button("Open borrower analysis", key="portfolio_open_analysis"):
        st.session_state._analysis_open_borrower = selected_id
        st.session_state.preview_selected_borrower = selected_id
        st.session_state.pop("analysis_period", None)
        st.session_state.pop("analysis_cutoff", None)
        st.session_state._preview_next_page = "Borrower analysis"
        st.rerun()
    credentials_available = bool(os.getenv("OPENAI_API_KEY", "").strip())
    if not credentials_available:
        st.session_state.portfolio_include_reviews = False
    include_reviews = st.checkbox(
        "Include agent reviews",
        key="portfolio_include_reviews",
        disabled=not credentials_available,
        help="Run bullish, bearish and recommendation agents, then generate follow-up questions.",
    )
    review_context = None
    review_settings_valid = True
    if not credentials_available:
        st.caption("Set OPENAI_API_KEY to include agent reviews. Calculations can run without it.")
    if include_reviews:
        st.caption(
            "Each assessed borrower gets a bull, bear and recommendation review. "
            "A further model call generates suggested questions. "
            "The settings below apply to every borrower in this request."
        )
        with st.expander("Agent review settings"):
            question = st.text_input(
                "Credit review question",
                DEFAULT_REVIEW_QUESTION,
                key="portfolio_batch_question",
            )
            criteria = st.text_area(
                "Credit criteria",
                DEFAULT_CRITERIA,
                key="portfolio_batch_criteria",
                height=130,
            )
            context = st.text_area(
                "Additional context / constraints",
                key="portfolio_batch_context",
            )
        review_settings_valid = bool(question.strip() and criteria.strip())
        if review_settings_valid:
            review_context = ExposureDecisionContext(
                question=question.strip(),
                credit_criteria=tuple(
                    line.strip() for line in criteria.splitlines() if line.strip()
                ),
                constraints=(context.strip(),) if context.strip() else (),
            )
        else:
            st.warning("Supply a review question and at least one credit criterion.")
    one, all_borrowers = st.columns(2)
    if one.button(
        "Run selected assessment",
        type="primary",
        width="stretch",
        disabled=not review_settings_valid,
    ):
        run_assessments(service, [selected_id], period_end, cutoff, review_context)
    if all_borrowers.button(
        "Assess all borrowers", width="stretch", disabled=not review_settings_valid
    ):
        run_assessments(service, list(names), period_end, cutoff, review_context)
    st.caption(
        "Actions use the chosen reporting dates. "
        "Search and filters do not change the all-borrower assessment scope."
    )
    if "portfolio_outcomes" in st.session_state:
        with st.expander("Last assessment run · outcomes"):
            st.dataframe(
                pd.DataFrame(st.session_state.portfolio_outcomes), hide_index=True, width="stretch"
            )
    render_selected(selected, service, credentials_available)
