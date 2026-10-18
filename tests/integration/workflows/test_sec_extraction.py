"""Offline pipeline integration; mocked outputs do not establish live model accuracy."""

import json
from datetime import date

import pytest
from model_helpers import ScriptedModel, model_response
from pydantic import ValidationError
from pydantic_ai.exceptions import ModelAPIError

from credit_monitoring.agents.prompts.batch import ALL_COMPANY_INSTRUCTIONS
from credit_monitoring.agents.prompts.extraction import EXTRACTION_INSTRUCTIONS
from credit_monitoring.covenants.extraction import (
    ExtractionIncompleteError,
    ExtractionInputError,
    ExtractionParseError,
    ExtractionRefusalError,
    ExtractionResponseError,
    extract_all_companies,
    extract_covenants,
)
from credit_monitoring.domain import (
    AllCompanyCovenantExtraction,
    CompanyCovenantExtraction,
    CovenantExtraction,
    CovenantTerm,
    ThresholdScheduleEntry,
)
from credit_monitoring.ingestion.chunking.evidence import prepare_documents
from credit_monitoring.retrieval.lexical.sec import build_index, search
from credit_monitoring.verification.extraction import validate_all_companies, validate_extraction


def expected_extraction(record, evidence_for):
    evidence = evidence_for(record)
    return CovenantExtraction(
        issuer="Synthetic Issuer Inc.",
        ticker="SYN",
        covenants=[
            CovenantTerm(
                covenant_name="Maximum Total Leverage Ratio",
                covenant_type="leverage",
                operator="<=",
                operator_quote="not exceeding",
                threshold_direction="maximum",
                evidence=evidence,
                threshold_schedule=[
                    ThresholdScheduleEntry(
                        threshold="5.00 to 1.00",
                        period_end_dates=[date(2025, 3, 31), date(2025, 6, 30)],
                        evidence=evidence,
                    )
                ],
            )
        ],
    )


def test_retrieval_to_pydantic_model_to_unverified_json(synthetic_records, evidence_for):
    record = {
        **synthetic_records["base"],
        "document_type": "Synthetic agreement",
        "role": "synthetic_fixture",
        "notes": "Synthetic catalog context only",
        "period_end": "2025-06-30",
    }
    documents = prepare_documents([record])
    results = search(
        "Total Leverage Ratio",
        index=build_index(documents),
        document_count=len(documents),
        ticker="SYN",
    )
    assert len(results) == 1
    expected = expected_extraction(record, evidence_for)
    model = ScriptedModel(response=model_response(extraction=expected))
    result = extract_covenants("Extract synthetic terms", results, model=model)
    assert result.validation is None
    assert result.extraction == expected
    assert result.schema_version == "2.1"
    model.respond.assert_called_once()
    request = model.respond.call_args.kwargs
    assert request["info"].instructions == EXTRACTION_INSTRUCTIONS.strip()
    assert request["info"].output_tools[0].parameters_json_schema["title"] == "CovenantExtraction"
    payload = json.loads(request["messages"][0].parts[0].content)
    envelope = payload["retrieved_records"][0]
    assert "notes" not in envelope["catalog_context"]
    assert envelope["text"] == record["content"]
    assert envelope["citation"] == record["citation"]
    assert record["notes"] == "Synthetic catalog context only"
    output = json.loads(result.model_dump_json())
    assert output["extraction"]["covenants"][0]["threshold_schedule"][0]["period_end_dates"] == [
        "2025-03-31",
        "2025-06-30",
    ]
    assert "validation" in output and "prompt_version" in output


def test_one_batch_request_and_nested_v2_results(
    synthetic_records, evidence_for, generation_response
):
    expected = AllCompanyCovenantExtraction(
        summary="Synthetic evidence summary",
        companies=[
            CompanyCovenantExtraction(
                company="Synthetic Issuer Inc.",
                ticker="SYN",
                extraction=expected_extraction(synthetic_records["base"], evidence_for),
            ),
            CompanyCovenantExtraction(
                company="Sparse Synthetic Issuer",
                ticker="SPARSE",
                extraction=CovenantExtraction(
                    ticker="SPARSE", gaps=["No supplied excerpts for SPARSE."]
                ),
            ),
        ],
    )
    model = ScriptedModel()
    model.respond.return_value = generation_response(expected)
    record = {**synthetic_records["base"], "notes": "Catalog-only claimed threshold 99x"}
    result = extract_all_companies(
        "Extract all",
        [record],
        model=model,
        company_by_ticker={"SYN": "Synthetic Issuer Inc.", "SPARSE": "Sparse Synthetic Issuer"},
    )
    model.respond.assert_called_once()
    assert result.validation is None and len(result.extraction.companies) == 2
    assert model.respond.call_args.kwargs["info"].instructions == ALL_COMPANY_INSTRUCTIONS.strip()
    payload = json.loads(model.respond.call_args.kwargs["messages"][0].parts[0].content)
    envelope = payload["retrieved_records"][0]
    assert "notes" not in envelope["catalog_context"]
    assert envelope["text"] == record["content"]
    assert record["notes"] == "Catalog-only claimed threshold 99x"
    assert (
        model.respond.call_args.kwargs["info"].output_tools[0].parameters_json_schema["title"]
        == "AllCompanyCovenantExtraction"
    )


def test_batch_coverage_and_cross_company_provenance_errors(
    synthetic_records,
    evidence_for,
    generation_response,
):
    expected = AllCompanyCovenantExtraction(
        summary="Synthetic fixture",
        companies=[
            CompanyCovenantExtraction(
                company="Other Synthetic Issuer",
                ticker="OTHER",
                extraction=expected_extraction(synthetic_records["base"], evidence_for),
            ),
            CompanyCovenantExtraction(
                company="Other Synthetic Issuer", ticker="OTHER", extraction=CovenantExtraction()
            ),
            CompanyCovenantExtraction(
                company="Unknown", ticker="UNKNOWN", extraction=CovenantExtraction()
            ),
        ],
    )
    model = ScriptedModel()
    model.respond.return_value = generation_response(expected)
    result = extract_all_companies(
        "Extract",
        [synthetic_records["base"]],
        model=model,
        company_by_ticker={"SYN": "Synthetic Issuer Inc.", "OTHER": "Other Synthetic Issuer"},
    )
    assert result.validation is None
    # The retained verifier can still be explicitly invoked outside extraction.
    report = validate_all_companies(
        result.extraction,
        [synthetic_records["base"]],
        {"SYN": "Synthetic Issuer Inc.", "OTHER": "Other Synthetic Issuer"},
    )
    codes = {issue.code for issue in report.issues}
    assert {
        "duplicate_company",
        "missing_company",
        "unexpected_company",
        "source_pair_mismatch",
        "company_ticker_mismatch",
    } <= codes
    assert not report.is_valid and result.extraction == expected


def test_empty_evidence_skips_single_and_batch_model_calls():
    model = ScriptedModel()
    single = extract_covenants("Extract", [], model=model)
    batch = extract_all_companies(
        "Extract", [], model=model, company_by_ticker={"SYN": "Synthetic Issuer Inc."}
    )
    model.respond.assert_not_called()
    assert single.extraction.gaps and batch.extraction.companies[0].extraction.gaps
    assert batch.extraction.companies[0].ticker == "SYN"


@pytest.mark.parametrize(
    "status,refusal,error",
    [
        ("completed", "Synthetic refusal", ExtractionRefusalError),
        ("incomplete", None, ExtractionIncompleteError),
        ("completed", None, ExtractionParseError),
        ("failed", None, ExtractionResponseError),
    ],
)
def test_generation_response_failure_types(
    status, refusal, error, synthetic_records, generation_response
):
    model = ScriptedModel()
    model.respond.return_value = generation_response(status=status, refusal=refusal)
    with pytest.raises(error) as info:
        extract_covenants("Extract", [synthetic_records["base"]], model=model)
    assert info.value.response_id == "resp_synthetic"


def test_model_pydantic_parse_failure_is_typed(synthetic_records):
    with pytest.raises(ValidationError) as invalid:
        CovenantExtraction.model_validate({"covenants": [{"operator": "approximately"}]})
    model = ScriptedModel()
    model.respond.side_effect = invalid.value
    with pytest.raises(ExtractionParseError):
        extract_covenants("Extract", [synthetic_records["base"]], model=model)


def test_model_request_failure_is_typed(synthetic_records):
    model = ScriptedModel()
    model.respond.side_effect = ModelAPIError(model_name="synthetic", message="Synthetic failure")
    with pytest.raises(ExtractionResponseError):
        extract_covenants("Extract", [synthetic_records["base"]], model=model)


def test_missing_input_provenance_fails_before_model_call():
    model = ScriptedModel()
    with pytest.raises(ExtractionInputError):
        extract_covenants("Extract", [{"content": "synthetic covenant"}], model=model)
    model.respond.assert_not_called()


def test_invalid_facts_are_returned_unverified(
    synthetic_records, evidence_for, generation_response
):
    expected = expected_extraction(synthetic_records["base"], evidence_for)
    expected.covenants[0].evidence.evidence_quote = "Invented quotation"
    model = ScriptedModel()
    model.respond.return_value = generation_response(expected)
    result = extract_covenants("Extract", [synthetic_records["base"]], model=model)
    assert result.validation is None and result.extraction == expected
    assert not validate_extraction(result.extraction, [synthetic_records["base"]]).is_valid
