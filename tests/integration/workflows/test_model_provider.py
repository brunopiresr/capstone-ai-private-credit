"""PydanticAI's installed OpenAI provider runs against a mocked HTTP transport."""

import asyncio
import json
from unittest.mock import Mock

import httpx2 as httpx
import pytest
from pydantic_ai import models
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.covenants.extraction import extract_covenants
from credit_monitoring.domain import CovenantExtraction


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
