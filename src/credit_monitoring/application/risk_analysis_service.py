"""Assemble assessment context without letting narrative output change compliance."""

from copy import deepcopy

from credit_monitoring.domain.assessment import RiskAssessment


def assessment_context(assessment: RiskAssessment) -> dict:
    """Include current metrics, bounded history, features, model metadata, and evidence."""
    features = assessment.trends
    if features is None and assessment.feature_snapshot is not None:
        features = assessment.feature_snapshot.features
    return deepcopy(
        {
            "borrower_id": assessment.borrower_id,
            "period_end": assessment.period_end.isoformat(),
            "information_cutoff": assessment.information_cutoff.isoformat(),
            "current_financials": [result.financial_inputs for result in assessment.results],
            "covenant_results": [result.model_dump(mode="json") for result in assessment.results],
            "historical_results": [result.model_dump(mode="json") for result in assessment.history],
            "risk_features": (features.model_dump(mode="json") if features is not None else None),
            "ml_prediction": assessment.prediction.model_dump(mode="json")
            if assessment.prediction
            else None,
            "ml_status": assessment.ml_status,
            "evidence": [evidence for result in assessment.results for evidence in result.evidence],
        }
    )


def format_assessment_summary(assessment: RiskAssessment) -> str:
    """Describe deterministic results and distinguish forecasts from observed outcomes."""
    statements = []
    for result in assessment.results:
        basis = result.financial_inputs.get("result_basis", "unavailable")
        value = "unavailable" if result.actual_value is None else f"{result.actual_value:.4f}"
        statements.append(
            f"{result.covenant_id}: {result.compliance_status}; {basis} actual {value}."
        )
    if assessment.ml_status == "stub":
        statements.append("The ML integration stub provides no forecast or risk probability.")
    elif assessment.ml_status == "complete":
        statements.append("Model outputs are predictions, not observed covenant outcomes.")
    elif assessment.ml_status in ("failed", "unavailable"):
        statements.append("ML output is unavailable; deterministic results remain available.")
    if assessment.prediction and assessment.prediction.model_name == "logistic_regression":
        statements.append(
            "This baseline was trained on simulated borrower histories; "
            "its evaluation measures performance on synthetic data."
        )
    return " ".join(statements) or "No covenant results are available."
