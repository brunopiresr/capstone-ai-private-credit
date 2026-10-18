"""Render authoritative assessment records and completed agent outputs."""

import pandas as pd
import streamlit as st

from credit_monitoring.domain.agent import AgentAnswer
from credit_monitoring.domain.assessment import FinancialPeriod, RiskAssessment


def _fmt(value: float | None, unit: str | None) -> str:
    return "Unavailable" if value is None else f"{value:.2f}{unit or ''}"


def render_results(assessment: RiskAssessment) -> None:
    st.caption(
        f"Borrower {assessment.borrower_id} · Reporting period {assessment.period_end} · "
        f"Information cutoff {assessment.information_cutoff}"
    )
    st.caption(f"Assessment run: {assessment.assessment_run_id}")
    if not assessment.results:
        st.info("No mapped covenant results are available for this borrower and period.")
    for result in assessment.results:
        covenant = result.resolved_covenant
        st.subheader(covenant.covenant_name if covenant else result.covenant_id)
        st.markdown(f"**Status: {result.compliance_status.replace('_', ' ')}**")
        actual, threshold, headroom = st.columns(3)
        actual.metric("Actual", _fmt(result.actual_value, result.unit))
        threshold.metric(
            "Threshold",
            f"{result.operator or ''} {_fmt(result.threshold, result.unit)}".strip(),
        )
        headroom.metric("Headroom", _fmt(result.headroom, result.unit))
        st.caption(
            f"Basis: {result.financial_inputs.get('result_basis', 'unavailable')} · "
            f"Covenant: {result.covenant_id} · Result: {result.result_id}"
        )
        for issue in result.issues:
            st.warning(issue)
        history = [
            item
            for item in assessment.history + assessment.results
            if item.covenant_id == result.covenant_id
        ]
        st.markdown("**Period history**")
        st.caption(
            "Stored service results. Missing values and changes in calculation basis "
            "remain explicit."
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Period": item.period_end.isoformat(),
                        "Status": item.compliance_status,
                        "Actual": item.actual_value,
                        "Threshold": item.threshold,
                        "Headroom": item.headroom,
                        "Unit": item.unit,
                        "Basis": item.financial_inputs.get("result_basis", "unavailable"),
                        "Formula": item.resolved_covenant.formula
                        if item.resolved_covenant
                        else None,
                        "Contractual basis": (
                            item.resolved_covenant.basis_key if item.resolved_covenant else None
                        ),
                    }
                    for item in sorted(history, key=lambda item: item.period_end)
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    if assessment.trends is not None:
        st.markdown("**Deterministic trends**")
        st.caption("Changes use the exact comparable prior period. Unavailable changes stay blank.")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Covenant": item.covenant_id,
                        "Actual change QoQ": item.metric_change_qoq,
                        "Headroom change QoQ": item.headroom_change_qoq,
                        "Threshold change QoQ": item.threshold_change_qoq,
                        "Basis changed": item.basis_changed,
                    }
                    for item in assessment.trends.covenants
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Metric": metric.replace("_", " "),
                        "Growth QoQ": getattr(assessment.trends, f"{metric}_growth_qoq"),
                        "Growth YoY": getattr(assessment.trends, f"{metric}_growth_yoy"),
                    }
                    for metric in ("reported_ebitda", "total_debt")
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    if assessment.narrative:
        st.markdown("**Service summary**")
        st.write(assessment.narrative)
    for issue in assessment.issues:
        st.warning(issue)


def render_verification(assessment: RiskAssessment) -> None:
    st.subheader("Structured verification")
    report = assessment.verification
    if report.is_valid:
        if report.issues:
            st.warning("Structured verification passed with warnings.")
        else:
            st.success("Structured verification passed.")
    else:
        st.error("Structured verification failed. Review the issues before using these results.")
    st.caption("Verification covers structured results; it does not verify generated prose.")
    for issue in report.issues:
        render = st.error if issue.severity == "error" else st.warning
        render(f"{issue.code}: {issue.message} ({issue.path})")


def render_prediction(assessment: RiskAssessment) -> None:
    st.subheader("Next-quarter forecast")
    prediction = assessment.prediction
    st.write(f"Prediction status: {assessment.ml_status}")
    if assessment.ml_status == "disabled":
        st.info(
            "Prediction is off. Select a prediction mode and run another assessment to enable it."
        )
    elif assessment.ml_status == "stub":
        st.info("The stub exercises the model interface and supplies no forecast probability.")
    elif assessment.ml_status in {"failed", "unavailable"}:
        st.warning("Forecast unavailable. The deterministic covenant results remain visible.")
        if prediction and prediction.error:
            st.error(prediction.error)
    elif prediction:
        probability = prediction.breach_probability
        st.metric(
            "Next-quarter breach probability",
            "Unavailable" if probability is None else f"{probability:.1%}",
        )
        st.caption("A forecast probability describes a future outcome, not current compliance.")
    if prediction:
        st.caption(
            f"Model: {prediction.model_name} {prediction.model_version} · "
            f"Horizon: {prediction.horizon_quarters} quarter(s) · "
            f"Target: {prediction.prediction_target}"
        )
        st.caption(f"Prediction: {prediction.prediction_id} · Snapshot: {prediction.snapshot_id}")
        if prediction.model_name == "logistic_regression":
            st.info("This baseline was trained and evaluated on synthetic borrower histories.")
        if prediction.model_artifact_hash:
            st.caption(f"Model artifact: {prediction.model_artifact_hash}")


def render_evidence(assessment: RiskAssessment) -> None:
    st.subheader("Financial inputs and provenance")
    periods = {}
    for result in assessment.history + assessment.results:
        financials = FinancialPeriod.model_validate(result.financial_inputs["financial_period"])
        periods[financials.period_end] = financials
    for period, financials in sorted(periods.items(), reverse=True):
        with st.expander(f"Financial inputs · {period}", expanded=period == assessment.period_end):
            st.caption(f"Source: {financials.source_file} · Row: {financials.source_row}")
            st.caption(
                f"Available at: {financials.available_at or 'Unknown'} · "
                f"Currency: {financials.currency or 'Unspecified'} · "
                f"Scale: {financials.scale or 'Unspecified'}"
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Metric": name,
                            "Value": value,
                            "Availability": ("Missing" if value is None else "Provided"),
                        }
                        for name, value in financials.metrics.items()
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
    st.subheader("Applied terms and source records")
    for result in assessment.history + assessment.results:
        with st.expander(f"{result.covenant_id} · {result.period_end}"):
            st.caption(f"Result: {result.result_id}")
            if result.resolved_covenant:
                st.json(result.resolved_covenant.model_dump(mode="json"))
            st.json(result.evidence)


def render_answer(answer: AgentAnswer) -> None:
    if not answer.complete:
        st.error(f"Assistant could not complete the response: {answer.error or 'unknown error'}")
    else:
        st.markdown(answer.answer)
        st.caption(f"Evidence confidence: {answer.confidence} · {answer.confidence_explanation}")
    if answer.sources:
        with st.expander("Sources"):
            for source in answer.sources:
                st.write(f"{source.document_id}: {source.citation}")
    if answer.tool_trace:
        with st.expander("Executed tools and supporting results"):
            for execution in answer.tool_trace:
                st.write(execution.name)
                st.json(execution.model_dump(mode="json"))
