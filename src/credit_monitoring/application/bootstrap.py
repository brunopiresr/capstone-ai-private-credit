"""Explicit SQLite/service composition for CLI, notebook, UI, and test entry points."""

from pathlib import Path
from typing import Any

from pydantic_ai.models import Model

from credit_monitoring.agents.models import DEFAULT_MODEL
from credit_monitoring.application.assessment_service import AssessmentService
from credit_monitoring.application.document_processing_service import DocumentProcessingService
from credit_monitoring.application.risk_analysis_service import (
    AssessmentNarrator,
    RiskAnalysisService,
)
from credit_monitoring.config.settings import AssessmentSettings
from credit_monitoring.covenants.repositories import CovenantRepository
from credit_monitoring.covenants.structured import CovenantReader
from credit_monitoring.features.risk_feature_builder import RiskFeatureBuilder
from credit_monitoring.financials.repositories import FinancialRepository
from credit_monitoring.ingestion.chunking.sections import DEFAULT_MAX_CHARS
from credit_monitoring.ml.factory import RiskModelFactory
from credit_monitoring.persistence.analytics_repositories import (
    CovenantResultRepository,
    RiskFeatureSnapshotRepository,
    RiskPredictionRepository,
)
from credit_monitoring.retrieval.lexical.local import LocalEvidenceSearch


def create_assessment_service(
    *,
    financial_repository: FinancialRepository,
    covenant_reader: CovenantReader,
    settings: AssessmentSettings | None = None,
    model_factory: RiskModelFactory | None = None,
    narrator: AssessmentNarrator | None = None,
) -> AssessmentService:
    settings = settings or AssessmentSettings()
    analytics_path = settings.analytics_database.expanduser().resolve()
    if analytics_path == financial_repository.database_path.expanduser().resolve():
        raise ValueError("Analytics storage must be separate from the source financial database.")
    results = CovenantResultRepository(analytics_path)
    return AssessmentService(
        financial_repository=financial_repository,
        covenant_reader=covenant_reader,
        settings=settings,
        result_repository=results,
        snapshot_repository=RiskFeatureSnapshotRepository(analytics_path),
        prediction_repository=RiskPredictionRepository(analytics_path),
        feature_builder=RiskFeatureBuilder(results),
        model_factory=model_factory or RiskModelFactory(),
        risk_analysis_service=RiskAnalysisService(narrator),
    )


def create_document_service(
    *,
    source_file: Path,
    html_dir: Path,
    markdown_dir: Path,
    database_path: Path,
    model: Model | str = DEFAULT_MODEL,
    user_agent: str = "",
    converter: Any = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> DocumentProcessingService:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive.")
    return DocumentProcessingService(
        source_file=source_file,
        html_dir=html_dir,
        markdown_dir=markdown_dir,
        repository=CovenantRepository(database_path),
        evidence_search=LocalEvidenceSearch(),
        model=model,
        user_agent=user_agent,
        converter=converter,
        max_chars=max_chars,
    )
