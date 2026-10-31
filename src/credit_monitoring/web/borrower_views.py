"""Borrower tables and overview, projected from saved assessment records."""

from html import escape

import pandas as pd
import streamlit as st

from credit_monitoring.application.borrower_workflow import BorrowerWorkflow, SavedFinancials
from credit_monitoring.application.portfolio_service import STATUS_LABELS
from credit_monitoring.domain.assessment import CovenantResult, RiskAssessment
from credit_monitoring.web.assessment import render_prediction, render_verification
from credit_monitoring.web.portfolio import formatted_time

FORMULAS = {
    "total_leverage": "Total leverage = contractual debt / covenant EBITDA",
    "net_leverage": "Net leverage = (contractual debt − eligible cash) / covenant EBITDA",
    "pro_forma_leverage": "Pro forma leverage = contractual debt / pro forma covenant EBITDA",
    "interest_coverage": "Interest coverage = covenant EBITDA / cash interest",
    "fixed_charge_coverage": (
        "Fixed-charge coverage = (covenant EBITDA − capex − cash taxes) / "
        "(cash interest + scheduled principal + rent)"
    ),
}


def name(result: CovenantResult) -> str:
    return (
        result.resolved_covenant.covenant_name if result.resolved_covenant else result.covenant_id
    )


def number(value: float | None, unit: str | None = "x") -> str:
    return "Unavailable" if value is None else f"{value:.2f}{unit or ''}"


def render_covenant_table(assessment: RiskAssessment, *, key: str) -> None:
    if not assessment.results:
        st.info("No mapped covenant results are available for this borrower and period.")
        return
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Covenant": name(result),
                    "Actual": result.actual_value,
                    "Threshold": (
                        f"{result.operator or ''} {number(result.threshold, result.unit)}".strip()
                    ),
                    "Headroom": result.headroom,
                    "Unit": result.unit,
                    "Compliance": STATUS_LABELS[result.compliance_status],
                }
                for result in assessment.results
            ]
        ),
        key=key,
        hide_index=True,
        width="stretch",
        row_height=43,
        column_config={
            "Actual": st.column_config.NumberColumn(format="%.2f"),
            "Headroom": st.column_config.NumberColumn(format="%.2f"),
        },
    )


def render_status(workflow: BorrowerWorkflow, assessment: RiskAssessment, *, version: int) -> None:
    statuses = sorted({r.compliance_status for r in assessment.results}) or ["incomplete"]
    chips = [
        (
            STATUS_LABELS[status],
            {
                "compliant": "green",
                "breach": "red",
                "incomplete": "amber",
                "unresolved": "amber",
                "unsupported": "amber",
            }.get(status, "grey"),
        )
        for status in statuses
    ]
    submitted = any(
        s["run_id"] == assessment.assessment_run_id
        for s in workflow.repository.submissions(assessment.borrower_id)
    )
    validation = workflow.validation(assessment.assessment_run_id)
    validation_label = (
        "Validated with exceptions"
        if validation and validation["payload"]["with_exceptions"]
        else "Validated"
        if validation
        else "Needs validation"
    )
    chips += [
        ("Submitted" if submitted else "Analyst draft", "grey"),
        (f"Assessment v{version}", "grey"),
        (validation_label, "green" if validation else "amber"),
    ]
    st.markdown(
        " ".join(
            f'<span class="preview-chip chip-{tone}">{escape(label)}</span>'
            for label, tone in chips
        ),
        unsafe_allow_html=True,
    )


def render_summary_metrics(assessment: RiskAssessment) -> None:
    leverage = next(
        (
            r
            for r in assessment.results
            if r.resolved_covenant
            and r.resolved_covenant.formula
            in {"net_leverage", "total_leverage", "pro_forma_leverage"}
        ),
        None,
    )
    coverage = next(
        (
            r
            for r in assessment.results
            if r.resolved_covenant and r.resolved_covenant.formula == "interest_coverage"
        ),
        None,
    )
    first, second, third = st.columns(3)
    first.metric(
        name(leverage) if leverage else "Leverage",
        number(leverage.actual_value, leverage.unit) if leverage else "Unavailable",
    )
    second.metric(
        "Leverage threshold",
        f"{leverage.operator or ''} {number(leverage.threshold, leverage.unit)}".strip()
        if leverage
        else "Unavailable",
    )
    third.metric(
        "Interest coverage",
        number(coverage.actual_value, coverage.unit) if coverage else "Unavailable",
    )


def render_saved_trend(assessment: RiskAssessment) -> None:
    current = next(
        (
            r
            for r in assessment.results
            if r.resolved_covenant
            and r.resolved_covenant.formula
            in {"net_leverage", "total_leverage", "pro_forma_leverage"}
        ),
        None,
    )
    if current is None:
        st.info("A comparable leverage trend is not available for this assessment.")
        return
    rows = []
    for result in sorted(assessment.history + assessment.results, key=lambda r: r.period_end):
        if result.covenant_id != current.covenant_id:
            continue
        comparable = (
            result.resolved_covenant is not None
            and result.resolved_covenant.basis_key == current.resolved_covenant.basis_key
            and result.compliance_status in {"compliant", "breach"}
        )
        rows.append(
            {
                "Period": str(result.period_end),
                name(current): result.actual_value if comparable else None,
            }
        )
    if sum(row[name(current)] is not None for row in rows) < 2:
        st.info("A comparable leverage trend is not available for this assessment.")
        return
    st.caption(
        f"{name(current)} · saved quarterly results; incompatible or unavailable values stay blank"
    )
    st.line_chart(pd.DataFrame(rows).set_index("Period"), height=210, color="#426c49")


def render_calculation_tables(assessment: RiskAssessment) -> None:
    st.subheader("Covenant calculations")
    st.caption(
        "Saved service results for the selected assessment version. Missing values stay blank."
    )
    render_covenant_table(assessment, key="analysis_covenant_calculations")
    left, right = st.columns([1.4, 1])
    with left, st.container(border=True):
        st.subheader("Input trace")
        periods = SavedFinancials(assessment).get_period_history(
            assessment.borrower_id, as_of=assessment.period_end
        )
        financials = next((p for p in periods if p.period_end == assessment.period_end), None)
        if financials:
            source = financials.source_file or "Source unavailable"
            if financials.source_row is not None:
                source += f" · row {financials.source_row}"
            st.caption(
                f"{financials.currency or 'Currency unspecified'} · "
                f"{financials.scale or 'Scale unspecified'} · "
                f"Available at: {financials.available_at or 'Unknown'}"
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Input": metric.replace("_", " ").title(),
                            "Value": value,
                            "Source": source,
                        }
                        for metric, value in financials.metrics.items()
                    ]
                ),
                key="analysis_input_trace",
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("Saved financial inputs are unavailable for this reporting period.")
        for result in assessment.results:
            covenant = result.resolved_covenant
            if covenant and covenant.formula in FORMULAS:
                st.code(FORMULAS[covenant.formula], language=None)
                st.caption(f"{name(result)} · {covenant.measurement_basis or 'Basis unspecified'}")
                adjustments = {
                    "Cash netting cap": covenant.cash_netting_cap,
                    "Addback cap fraction": covenant.addback_cap_fraction,
                    "Synergy cap fraction": covenant.synergy_cap_fraction,
                }
                for label, value in adjustments.items():
                    if value is not None:
                        st.caption(f"{label}: {value:g}")
    with right, st.container(border=True):
        st.subheader("Verification & exceptions")
        render_verification(assessment)
        for issue in assessment.issues:
            st.warning(issue)
        for result in assessment.results:
            for issue in result.issues:
                st.warning(f"{name(result)}: {issue}")
        st.markdown("**Contract basis**")
        for result in assessment.results:
            covenant = result.resolved_covenant
            st.caption(
                f"{name(result)} · "
                + (
                    f"{covenant.measurement_basis or 'Unspecified'} · {covenant.testing_status}"
                    if covenant
                    else "Terms unresolved"
                )
            )
    st.subheader("Applied terms and source records")
    if assessment.results:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Covenant": name(result),
                        "Formula": result.resolved_covenant.formula
                        if result.resolved_covenant
                        else None,
                        "Measurement basis": result.resolved_covenant.measurement_basis
                        if result.resolved_covenant
                        else None,
                        "Testing": result.resolved_covenant.testing_status
                        if result.resolved_covenant
                        else "unresolved",
                        "Result basis": result.financial_inputs.get("result_basis", "unavailable"),
                    }
                    for result in assessment.results
                ]
            ),
            key="analysis_applied_terms",
            hide_index=True,
            width="stretch",
        )
    with st.expander("Source evidence and complete calculation records"):
        for result in assessment.results:
            st.markdown(f"**{name(result)}**")
            st.json(result.model_dump(mode="json"), expanded=False)
    with st.expander("Period history and comparable trends"):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Period": str(r.period_end),
                        "Covenant": name(r),
                        "Actual": r.actual_value,
                        "Threshold": r.threshold,
                        "Headroom": r.headroom,
                        "Compliance": STATUS_LABELS[r.compliance_status],
                        "Unit": r.unit,
                        "Result basis": r.financial_inputs.get("result_basis", "unavailable"),
                        "Contractual basis": r.resolved_covenant.basis_key
                        if r.resolved_covenant
                        else None,
                    }
                    for r in sorted(
                        assessment.history + assessment.results, key=lambda r: r.period_end
                    )
                ]
            ),
            key="analysis_period_history",
            hide_index=True,
            width="stretch",
        )
        if assessment.trends:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Covenant": f.covenant_id,
                            "Actual change QoQ": f.metric_change_qoq,
                            "Headroom change QoQ": f.headroom_change_qoq,
                            "Threshold change QoQ": f.threshold_change_qoq,
                            "Basis changed": f.basis_changed,
                        }
                        for f in assessment.trends.covenants
                    ]
                ),
                key="analysis_comparable_trends",
                hide_index=True,
                width="stretch",
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Metric": metric.replace("_", " ").title(),
                            "Growth QoQ": getattr(assessment.trends, f"{metric}_growth_qoq"),
                            "Growth YoY": getattr(assessment.trends, f"{metric}_growth_yoy"),
                        }
                        for metric in ("reported_ebitda", "total_debt")
                    ]
                ),
                key="analysis_financial_growth",
                hide_index=True,
                width="stretch",
            )
        historical_inputs = SavedFinancials(assessment).get_period_history(
            assessment.borrower_id, as_of=assessment.period_end
        )
        if historical_inputs:
            st.markdown("**Financial input history**")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Period": str(period.period_end),
                            "Input": metric.replace("_", " ").title(),
                            "Value": value,
                            "Source": period.source_file,
                            "Source row": period.source_row,
                            "Currency": period.currency,
                            "Scale": period.scale,
                        }
                        for period in historical_inputs
                        for metric, value in period.metrics.items()
                    ]
                ),
                key="analysis_financial_history",
                hide_index=True,
                width="stretch",
            )
    with st.expander("Next-quarter forecast", expanded=True):
        render_prediction(assessment)


def render_history_table(workflow: BorrowerWorkflow, versions: list, selected: str) -> None:
    st.subheader("Assessment & review history")
    rows = []
    for index, (assessment, created) in enumerate(versions):
        run_id = assessment.assessment_run_id
        events = workflow.repository.events(run_id, "run")
        review = workflow.portfolio.repository.latest_review(run_id)
        rows.append(
            {
                "Version": f"Assessment v{len(versions) - index}",
                "State": "Selected" if run_id == selected else "Previous" if index else "Latest",
                "Period": str(assessment.period_end),
                "Compliance": " / ".join(
                    sorted({STATUS_LABELS[r.compliance_status] for r in assessment.results})
                )
                or "Incomplete",
                "Review": review.status.title() if review else "Not run",
                "Saved (Lisbon)": formatted_time(created),
                "Reason": events[0]["payload"].get("reason", "") if events else "",
            }
        )
    st.dataframe(
        pd.DataFrame(rows), key="analysis_version_history", hide_index=True, width="stretch"
    )
    st.caption("Choose Assessment version in Assessment settings to inspect a saved run.")
