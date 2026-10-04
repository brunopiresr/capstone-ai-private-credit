"""Offline pipeline integration; mocked outputs do not establish live model accuracy."""

import json
from datetime import date
from unittest.mock import Mock

import httpx
import pytest
from openai import APIError, OpenAI
from pydantic import ValidationError

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


def test_retrieval_to_installed_sdk_parse_to_validation_to_json(synthetic_records, evidence_for):
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
    captured = []

    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "resp_synthetic",
                "object": "response",
                "created_at": 0,
                "model": "gpt-4o-mini",
                "status": "completed",
                "error": None,
                "incomplete_details": None,
                "instructions": None,
                "metadata": {},
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
                "temperature": 1.0,
                "top_p": 1.0,
                "text": {"format": {"type": "text"}},
                "truncation": "disabled",
                "usage": None,
                "output": [
                    {
                        "id": "msg_synthetic",
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": expected.model_dump_json(),
                                "annotations": [],
                                "logprobs": [],
                            }
                        ],
                    }
                ],
            },
        )

    with OpenAI(
        api_key="synthetic-test-key",
        http_client=httpx.Client(
            transport=httpx.MockTransport(respond),
        ),
    ) as client:
        result = extract_covenants("Extract synthetic terms", results, client=client)
    assert result.validation.is_valid
    assert result.extraction == expected
    assert result.schema_version == "2"
    assert len(captured) == 1 and captured[0]["instructions"] == EXTRACTION_INSTRUCTIONS
    assert captured[0]["text"]["format"]["name"] == "CovenantExtraction"
    output = json.loads(result.model_dump_json())
    assert output["extraction"]["covenants"][0]["threshold_schedule"][0]["period_end_dates"] == [
        "2025-03-31",
        "2025-06-30",
    ]
    assert "validation" in output and "prompt_version" in output


def test_one_batch_request_and_nested_v2_results(synthetic_records, evidence_for, sdk_response):
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
    client = Mock()
    client.responses.parse.return_value = sdk_response(expected)
    result = extract_all_companies(
        "Extract all",
        [synthetic_records["base"]],
        client=client,
        company_by_ticker={"SYN": "Synthetic Issuer Inc.", "SPARSE": "Sparse Synthetic Issuer"},
    )
    client.responses.parse.assert_called_once()
    assert result.validation.is_valid and len(result.extraction.companies) == 2
    assert client.responses.parse.call_args.kwargs["instructions"] == ALL_COMPANY_INSTRUCTIONS
    assert client.responses.parse.call_args.kwargs["text_format"] is AllCompanyCovenantExtraction


def test_batch_coverage_and_cross_company_provenance_errors(
    synthetic_records,
    evidence_for,
    sdk_response,
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
    client = Mock()
    client.responses.parse.return_value = sdk_response(expected)
    result = extract_all_companies(
        "Extract",
        [synthetic_records["base"]],
        client=client,
        company_by_ticker={"SYN": "Synthetic Issuer Inc.", "OTHER": "Other Synthetic Issuer"},
    )
    codes = {issue.code for issue in result.validation.issues}
    assert {
        "duplicate_company",
        "missing_company",
        "unexpected_company",
        "source_pair_mismatch",
        "company_ticker_mismatch",
    } <= codes
    assert not result.validation.is_valid and result.extraction == expected


def test_empty_evidence_skips_single_and_batch_model_calls():
    client = Mock()
    single = extract_covenants("Extract", [], client=client)
    batch = extract_all_companies(
        "Extract", [], client=client, company_by_ticker={"SYN": "Synthetic Issuer Inc."}
    )
    client.responses.parse.assert_not_called()
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
def test_sdk_response_failure_types(status, refusal, error, synthetic_records, sdk_response):
    client = Mock()
    client.responses.parse.return_value = sdk_response(status=status, refusal=refusal)
    with pytest.raises(error) as info:
        extract_covenants("Extract", [synthetic_records["base"]], client=client)
    assert info.value.response_id == "resp_synthetic"


def test_sdk_pydantic_parse_failure_is_typed(synthetic_records):
    with pytest.raises(ValidationError) as invalid:
        CovenantExtraction.model_validate({"covenants": [{"operator": "approximately"}]})
    client = Mock()
    client.responses.parse.side_effect = invalid.value
    with pytest.raises(ExtractionParseError):
        extract_covenants("Extract", [synthetic_records["base"]], client=client)


def test_sdk_request_failure_is_typed(synthetic_records):
    client = Mock()
    client.responses.parse.side_effect = APIError(
        "Synthetic failure",
        request=httpx.Request("POST", "https://example.invalid"),
        body=None,
    )
    with pytest.raises(ExtractionResponseError):
        extract_covenants("Extract", [synthetic_records["base"]], client=client)


def test_missing_input_provenance_fails_before_model_call():
    client = Mock()
    with pytest.raises(ExtractionInputError):
        extract_covenants("Extract", [{"content": "synthetic covenant"}], client=client)
    client.responses.parse.assert_not_called()


def test_invalid_facts_are_returned_with_report(synthetic_records, evidence_for, sdk_response):
    expected = expected_extraction(synthetic_records["base"], evidence_for)
    expected.covenants[0].evidence.evidence_quote = "Invented quotation"
    client = Mock()
    client.responses.parse.return_value = sdk_response(expected)
    result = extract_covenants("Extract", [synthetic_records["base"]], client=client)
    assert not result.validation.is_valid and result.extraction == expected
