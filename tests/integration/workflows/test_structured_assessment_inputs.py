"""Use existing extraction contracts with mocked processing and real temporary SQLite."""

from datetime import date

import pytest

from credit_monitoring.application.assessment_service import AssessmentService
from credit_monitoring.config.settings import AssessmentSettings
from credit_monitoring.covenants.structured import ExtractionBinding, ExtractionCovenantReader
from credit_monitoring.domain import (
    CovenantExtraction,
    CovenantTerm,
    CovenantTestingEvent,
    ReportedFinancialValue,
    SourceEvidence,
    ThresholdScheduleEntry,
)
from credit_monitoring.domain.assessment import FinancialPeriod
from credit_monitoring.financials.repositories import FinancialRepository
from credit_monitoring.ingestion.loaders.financials import load_financials


@pytest.fixture
def stored_terms(document_service_factory, sdk_response):
    text = "# Synthetic agreement\n\nMaximum leverage 5.00x; reported actual 4.50x.\n"
    service = document_service_factory(text)
    citation = service.get_document_extraction("SYN").citation
    evidence = SourceEvidence(document_id="SYN", citation=citation, evidence_quote=text)
    extraction = CovenantExtraction(
        covenants=[
            CovenantTerm(
                covenant_name="Maximum leverage",
                covenant_type="leverage",
                metric="Leverage ratio",
                operator="<=",
                operator_quote="Maximum",
                threshold_direction="maximum",
                evidence=evidence,
                threshold_schedule=[
                    ThresholdScheduleEntry(
                        threshold="5.00 to 1.00",
                        period_end_dates=[date(2025, 9, 30)],
                        evidence=evidence,
                    )
                ],
            )
        ],
        reported_financial_values=[
            ReportedFinancialValue(
                metric_name="Leverage ratio",
                reported_value="4.50x",
                period_end=date(2025, 9, 30),
                evidence=evidence,
            )
        ],
    )
    service.client.responses.parse.return_value = sdk_response(extraction)
    service.process_document("SYN")
    reader = ExtractionCovenantReader(
        service,
        [
            ExtractionBinding(
                borrower_id="BORROWER",
                agreement_id="agreement-1",
                covenant_id="agreement-1:leverage",
                covenant_name="Maximum leverage",
                document_id="SYN",
            )
        ],
    )
    return service, reader, extraction


def test_existing_extraction_is_consumed_without_reprocessing(stored_terms, tmp_path):
    service, reader, _ = stored_terms
    financial_csv = tmp_path / "financials.csv"
    financial_csv.write_text("borrower_id,period_end,total_debt\nBORROWER,2025-09-30,\n")
    database = tmp_path / "financials.sqlite3"
    load_financials(financial_csv, database)
    assessment_service = AssessmentService(
        financial_repository=FinancialRepository(database),
        covenant_reader=reader,
        settings=AssessmentSettings(analytics_database=tmp_path / "analytics.sqlite3"),
    )
    period = date(2025, 9, 30)
    assessment = assessment_service.assess("BORROWER", period, period, ml_enabled=True)
    assert assessment.verification.is_valid
    assert assessment.results[0].actual_value == 4.5
    assert assessment.results[0].headroom == 0.5
    assert assessment.results[0].financial_inputs["result_basis"] == "reported"
    assert "reported actual" in assessment.narrative
    assert service.client.responses.parse.call_count == 1
    assert not reader.resolve(
        "SYN001", period, period, FinancialPeriod(borrower_id="SYN001", period_end=period)
    )


@pytest.mark.parametrize("condition", ["wrong_period", "stale", "future", "ambiguous", "bad_quote"])
def test_unresolved_document_inputs(stored_terms, condition, sdk_response):
    service, reader, extraction = stored_terms
    period = date(2025, 9, 30)
    if condition == "wrong_period":
        period = date(2025, 6, 30)
    elif condition == "stale":
        service.model = "different-model"
    elif condition == "future":
        binding = reader.bindings[0]
        reader.bindings = [
            ExtractionBinding(
                borrower_id=binding.borrower_id,
                agreement_id=binding.agreement_id,
                covenant_id=binding.covenant_id,
                covenant_name=binding.covenant_name,
                document_id=binding.document_id,
                available_at=date(2025, 10, 1),
            )
        ]
    elif condition == "ambiguous":
        reader.bindings.append(reader.bindings[0])
    elif condition == "bad_quote":
        extraction.covenants[0].evidence.evidence_quote = "Invented source quote"
        service.client.responses.parse.return_value = sdk_response(extraction)
        service.process_document("SYN", force=True)
    financials = FinancialPeriod(borrower_id="BORROWER", period_end=period)
    resolution = reader.resolve("BORROWER", period, period, financials)[0]
    assert resolution.covenant is None
    assert resolution.issues


def test_testing_event_preserves_waiver(stored_terms, sdk_response):
    service, reader, extraction = stored_terms
    period = date(2025, 9, 30)
    extraction.testing_events = [
        CovenantTestingEvent(
            covenant_name="Maximum leverage",
            event_type="waiver",
            period_end_dates=[period],
            evidence=extraction.covenants[0].evidence,
        )
    ]
    service.client.responses.parse.return_value = sdk_response(extraction)
    service.process_document("SYN", force=True)
    resolution = reader.resolve(
        "BORROWER", period, period, FinancialPeriod(borrower_id="BORROWER", period_end=period)
    )[0]
    assert resolution.covenant.testing_status == "waived"


def test_group_waiver_does_not_imply_active_compliance(stored_terms, sdk_response):
    service, reader, extraction = stored_terms
    period = date(2025, 9, 30)
    extraction.testing_events = [
        CovenantTestingEvent(
            covenant_name="All financial covenants",
            event_type="waiver",
            period_end_dates=[period],
            evidence=extraction.covenants[0].evidence,
        ),
    ]
    service.client.responses.parse.return_value = sdk_response(extraction)
    service.process_document("SYN", force=True)
    financials = FinancialPeriod(borrower_id="BORROWER", period_end=period)
    resolution = reader.resolve("BORROWER", period, period, financials)[0]
    assert resolution.covenant is None
    assert any("scope" in issue for issue in resolution.issues)
