"""Quarterly assessments from existing structured terms and financial inputs."""

from datetime import date

from credit_monitoring.application.risk_analysis_service import (
    AssessmentNarrator,
    RiskAnalysisService,
)
from credit_monitoring.calculations.covenants import calculate_covenant
from credit_monitoring.config.settings import AssessmentSettings
from credit_monitoring.covenants.structured import CovenantReader
from credit_monitoring.domain.analytics_base import new_identifier
from credit_monitoring.domain.assessment import FinancialPeriod, RiskAssessment
from credit_monitoring.domain.risk_features import BorrowerFeatureSnapshot
from credit_monitoring.domain.risk_prediction import RiskPrediction
from credit_monitoring.features.risk_feature_builder import RiskFeatureBuilder
from credit_monitoring.financials.repositories import FinancialRepository
from credit_monitoring.ml.factory import RiskModelFactory
from credit_monitoring.persistence.analytics_repositories import (
    CovenantResultRepository,
    RiskFeatureSnapshotRepository,
    RiskPredictionRepository,
)
from credit_monitoring.verification.verifier import verify_assessment


class AssessmentService:
    """Persist calculations before invoking optional feature, model, and narrative services."""

    def __init__(
        self,
        *,
        financial_repository: FinancialRepository,
        covenant_reader: CovenantReader,
        settings: AssessmentSettings | None = None,
        model_factory: RiskModelFactory | None = None,
        narrator: AssessmentNarrator | None = None,
    ) -> None:
        self.financial_repository = financial_repository
        self.covenant_reader = covenant_reader
        self.settings = settings or AssessmentSettings()
        analytics_path = self.settings.analytics_database.expanduser().resolve()
        if analytics_path == financial_repository.database_path.expanduser().resolve():
            raise ValueError(
                "Analytics storage must be separate from the source financial database."
            )
        self.result_repository = CovenantResultRepository(analytics_path)
        self.snapshot_repository = RiskFeatureSnapshotRepository(analytics_path)
        self.prediction_repository = RiskPredictionRepository(analytics_path)
        self.feature_builder = RiskFeatureBuilder(self.result_repository)
        self.model_factory = model_factory or RiskModelFactory()
        self.risk_analysis_service = RiskAnalysisService(narrator)

    def assess(
        self,
        borrower_id: str,
        period_end: date,
        information_cutoff: date,
        *,
        ml_enabled: bool | None = None,
    ) -> RiskAssessment:
        """Assess existing inputs and backfill available history in a new immutable run.

        The cutoff bounds reporting periods and any known availability timestamps.
        Unknown source availability is reported explicitly, not inferred from load time.
        """
        if not borrower_id.strip() or information_cutoff < period_end:
            raise ValueError(
                "A borrower and a cutoff on or after the reporting period are required."
            )
        run_id = new_identifier()
        use_ml = self.settings.ml_enabled if ml_enabled is None else ml_enabled
        rows = self.financial_repository.get_history(borrower_id, as_of=period_end.isoformat())
        periods = {
            date.fromisoformat(row["period_end"]): FinancialPeriod.from_repository_row(row)
            for row in rows
        }
        periods.setdefault(
            period_end, FinancialPeriod(borrower_id=borrower_id, period_end=period_end)
        )
        results = []
        input_issues = []
        for reporting_date in sorted(periods):
            financials = periods[reporting_date]
            if financials.available_at is not None and financials.available_at > information_cutoff:
                input_issues.append(
                    f"Financial inputs for {reporting_date} were unavailable at the cutoff."
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
            if use_ml:
                if assessment.results:
                    self._run_ml(assessment)
                else:
                    assessment.ml_status = "unavailable"
        try:
            assessment.narrative = self.risk_analysis_service.analyze(assessment)
        except Exception as error:
            assessment.issues.append(f"Narrative unavailable: {type(error).__name__}: {error}")
        assessment.verification = verify_assessment(assessment)
        return assessment

    def _run_ml(self, assessment: RiskAssessment) -> None:
        snapshot_saved = False
        try:
            features = self.feature_builder.build(
                assessment.borrower_id,
                assessment.period_end,
                assessment.information_cutoff,
                assessment_run_id=assessment.assessment_run_id,
            )
            stored_history = self.result_repository.get_history(
                assessment.borrower_id,
                period_end=assessment.period_end,
                information_cutoff=assessment.information_cutoff,
                assessment_run_id=assessment.assessment_run_id,
            )
            snapshot = BorrowerFeatureSnapshot(
                assessment_run_id=assessment.assessment_run_id,
                features=features,
                source_result_ids=[result.result_id for result in stored_history],
            )
            self.snapshot_repository.save(snapshot)
            snapshot_saved = True
            assessment.feature_snapshot = snapshot
            model = self.model_factory.create(self.settings.risk_model)
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
                    assessment.issues.append(f"ML failure record unavailable: {storage_error}")
