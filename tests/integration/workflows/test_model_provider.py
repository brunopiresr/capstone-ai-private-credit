"""PydanticAI's installed OpenAI provider runs against a mocked HTTP transport."""

import asyncio
import json
from datetime import date
from unittest.mock import Mock

import httpx2 as httpx
import pytest
from pydantic import TypeAdapter
from pydantic_ai import Agent, models
from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.agents.tools.common import ToolCollection, domain_tool
from credit_monitoring.covenants.extraction import extract_covenants
from credit_monitoring.domain import (
    CovenantExtraction,
    DocumentExtraction,
    DocumentSummary,
    FinancialPeriod,
    FinancialReview,
    RetrievedRecord,
    RiskAssessment,
    RiskPrediction,
    ToolFailure,
    ToolOutcome,
)


def response_body(status, output=()):
    return {
        "id": "resp_synthetic",
        "object": "response",
        "created_at": 1,
        "model": "gpt-4o-mini",
        "status": status,
        "background": False,
        "error": None,
        "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
        "output": list(output),
        "usage": None,
    }


def sse_events(status, *, refusal=False):
    call = {
        "type": "function_call",
        "id": "fc_test",
        "name": "process_document",
        "call_id": "call_test",
        "arguments": "",
        "status": "in_progress",
    }
    events = [
        {"type": "response.created", "response": response_body("in_progress")},
        {"type": "response.output_item.added", "output_index": 0, "item": call},
        {
            "type": "response.function_call_arguments.delta",
            "item_id": "fc_test",
            "output_index": 0,
            "delta": '{"document_id":"SYN"}',
        },
    ]
    if refusal:
        events.append(
            {
                "type": "response.refusal.delta",
                "item_id": "msg_refusal",
                "output_index": 1,
                "content_index": 0,
                "delta": "Cannot answer",
            }
        )
    if status != "in_progress":
        events.append({"type": "response." + status, "response": response_body(status)})
    return "".join(
        "data: " + json.dumps({**event, "sequence_number": index}) + "\n\n"
        for index, event in enumerate(events)
    )


@pytest.mark.parametrize(
    "status,refusal,error",
    [
        ("incomplete", False, "model_incomplete"),
        ("failed", False, "model_error"),
        ("in_progress", False, "model_incomplete"),
        ("completed", True, "model_refusal"),
    ],
)
def test_provider_never_dispatches_tools_from_rejected_response(
    monkeypatch,
    status,
    refusal,
    error,
):
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    service = Mock()

    async def run():
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=sse_events(status, refusal=refusal),
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            model = OpenAIResponsesModel(
                "gpt-4o-mini",
                provider=OpenAIProvider(
                    api_key="synthetic-test-key",
                    http_client=client,
                ),
            )
            return await CreditAssessmentAgent(service=service, model=model).ask_async(
                "Process SYN"
            )

    answer = asyncio.run(run())
    assert answer.error == error and not answer.complete
    assert answer.tool_trace == []
    service.process_document.assert_not_called()


def test_extraction_uses_provider_output_schema_and_preserves_facts(
    monkeypatch,
    synthetic_records,
):
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    expected = CovenantExtraction(issuer="Synthetic", gaps=["Missing threshold"])
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        tool_name = payload["tools"][0]["name"]
        return httpx.Response(
            200,
            json=response_body(
                "completed",
                [
                    {
                        "type": "function_call",
                        "id": "fc_extract",
                        "call_id": "extract_call",
                        "name": tool_name,
                        "arguments": expected.model_dump_json(),
                        "status": "completed",
                    }
                ],
            ),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    model = OpenAIResponsesModel(
        "gpt-4o-mini",
        provider=OpenAIProvider(
            api_key="synthetic-test-key",
            http_client=client,
        ),
    )
    try:
        result = extract_covenants("Extract", [synthetic_records["base"]], model=model)
    finally:
        asyncio.run(client.aclose())
    assert result.extraction == expected and result.validation is None
    assert len(requests) == 1
    schema = requests[0]["tools"][0]["parameters"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])


@pytest.mark.parametrize(
    "expected",
    [
        FinancialReview(
            borrower_id="SYN",
            period_end=date(2025, 9, 30),
            information_cutoff=date(2025, 10, 15),
            current=FinancialPeriod(
                borrower_id="SYN",
                period_end=date(2025, 9, 30),
                metrics={"reported_ebitda": 26, "cash": None},
                source_file="finanças.csv",
            ),
            issues=["Publication date unknown"],
        ),
        RiskAssessment(
            assessment_run_id="run_synthetic",
            borrower_id="SYN",
            period_end=date(2025, 9, 30),
            information_cutoff=date(2025, 10, 15),
            results=[],
            ml_status="stub",
            prediction=RiskPrediction(
                borrower_id="SYN",
                period_end=date(2025, 9, 30),
                model_name="stub",
                model_version="v1",
                prediction_status="stub",
            ),
        ),
        DocumentExtraction(document_id="SYN", citation="Synthetic", status="missing"),
        [DocumentSummary(document_id="SYN", citation="Synthetic", status="complete")],
        [RetrievedRecord(document_id="SYN", citation="Synthetic — €", text="Leverage ≤ 4.00x")],
        [],
        ToolFailure(code="service_error", message="Source unavailable"),
    ],
)
def test_provider_serializes_domain_results_once_and_keeps_native_history(monkeypatch, expected):
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    requests = []

    def read_result() -> ToolOutcome:
        return expected

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            output = [
                {
                    "type": "function_call",
                    "id": "fc_read",
                    "call_id": "read_call",
                    "name": "read_result",
                    "arguments": "{}",
                    "status": "completed",
                }
            ]
        else:
            output = [
                {
                    "type": "message",
                    "id": "msg_answer",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "Done", "annotations": []}],
                }
            ]
        return httpx.Response(200, json=response_body("completed", output))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            model = OpenAIResponsesModel(
                "gpt-4o-mini",
                provider=OpenAIProvider(api_key="synthetic-test-key", http_client=client),
            )
            return await Agent(model, tools=[domain_tool(read_result)]).run(
                "Read the domain result"
            )

    result = asyncio.run(run())
    assert result.output == "Done" and len(requests) == 2
    returned = next(
        part
        for message in result.all_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    )
    if isinstance(expected, list):
        assert isinstance(returned.content, ToolCollection)
        assert returned.content.root == expected
    else:
        assert type(returned.content) is type(expected) and returned.content == expected
    wire_result = next(
        item for item in requests[1]["input"] if item.get("type") == "function_call_output"
    )["output"]
    # One decode must produce structured data, rather than another encoded JSON string.
    assert json.loads(wire_result) == TypeAdapter(ToolOutcome).dump_python(expected, mode="json")
