"""Project completed assessments into isolated evidence; never execute financial work."""

import json

from credit_monitoring.domain.assessment import FinancialPeriod, RiskAssessment
from credit_monitoring.domain.credit_review import EvidenceReference, ReviewSnapshot
from credit_monitoring.domain.financials import FINANCIAL_METRICS
from credit_monitoring.public_context.events import PublicNewsContext

_SOURCE_FIELDS = {
    "document_id",
    "citation",
    "evidence_quote",
    "source_file",
    "source_row",
    "source_start",
    "source_end",
    "markdown_path",
    "source_url",
    "available_at",
    "source_hash",
    "source_type",
}


def _sources(records: list[dict]) -> list[dict]:
    return [
        {key: value for key, value in record.items() if key in _SOURCE_FIELDS} for record in records
    ]


def _sanitize(assessment: RiskAssessment) -> dict:
    data = assessment.model_dump(mode="json", exclude={"narrative"})
    for result in data["results"] + data["history"]:
        raw = result["financial_inputs"].get("financial_period", {})
        financials = {
            key: value for key, value in raw.items() if key in FinancialPeriod.model_fields
        }
        financials["metrics"] = {
            key: value
            for key, value in financials.get("metrics", {}).items()
            if key in FINANCIAL_METRICS
        }
        result["financial_inputs"] = {
            "financial_period": financials,
            "result_basis": result["financial_inputs"].get("result_basis", "unavailable"),
        }
        result["evidence"] = _sources(result["evidence"])
        if covenant := result["resolved_covenant"]:
            covenant["evidence"] = _sources(covenant["evidence"])
            covenant["reported_evidence"] = _sources(covenant["reported_evidence"])
    return data


def _identity_errors(assessment: RiskAssessment) -> list[str]:
    """Check supplied identities and statuses without replaying calculation formulas."""
    errors = []
    if not assessment.borrower_id.strip() or assessment.information_cutoff < assessment.period_end:
        errors.append("Invalid assessment borrower or dates.")
    identifiers = set()
    for current, results in ((True, assessment.results), (False, assessment.history)):
        for result in results:
            financials = result.financial_inputs.get("financial_period", {})
            covenant = result.resolved_covenant
            if (
                result.result_id in identifiers
                or result.borrower_id != assessment.borrower_id
                or result.assessment_run_id != assessment.assessment_run_id
                or result.information_cutoff != assessment.information_cutoff
                or (current and result.period_end != assessment.period_end)
                or (not current and result.period_end >= assessment.period_end)
                or financials.get("borrower_id") != assessment.borrower_id
                or str(financials.get("period_end")) != result.period_end.isoformat()
                or (
                    covenant is not None
                    and (
                        covenant.borrower_id != assessment.borrower_id
                        or covenant.period_end != result.period_end
                    )
                )
            ):
                errors.append(
                    "Calculation inputs or identity are outside this borrower assessment."
                )
            identifiers.add(result.result_id)
    for features in (
        assessment.trends,
        assessment.feature_snapshot.features if assessment.feature_snapshot else None,
    ):
        if features is not None and (
            features.borrower_id != assessment.borrower_id
            or features.period_end != assessment.period_end
            or features.information_cutoff != assessment.information_cutoff
        ):
            errors.append("Trend or feature identity does not match the assessment.")
    snapshot, prediction = assessment.feature_snapshot, assessment.prediction
    if snapshot is not None and (
        snapshot.assessment_run_id != assessment.assessment_run_id
        or not set(snapshot.source_result_ids).issubset(identifiers)
    ):
        errors.append("Feature snapshot does not identify this assessment's results.")
    if prediction is not None:
        if (
            snapshot is None
            or prediction.snapshot_id != snapshot.snapshot_id
            or prediction.borrower_id != assessment.borrower_id
            or prediction.period_end != assessment.period_end
            or prediction.prediction_status != assessment.ml_status
        ):
            errors.append("Prediction identity or status does not match the assessment.")
        if prediction.prediction_status != "complete" and (
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
            errors.append("An unavailable or stub model cannot provide a forecast.")
    elif assessment.ml_status in ("complete", "stub"):
        errors.append("The reported ML status requires a prediction record.")
    if not assessment.verification.is_valid or any(
        issue.severity == "error" for issue in assessment.verification.issues
    ):
        errors.append("Structured assessment verification failed.")
    return list(dict.fromkeys(errors))


def build_review_snapshot(
    assessment: RiskAssessment, news: PublicNewsContext
) -> tuple[ReviewSnapshot, tuple[str, ...]]:
    """Own provenance and caveats; canonical strings keep nested inputs immutable."""
    errors = _identity_errors(assessment)
    data = _sanitize(assessment)
    references = [
        EvidenceReference(evidence_id="assessment", kind="assessment", path="/assessment")
    ]
    for collection in ("results", "history"):
        for index, result in enumerate(data[collection]):
            path = f"/assessment/{collection}/{index}"
            result_id = result["result_id"]
            references.extend(
                (
                    EvidenceReference(
                        evidence_id=f"result:{result_id}", kind="calculation", path=path
                    ),
                    EvidenceReference(
                        evidence_id=f"financial:{result_id}",
                        kind="financial",
                        path=f"{path}/financial_inputs/financial_period",
                    ),
                )
            )
            references.extend(
                EvidenceReference(
                    evidence_id=f"source:{result_id}:{i}",
                    kind="source",
                    path=f"{path}/evidence/{i}",
                )
                for i in range(len(result["evidence"]))
            )
    if assessment.trends is not None:
        references.append(
            EvidenceReference(evidence_id="trends", kind="trends", path="/assessment/trends")
        )
    if assessment.feature_snapshot is not None:
        references.append(
            EvidenceReference(
                evidence_id=f"features:{assessment.feature_snapshot.snapshot_id}",
                kind="features",
                path="/assessment/feature_snapshot",
            )
        )
    if assessment.prediction is not None:
        references.append(
            EvidenceReference(
                evidence_id=f"prediction:{assessment.prediction.prediction_id}",
                kind="prediction",
                path="/assessment/prediction",
            )
        )
    references.extend(
        EvidenceReference(evidence_id=f"news:{index}", kind="news", path=f"/news/items/{index}")
        for index in range(len(news.items))
    )
    limitations = [*assessment.issues, *news.issues]
    limitations.extend(issue.message for issue in assessment.verification.issues)
    if not assessment.results:
        limitations.append("No current covenant results are available.")
    if assessment.ml_status != "complete":
        limitations.append(f"ML status is {assessment.ml_status}; no usable model forecast exists.")
    if assessment.prediction and assessment.prediction.model_name == "logistic_regression":
        limitations.append(
            "The Logistic Regression model was trained and evaluated on synthetic "
            "histories, not real credit outcomes."
        )
    if news.status != "available":
        limitations.append(
            f"Public news status is {news.status}; this does not establish "
            "the absence of relevant public events."
        )
    return ReviewSnapshot(
        borrower_id=assessment.borrower_id,
        assessment_run_id=assessment.assessment_run_id,
        period_end=assessment.period_end,
        information_cutoff=assessment.information_cutoff,
        assessment_json=json.dumps(data, sort_keys=True, allow_nan=False),
        news=news,
        evidence=tuple(references),
        limitations=tuple(dict.fromkeys(limitations)),
    ), tuple(errors)
