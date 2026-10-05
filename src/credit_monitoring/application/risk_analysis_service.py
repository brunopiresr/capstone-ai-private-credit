"""Assemble assessment context without letting narrative output change compliance."""

from copy import deepcopy
from typing import Protocol

from credit_monitoring.domain.assessment import RiskAssessment


class AssessmentNarrator(Protocol):
    """An optional narrative boundary receiving only the structured assessment context."""

    def summarize(self, context: dict) -> str:
        """Describe supplied results, distinguishing predictions from observed facts."""
        ...


def assessment_context(assessment: RiskAssessment) -> dict:
    """Include current metrics, bounded history, features, model metadata, and evidence."""
    return deepcopy(
        {
            "borrower_id": assessment.borrower_id,
            "period_end": assessment.period_end.isoformat(),
            "information_cutoff": assessment.information_cutoff.isoformat(),
            "current_financials": [result.financial_inputs for result in assessment.results],
            "covenant_results": [result.model_dump(mode="json") for result in assessment.results],
            "historical_results": [result.model_dump(mode="json") for result in assessment.history],
            "risk_features": (
                assessment.feature_snapshot.features.model_dump(mode="json")
                if assessment.feature_snapshot
                else None
            ),
            "ml_prediction": assessment.prediction.model_dump(mode="json")
            if assessment.prediction
            else None,
            "ml_status": assessment.ml_status,
            "evidence": [evidence for result in assessment.results for evidence in result.evidence],
        }
    )


class RiskAnalysisService:
    """Produce a structured-context narrative, with a deterministic default."""

    def __init__(self, narrator: AssessmentNarrator | None = None) -> None:
        self.narrator = narrator

    def analyze(self, assessment: RiskAssessment) -> str:
        """Keep optional prose separate from the authoritative typed results."""
        if self.narrator is not None:
            narrative = self.narrator.summarize(assessment_context(assessment))
            if not isinstance(narrative, str) or not narrative.strip():
                raise ValueError("The narrator must return nonempty text.")
            return narrative
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
