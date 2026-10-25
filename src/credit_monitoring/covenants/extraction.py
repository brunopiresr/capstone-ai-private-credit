"""Structured SEC fact extraction through injected PydanticAI models."""

import json
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import ValidationError
from pydantic_ai import Agent, ToolOutput, capture_run_messages
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import Model

from credit_monitoring.agents.models import (
    DEFAULT_MODEL,
    ModelFailure,
    check_response,
    resolve_model,
)
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
from credit_monitoring.observability import session_scope
from credit_monitoring.observability.session import get_active_session

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
    """The model response contains refusal content."""


class ExtractionIncompleteError(ExtractionError):
    """Generation did not complete; no partial extraction is accepted."""


class ExtractionParseError(ExtractionError):
    """Structured output parsing failed, or completed output has no parsed object."""


class ExtractionResponseError(ExtractionError):
    """Model/API request or response failed."""


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


def _parse(*, model: Model | str, instructions: str, prompt: str, schema: type) -> Any:
    agent = Agent(
        resolve_model(model),
        name="Document extraction",
        instructions=instructions,
        output_type=ToolOutput(schema, strict=True),
        retries=0,
    )
    with capture_run_messages() as messages:
        try:
            session = get_active_session()
            result = agent.run_sync(prompt, conversation_id=session.session_id if session else None)
        except (ValidationError, UnexpectedModelBehavior, ModelAPIError) as exc:
            failure = exc
        else:
            failure = None
        response = next((m for m in reversed(messages) if isinstance(m, ModelResponse)), None)
        if response is not None:
            try:
                check_response(response)
            except ModelFailure as exc:
                error_type = {
                    "model_refusal": ExtractionRefusalError,
                    "model_incomplete": ExtractionIncompleteError,
                    "empty_response": ExtractionParseError,
                }.get(exc.code, ExtractionResponseError)
                raise error_type(str(exc), response_id=exc.response_id) from exc
        if failure is not None:
            error_type = (
                ExtractionResponseError
                if isinstance(failure, ModelAPIError)
                else ExtractionParseError
            )
            raise error_type(
                f"Structured extraction failed: {failure}",
                response_id=response.provider_response_id if response else None,
            ) from failure
    return result.output


def extract_covenants(
    query: str,
    search_results: Iterable[RetrievedRecord | Mapping[str, Any]],
    *,
    model: Model | str = DEFAULT_MODEL,
) -> ExtractionResult:
    """Extract facts unchanged; validation is null while POC verification is disabled."""
    with session_scope():
        records = _records(search_results)
        if not any(r.text.strip() for r in records):
            extraction = CovenantExtraction(gaps=["No relevant evidence was retrieved."])
        else:
            extraction = _parse(
                model=model,
                instructions=EXTRACTION_INSTRUCTIONS,
                prompt=build_prompt(query, records, include_catalog_notes=False),
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
    model: Model | str = DEFAULT_MODEL,
) -> AllCompanyExtractionResult:
    """One request for all companies; automatic post-extraction verification is disabled."""
    with session_scope():
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
            payload = json.loads(build_prompt(query, records, include_catalog_notes=False))
            payload["company_catalog"] = [
                {"company": company, "ticker": ticker}
                for ticker, company in sorted(company_by_ticker.items())
            ]
            extraction = _parse(
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
