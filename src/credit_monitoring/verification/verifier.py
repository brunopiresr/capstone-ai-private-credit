"""Replay calculation inputs and check assessment provenance and model identity."""

from credit_monitoring.calculations.covenants import calculate_covenant
from credit_monitoring.domain.assessment import (
    CovenantResolution,
    FinancialPeriod,
    RiskAssessment,
)
from credit_monitoring.domain.validation import ValidationReport


def verify_assessment(assessment: RiskAssessment) -> ValidationReport:
    """Check structured results; this does not certify arbitrary narrative entailment."""
    report = ValidationReport()
    for index, result in enumerate(assessment.results + assessment.history):
        path = f"results[{index}]"
        if (
            result.borrower_id != assessment.borrower_id
            or result.assessment_run_id != assessment.assessment_run_id
            or result.period_end > assessment.period_end
            or result.information_cutoff > assessment.information_cutoff
        ):
            report.add(
                "error", "result_scope_mismatch", path, "Result is outside this assessment run."
            )
            continue
        financials = FinancialPeriod.model_validate(result.financial_inputs["financial_period"])
        covenant = result.resolved_covenant
        if financials.available_at is None or covenant is None or covenant.available_at is None:
            report.add(
                "warning",
                "information_availability_unknown",
                path,
                "Reporting dates do not establish when these inputs became available.",
            )
        if financials.available_at and financials.available_at > assessment.information_cutoff:
            report.add(
                "error", "future_financial_inputs", path, "Financial inputs exceed the cutoff."
            )
        if (
            covenant
            and covenant.available_at
            and covenant.available_at > assessment.information_cutoff
        ):
            report.add("error", "future_covenant_terms", path, "Covenant terms exceed the cutoff.")
        if covenant is None:
            if result.compliance_status != "unresolved":
                report.add(
                    "error",
                    "unresolved_compliance",
                    path,
                    "Unresolved terms cannot establish compliance.",
                )
            continue
        if not result.evidence:
            report.add(
                "error", "missing_provenance", path, "Resolved terms require source provenance."
            )
        if result.financial_inputs["result_basis"] == "reported" and not covenant.reported_evidence:
            report.add(
                "error",
                "missing_reported_evidence",
                path,
                "Reported ratios require their own evidence.",
            )
        replay = calculate_covenant(
            CovenantResolution(
                covenant_id=result.covenant_id,
                covenant_type=result.covenant_type,
                covenant=covenant,
            ),
            financials,
            assessment_run_id=result.assessment_run_id,
            information_cutoff=result.information_cutoff,
        )
        for field in ("actual_value", "threshold", "operator", "headroom", "compliance_status"):
            if getattr(replay, field) != getattr(result, field):
                report.add(
                    "error",
                    "calculation_mismatch",
                    f"{path}.{field}",
                    "Result differs from its stored calculation inputs.",
                )
    if assessment.prediction is not None:
        prediction = assessment.prediction
        snapshot = assessment.feature_snapshot
        if snapshot is None or (
            prediction.snapshot_id != snapshot.snapshot_id
            or prediction.borrower_id != assessment.borrower_id
            or prediction.period_end != assessment.period_end
        ):
            report.add(
                "error",
                "prediction_identity_mismatch",
                "prediction",
                "Prediction does not identify this assessment's feature snapshot.",
            )
        if prediction.prediction_status == "stub" and (
            prediction.risk_level != "unknown"
            or any(
                value is not None
                for value in (
                    prediction.breach_probability,
                    prediction.deterioration_probability,
                    prediction.anomaly_score,
                )
            )
        ):
            report.add("error", "stub_forecast", "prediction", "A stub cannot supply forecasts.")
    return report
