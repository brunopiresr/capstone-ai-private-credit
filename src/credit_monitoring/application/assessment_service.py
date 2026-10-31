"""Quarterly assessments from existing structured terms and financial inputs."""

import logging
from datetime import date

from credit_monitoring.application.risk_analysis_service import (
    format_assessment_summary,
)
from credit_monitoring.calculations.covenants import calculate_covenant
from credit_monitoring.config.settings import AssessmentSettings
from credit_monitoring.covenants.structured import CovenantReader
from credit_monitoring.domain.analytics_base import new_identifier
from credit_monitoring.domain.assessment import FinancialPeriod, RiskAssessment
from credit_monitoring.domain.risk_features import BorrowerFeatureSnapshot
from credit_monitoring.domain.risk_prediction import RiskPrediction
from credit_monitoring.features.risk_feature_builder import build_risk_features
from credit_monitoring.financials.repositories import FinancialRepository
from credit_monitoring.ml.base import RiskModel
from credit_monitoring.ml.factory import create_risk_model
from credit_monitoring.observability import session_scope
from credit_monitoring.observability.configuration import span
from credit_monitoring.observability.logging import log_event, logging_context
from credit_monitoring.persistence.analytics_repositories import (
    CovenantResultRepository,
    RiskFeatureSnapshotRepository,
    RiskPredictionRepository,
)
from credit_monitoring.verification.verifier import verify_assessment

logger = logging.getLogger(__name__)


class AssessmentService:
    """Calculate and verify results, build trends, then invoke an optional risk model."""

    def __init__(
        self,
        *,
        financial_repository: FinancialRepository,
        covenant_reader: CovenantReader,
        settings: AssessmentSettings,
        result_repository: CovenantResultRepository,
        snapshot_repository: RiskFeatureSnapshotRepository,
        prediction_repository: RiskPredictionRepository,
        risk_model: RiskModel | None = None,
    ) -> None:
        self.financial_repository = financial_repository
        self.covenant_reader = covenant_reader
        self.settings = settings
        self.result_repository = result_repository
        self.snapshot_repository = snapshot_repository
        self.prediction_repository = prediction_repository
        self.risk_model = risk_model

    def assess(
        self,
        borrower_id: str,
        period_end: date,
        information_cutoff: date,
        *,
        ml_enabled: bool | None = None,
        financial_overrides: dict[str, float | None] | None = None,
        revision_reason: str = "",
        financial_snapshot: FinancialPeriod | None = None,
    ) -> RiskAssessment:
        """Assess existing inputs and backfill available history in a new immutable run.

        The cutoff bounds reporting periods and any known availability timestamps.
        Unknown source availability is reported explicitly, not inferred from load time.
        """
        if not borrower_id.strip() or information_cutoff < period_end:
            raise ValueError(
                "A borrower and a cutoff on or after the reporting period are required."
            )
        if financial_overrides is not None:
            if not financial_overrides or not revision_reason.strip():
                raise ValueError("Revised financial inputs require changes and a reason.")
            FinancialPeriod(
                borrower_id=borrower_id, period_end=period_end, metrics=financial_overrides
            )
        if financial_snapshot is not None:
            financial_snapshot = FinancialPeriod.model_validate(financial_snapshot.model_dump())
            if (financial_snapshot.borrower_id, financial_snapshot.period_end) != (
                borrower_id,
                period_end,
            ):
                raise ValueError("Saved financial inputs must match the requested borrower-period.")
        run_id = new_identifier()
        with (
            session_scope(),
            span("credit.assessment", borrower_id=borrower_id),
            logging_context(
                assessment_run_id=run_id,
                borrower_id=borrower_id,
                period_end=period_end,
                information_cutoff=information_cutoff,
            ),
        ):
            use_ml = self.settings.ml_enabled if ml_enabled is None else ml_enabled
            log_event(logger, "assessment", inputs={"ml_enabled": use_ml}, status="started")
            periods = {
                period.period_end: period
                for period in self.financial_repository.get_period_history(
                    borrower_id, as_of=period_end
                )
            }
            periods.setdefault(
                period_end, FinancialPeriod(borrower_id=borrower_id, period_end=period_end)
            )
            if financial_snapshot is not None:
                periods[period_end] = financial_snapshot
            if financial_overrides is not None:
                original = periods[period_end]
                if original.available_at and original.available_at > information_cutoff:
                    raise ValueError("Cannot revise financials unavailable at the selected cutoff.")
                periods[period_end] = FinancialPeriod.model_validate(
                    {
                        **original.model_dump(),
                        "metrics": {**original.metrics, **financial_overrides},
                        "source_file": f"Analyst revision: {revision_reason.strip()}",
                        "source_row": None,
                        "loaded_at": None,
                        "available_at": None,
                    }
                )
            results = []
            input_issues = []
            for reporting_date in sorted(periods):
                financials = periods[reporting_date]
                if (
                    financials.available_at is not None
                    and financials.available_at > information_cutoff
                ):
                    input_issues.append(
                        f"Financial inputs for {reporting_date} were unavailable at the cutoff."
                    )
                    log_event(
                        logger,
                        "financial_period",
                        status="rejected",
                        period_end=reporting_date,
                        inputs={"available_at": financials.available_at},
                        outputs={"reason": input_issues[-1]},
                    )
                    continue
                resolutions = self.covenant_reader.resolve(
                    borrower_id,
                    reporting_date,
                    information_cutoff,
                    financials,
                )
                for resolution in resolutions:
                    results.append(
                        calculate_covenant(
                            resolution,
                            financials,
                            assessment_run_id=run_id,
                            information_cutoff=information_cutoff,
                        )
                    )
            assessment = RiskAssessment(
                assessment_run_id=run_id,
                borrower_id=borrower_id,
                period_end=period_end,
                information_cutoff=information_cutoff,
                results=[result for result in results if result.period_end == period_end],
                history=[result for result in results if result.period_end < period_end],
                issues=input_issues,
            )
            if not assessment.results:
                assessment.issues.append(
                    "No mapped covenant inputs are available for this borrower-period."
                )
            assessment.verification = verify_assessment(assessment)
            if not assessment.verification.is_valid:
                assessment.issues.append("Structured verification failed; ML was not invoked.")
                assessment.ml_status = "unavailable" if use_ml else "disabled"
            else:
                self.result_repository.save_all(results)
                if assessment.results:
                    try:
                        assessment.trends = build_risk_features(
                            results,
                            borrower_id,
                            period_end,
                            information_cutoff,
                            assessment_run_id=run_id,
                        )
                    except Exception as error:
                        logger.error(
                            "Deterministic trends failed",
                            extra={"error_type": type(error).__name__},
                        )
                        assessment.issues.append(
                            f"Deterministic trends unavailable: {type(error).__name__}: {error}"
                        )
                        assessment.ml_status = "failed" if use_ml else "disabled"
                    else:
                        if use_ml:
                            self._run_ml(assessment)
                elif use_ml:
                    assessment.ml_status = "unavailable"
            assessment.narrative = format_assessment_summary(assessment)
            assessment.verification = verify_assessment(assessment)
            log_event(
                logger,
                "assessment",
                outputs={
                    "current_result_count": len(assessment.results),
                    "history_result_count": len(assessment.history),
                    "verification_valid": assessment.verification.is_valid,
                    "ml_status": assessment.ml_status,
                    "issue_count": len(assessment.issues),
                },
            )
            return assessment

    def _run_ml(self, assessment: RiskAssessment) -> None:
        snapshot_saved = False
        try:
            features = assessment.trends
            if features is None:
                raise ValueError("Deterministic features are unavailable.")
            snapshot = BorrowerFeatureSnapshot(
                assessment_run_id=assessment.assessment_run_id,
                features=features,
                source_result_ids=[
                    result.result_id
                    for result in sorted(
                        assessment.results + assessment.history,
                        key=lambda result: (result.period_end, result.covenant_id),
                    )
                ],
            )
            self.snapshot_repository.save(snapshot)
            snapshot_saved = True
            assessment.feature_snapshot = snapshot
            model = (
                self.risk_model
                if self.risk_model is not None
                else create_risk_model(self.settings.risk_model)
            )
            prediction = RiskPrediction.model_validate(
                model.predict(features.model_copy(deep=True))
            )
            if prediction.horizon_quarters != 1:
                raise ValueError("This workflow supports next-quarter predictions only.")
            if (
                prediction.borrower_id != assessment.borrower_id
                or prediction.period_end != assessment.period_end
            ):
                raise ValueError("Model returned a prediction for a different borrower-period.")
            if (
                prediction.snapshot_id is not None
                and prediction.snapshot_id != snapshot.snapshot_id
            ):
                raise ValueError("Model returned an unexpected feature-snapshot reference.")
            prediction.snapshot_id = snapshot.snapshot_id
            assessment.prediction = prediction
            verification = verify_assessment(assessment)
            if not verification.is_valid:
                assessment.prediction = None
                raise ValueError("Model output failed structured verification.")
            self.prediction_repository.save(prediction)
            assessment.ml_status = prediction.prediction_status
        except Exception as error:
            logger.error("Assessment prediction failed", extra={"error_type": type(error).__name__})
            assessment.prediction = None
            assessment.ml_status = "failed"
            message = f"ML unavailable: {type(error).__name__}: {error}"
            assessment.issues.append(message)
            if snapshot_saved:
                failure = RiskPrediction(
                    borrower_id=assessment.borrower_id,
                    period_end=assessment.period_end,
                    snapshot_id=assessment.feature_snapshot.snapshot_id,
                    model_name=self.settings.risk_model.type,
                    model_version=self.settings.risk_model.version,
                    prediction_status="failed",
                    error=message,
                )
                try:
                    self.prediction_repository.save(failure)
                    assessment.prediction = failure
                except Exception as storage_error:
                    logger.error(
                        "ML failure storage failed",
                        extra={"error_type": type(storage_error).__name__},
                    )
                    assessment.issues.append(f"ML failure record unavailable: {storage_error}")
