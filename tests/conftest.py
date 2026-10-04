"""Shared controlled extraction fixtures; no credentials, network, or real SEC claims."""

import json
from pathlib import Path

import pytest
from openai.types.responses import (
    ParsedResponse,
    ParsedResponseOutputMessage,
    ParsedResponseOutputText,
    ResponseOutputRefusal,
)
from openai.types.responses.response import IncompleteDetails

from credit_monitoring.domain import SourceEvidence


@pytest.fixture
def synthetic_records():
    path = Path(__file__).parent / "fixtures/sec_covenant_v2/records.json"
    return json.loads(path.read_text())["records"]


@pytest.fixture
def evidence_for():
    def build(record, quote=None):
        return SourceEvidence(
            document_id=record["document_id"],
            citation=record["citation"],
            evidence_quote=quote if quote is not None else record["content"],
            markdown_path=record.get("markdown_path"),
            source_start=record.get("source_start"),
            source_end=record.get("source_end"),
        )

    return build


@pytest.fixture
def sdk_response():
    """Construct the installed SDK's actual types without sending a request."""

    def build(extraction=None, *, status="completed", refusal=None):
        content = []
        if refusal is not None:
            content.append(ResponseOutputRefusal(type="refusal", refusal=refusal))
        elif extraction is not None:
            content.append(
                ParsedResponseOutputText.model_construct(
                    type="output_text",
                    text=extraction.model_dump_json(),
                    parsed=extraction,
                    annotations=[],
                    logprobs=[],
                )
            )
        return ParsedResponse.model_construct(
            id="resp_synthetic",
            status=status,
            error=None,
            incomplete_details=IncompleteDetails(reason="max_output_tokens")
            if status == "incomplete"
            else None,
            output=[
                ParsedResponseOutputMessage.model_construct(
                    type="message",
                    id="msg_synthetic",
                    role="assistant",
                    status="completed",
                    content=content,
                )
            ],
        )

    return build
