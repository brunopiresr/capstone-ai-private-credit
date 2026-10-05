"""Structured SEC fact extraction using the existing OpenAI Responses parse API."""

import json
from collections.abc import Iterable, Mapping
from typing import Any

from openai import APIError, APIResponseValidationError
from pydantic import ValidationError

from credit_monitoring.agents.prompts.assembly import build_prompt
from credit_monitoring.agents.prompts.batch import ALL_COMPANY_INSTRUCTIONS, BATCH_PROMPT_VERSION
from credit_monitoring.agents.prompts.extraction import (
    EXTRACTION_INSTRUCTIONS,
    EXTRACTION_PROMPT_VERSION,
)
from credit_monitoring.domain import (
    AllCompanyCovenantExtraction,
    AllCompanyExtractionResult,
    CompanyCovenantExtraction,
    CovenantExtraction,
    ExtractionResult,
    RetrievedRecord,
)

# POC: automatic post-extraction verification is temporarily disabled. Keep the
# validators and their tests; restore this import and the calls below to re-enable.
# from credit_monitoring.verification.extraction import validate_all_companies, validate_extraction


class ExtractionError(RuntimeError):
    """Base generation/input failure; verification failures instead live in the result report."""

    def __init__(self, message: str, *, response_id: str | None = None):
        super().__init__(message)
        self.response_id = response_id


class ExtractionInputError(ExtractionError):
    """Missing or malformed retrieval inputs; no model call was made."""


class ExtractionRefusalError(ExtractionError):
    """The SDK response contains refusal content."""


class ExtractionIncompleteError(ExtractionError):
    """Generation did not complete; no partial extraction is accepted."""


class ExtractionParseError(ExtractionError):
    """SDK JSON/Pydantic parsing failed, or completed output has no parsed object."""


class ExtractionResponseError(ExtractionError):
    """SDK/API request or response failed."""


def _records(values: Iterable[RetrievedRecord | Mapping[str, Any]]) -> list[RetrievedRecord]:
    try:
        records = [RetrievedRecord.from_record(value) for value in values]
    except (ValidationError, TypeError, KeyError) as exc:
        raise ExtractionInputError(f"Invalid retrieved-record contract: {exc}") from exc
    if any(not r.document_id.strip() or not r.citation.strip() for r in records):
        raise ExtractionInputError(
            "Retrieved records require nonempty source document IDs and citations."
        )
    return records


def _parse(*, client: Any, model: str, instructions: str, prompt: str, schema: type) -> Any:
    try:
        response = client.responses.parse(
            model=model,
            instructions=instructions,
            input=prompt,
            text_format=schema,
        )
    except (ValidationError, json.JSONDecodeError) as exc:
        raise ExtractionParseError(f"Structured extraction could not be parsed: {exc}") from exc
    except (APIResponseValidationError, APIError) as exc:
        raise ExtractionResponseError(f"Extraction SDK request/response failed: {exc}") from exc
    response_id = response.id
    for output in response.output:
        if output.type == "message":
            for content in output.content:
                if content.type == "refusal":
                    raise ExtractionRefusalError(content.refusal, response_id=response_id)
    if response.status == "incomplete":
        reason = (
            response.incomplete_details.reason if response.incomplete_details else "unspecified"
        )
        raise ExtractionIncompleteError(f"Incomplete generation: {reason}", response_id=response_id)
    if response.status != "completed" or response.error is not None:
        raise ExtractionResponseError(
            f"Extraction response status={response.status}; error={response.error}",
            response_id=response_id,
        )
    parsed = response.output_parsed
    if parsed is None or not isinstance(parsed, schema):
        raise ExtractionParseError(
            "No parsed extraction of the requested type.", response_id=response_id
        )
    return parsed


def extract_covenants(
    query: str,
    search_results: Iterable[RetrievedRecord | Mapping[str, Any]],
    *,
    client: Any,
    model: str = "gpt-4o-mini",
) -> ExtractionResult:
    """Extract facts unchanged; validation is null while POC verification is disabled."""
    records = _records(search_results)
    if not any(r.text.strip() for r in records):
        extraction = CovenantExtraction(gaps=["No relevant evidence was retrieved."])
    else:
        extraction = _parse(
            client=client,
            model=model,
            instructions=EXTRACTION_INSTRUCTIONS,
            prompt=build_prompt(query, records),
            schema=CovenantExtraction,
        )
    return ExtractionResult(
        prompt_version=EXTRACTION_PROMPT_VERSION,
        extraction=extraction,
        # POC: restore this call with the validator import when verification resumes.
        # validation=validate_extraction(extraction, records),
        validation=None,
    )


def extract_all_companies(
    query: str,
    documents: Iterable[RetrievedRecord | Mapping[str, Any]],
    *,
    company_by_ticker: Mapping[str, str],
    client: Any,
    model: str = "gpt-4o-mini",
) -> AllCompanyExtractionResult:
    """One request for all companies; automatic post-extraction verification is disabled."""
    records = _records(documents)
    if any(
        not isinstance(t, str) or not t.strip() or not isinstance(c, str) or not c.strip()
        for t, c in company_by_ticker.items()
    ):
        raise ExtractionInputError("Company catalog requires nonempty ticker/name strings.")
    if not company_by_ticker or not any(r.text.strip() for r in records):
        extraction = AllCompanyCovenantExtraction(
            summary="No indexed SEC evidence or company catalog is available.",
            companies=[
                CompanyCovenantExtraction(
                    company=company,
                    ticker=ticker,
                    extraction=CovenantExtraction(gaps=["No relevant evidence was retrieved."]),
                )
                for ticker, company in sorted(company_by_ticker.items())
            ],
            gaps=["No indexed SEC evidence or company catalog is available."],
        )
    else:
        payload = json.loads(build_prompt(query, records))
        payload["company_catalog"] = [
            {"company": company, "ticker": ticker}
            for ticker, company in sorted(company_by_ticker.items())
        ]
        extraction = _parse(
            client=client,
            model=model,
            instructions=ALL_COMPANY_INSTRUCTIONS,
            prompt=json.dumps(payload, ensure_ascii=False, indent=2),
            schema=AllCompanyCovenantExtraction,
        )
    # POC: retain this report-building block for restoring verification later.
    # report = validate_all_companies(extraction, records, company_by_ticker)
    # if not company_by_ticker:
    #     report.add(
    #         "warning", "no_company_catalog", "companies", "No company catalog was supplied."
    #     )
    return AllCompanyExtractionResult(
        prompt_version=f"{EXTRACTION_PROMPT_VERSION}+{BATCH_PROMPT_VERSION}",
        extraction=extraction,
        # validation=report,
        validation=None,
    )
