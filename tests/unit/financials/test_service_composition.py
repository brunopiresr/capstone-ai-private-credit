"""Services can execute with supplied collaborators and no filesystem layout."""

from datetime import date
from types import SimpleNamespace

from credit_monitoring.application.assessment_service import AssessmentService
from credit_monitoring.application.document_processing_service import DocumentProcessingService
from credit_monitoring.config.settings import AssessmentSettings


def test_assessment_with_in_memory_collaborators_does_not_initialize_storage(tmp_path):
    saved = []
    service = AssessmentService(
        financial_repository=SimpleNamespace(get_period_history=lambda *a, **k: []),
        covenant_reader=SimpleNamespace(resolve=lambda *args: []),
        settings=AssessmentSettings(analytics_database=tmp_path / "unused.sqlite3"),
        result_repository=SimpleNamespace(save_all=saved.extend),
        snapshot_repository=object(),
        prediction_repository=object(),
    )
    result = service.assess("BORROWER", date(2025, 9, 30), date(2025, 9, 30))
    assert result.verification.is_valid and result.results == []
    assert result.trends is None and result.prediction is None
    assert result.issues == ["No mapped covenant inputs are available for this borrower-period."]
    assert list(tmp_path.iterdir()) == []


def test_document_service_constructor_does_not_initialize_storage(tmp_path):
    repository, search = object(), object()
    service = DocumentProcessingService(
        source_file=tmp_path / "catalog.csv",
        html_dir=tmp_path / "html",
        markdown_dir=tmp_path / "markdown",
        repository=repository,
        evidence_search=search,
    )
    assert service.repository is repository and service.evidence_search is search
    assert list(tmp_path.iterdir()) == []
