"""Explicit SQLite/service composition for CLI, notebook, UI, and test entry points."""

import csv
import shutil
from pathlib import Path
from typing import Any

from pydantic_ai.models import Model

from credit_monitoring.agents.credit_review import (
    BearishCreditAgent,
    BullishCreditAgent,
    CreditRecommendationAgent,
)
from credit_monitoring.agents.models import DEFAULT_MODEL
from credit_monitoring.application.assessment_service import AssessmentService
from credit_monitoring.application.credit_review_service import (
    CreditReviewService,
    ReviewEventHandler,
)
from credit_monitoring.application.document_processing_service import DocumentProcessingService
from credit_monitoring.application.portfolio_service import PortfolioService
from credit_monitoring.config.settings import AssessmentSettings, CreditReviewSettings
from credit_monitoring.covenants.repositories import CovenantRepository
from credit_monitoring.covenants.structured import CovenantReader, SyntheticCovenantReader
from credit_monitoring.financials.repositories import FinancialRepository
from credit_monitoring.ingestion.chunking.sections import DEFAULT_MAX_CHARS
from credit_monitoring.ml.base import RiskModel
from credit_monitoring.persistence.analytics_repositories import (
    CovenantResultRepository,
    RiskFeatureSnapshotRepository,
    RiskPredictionRepository,
    initialize_analytics,
)
from credit_monitoring.persistence.portfolio_repository import PortfolioRepository
from credit_monitoring.public_context.retrieval import PublicNewsProvider
from credit_monitoring.retrieval.lexical.local import LocalEvidenceSearch


def create_portfolio_service(
    *, data_root: Path, working_dir: Path, model: Model | str = DEFAULT_MODEL
) -> PortfolioService:
    """Seed once, retain working inputs, and reuse the established calculation/agent flows."""
    source = data_root / "app" / "synthetic"
    working_dir.mkdir(parents=True, exist_ok=True)
    financial_database = working_dir / "financials.sqlite3"
    if not financial_database.exists():
        shutil.copyfile(source / "financials.sqlite3", financial_database)
    financial_repository = FinancialRepository(financial_database)
    with (source / "synthetic_borrowers.csv").open(newline="", encoding="utf-8") as file:
        borrowers = [
            {key: row[key] for key in ("borrower_id", "borrower_name", "industry")}
            for row in csv.DictReader(file)
        ]
    assessment = create_assessment_service(
        financial_repository=financial_repository,
        covenant_reader=SyntheticCovenantReader(source / "synthetic_covenant_terms.csv"),
        settings=AssessmentSettings(analytics_database=working_dir / "analytics.sqlite3"),
    )
    return PortfolioService(
        borrowers=borrowers,
        financial_repository=financial_repository,
        assessment_service=assessment,
        review_service=create_credit_review_service(assessment_service=assessment, model=model),
        repository=PortfolioRepository(working_dir / "portfolio.sqlite3"),
    )


def create_credit_review_service(
    *,
    assessment_service: AssessmentService | None = None,
    model: Model | str = DEFAULT_MODEL,
    bullish_model: Model | str | None = None,
    bearish_model: Model | str | None = None,
    recommendation_model: Model | str | None = None,
    settings: CreditReviewSettings | None = None,
    news_provider: PublicNewsProvider | None = None,
    event_handler: ReviewEventHandler | None = None,
) -> CreditReviewService:
    """Compose independent roles; credentials are resolved only when review is requested."""
    return CreditReviewService(
        assessment_service=assessment_service,
        bullish_agent=BullishCreditAgent(model=bullish_model or model, settings=settings),
        bearish_agent=BearishCreditAgent(model=bearish_model or model, settings=settings),
        recommendation_agent=CreditRecommendationAgent(
            model=recommendation_model or model, settings=settings
        ),
        news_provider=news_provider,
        event_handler=event_handler,
    )


def create_assessment_service(
    *,
    financial_repository: FinancialRepository,
    covenant_reader: CovenantReader,
    settings: AssessmentSettings | None = None,
    risk_model: RiskModel | None = None,
) -> AssessmentService:
    settings = settings or AssessmentSettings()
    analytics_path = settings.analytics_database.expanduser().resolve()
    if analytics_path == financial_repository.database_path.expanduser().resolve():
        raise ValueError("Analytics storage must be separate from the source financial database.")
    initialize_analytics(analytics_path)
    results = CovenantResultRepository(analytics_path)
    return AssessmentService(
        financial_repository=financial_repository,
        covenant_reader=covenant_reader,
        settings=settings,
        result_repository=results,
        snapshot_repository=RiskFeatureSnapshotRepository(analytics_path),
        prediction_repository=RiskPredictionRepository(analytics_path),
        risk_model=risk_model,
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
