"""Actual SDK response types exercise adaptive tools, RAG, failures, and loop limits."""

import json
from unittest.mock import Mock

import httpx
import pytest
from openai import APIError, OpenAI
from openai.types.responses import (
    Response,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputRefusal,
    ResponseOutputText,
    ResponseReasoningItem,
)

from credit_monitoring.agents.monitoring import MonitoringAgent
from credit_monitoring.agents.tools.documents import DocumentTools
from credit_monitoring.domain import CovenantExtraction


def response(*calls, answer=None, status="completed", refusal=None, reasoning=False):
    output = []
    if reasoning:
        output.append(
            ResponseReasoningItem.model_construct(
                id="reasoning",
                type="reasoning",
                summary=[],
                encrypted_content="private-content",
            )
        )
    for index, (name, arguments) in enumerate(calls):
        output.append(
            ResponseFunctionToolCall(
                name=name,
                arguments=arguments if isinstance(arguments, str) else json.dumps(arguments),
                call_id=f"call_{index}_{name}",
                type="function_call",
            )
        )
    if answer is not None or refusal is not None:
        content = (
            [ResponseOutputRefusal(type="refusal", refusal=refusal)]
            if refusal
            else [ResponseOutputText(type="output_text", text=answer, annotations=[], logprobs=[])]
        )
        output.append(
            ResponseOutputMessage(
                type="message",
                id="msg",
                role="assistant",
                status="completed",
                content=content,
            )
        )
    return Response.model_construct(id="resp", status=status, error=None, output=output)


def agent(service, **kwargs):
    client = Mock()
    return MonitoringAgent(client=client, service=service, **kwargs), client


def test_document_discovery_processing_cache_read_and_rag_loop(
    document_service_factory,
    sdk_response,
):
    service = document_service_factory()
    service.client.responses.parse.return_value = sdk_response(CovenantExtraction())
    monitor, client = agent(service)
    client.responses.create.side_effect = [
        response(("list_documents", {"ticker": None}), reasoning=True),
        response(("get_document_extraction", {"document_id": "SYN"})),
        response(("process_document", {"document_id": "SYN"})),
        response(("process_document", {"document_id": "SYN"})),
        response(("search_evidence", {"query": "maximum leverage", "ticker": None})),
        response(answer="The filing states 4.00 to 1.00. [SYN] Synthetic Issuer, Amendment."),
    ]
    answer = monitor.ask("Show the schedule and supporting filing text.", ticker="SYN")
    assert answer.complete and len(answer.tool_trace) == 5
    assert answer.tool_trace[0].outcome["data"][0]["status"] == "missing"
    assert answer.tool_trace[1].outcome["data"]["result"] is None
    assert not answer.tool_trace[2].outcome["data"]["cache_hit"]
    assert answer.tool_trace[3].outcome["data"]["cache_hit"]
    service.client.responses.parse.assert_called_once()
    assert [s.document_id for s in answer.sources] == ["SYN"]
    assert "private-content" not in answer.model_dump_json()
    second_input = client.responses.create.call_args_list[1].kwargs["input"]
    assert any(item.get("type") == "function_call_output" for item in second_input)
    final_input = client.responses.create.call_args_list[-1].kwargs["input"]
    results = [
        json.loads(i["output"]) for i in final_input if i.get("type") == "function_call_output"
    ]
    assert "Maximum leverage" in results[-1]["data"][0]["content"]


@pytest.mark.parametrize(
    "name,arguments,error",
    [
        ("unknown", {}, "unknown_tool"),
        ("get_document_extraction", "{broken json", "invalid_arguments"),
        ("get_document_extraction", "[]", "invalid_arguments"),
        ("process_document", {"document_id": "SYN", "force": True}, "invalid_arguments"),
        ("get_document_extraction", {"document_id": 3}, "invalid_arguments"),
        ("get_document_extraction", {"document_id": "UNKNOWN"}, "service_error"),
        ("search_evidence", {"query": "leverage", "ticker": "OTHER"}, "service_error"),
    ],
)
def test_dispatch_errors_are_results_for_next_agent_round(
    name,
    arguments,
    error,
    document_service_factory,
):
    monitor, client = agent(document_service_factory())
    client.responses.create.side_effect = [
        response((name, arguments)),
        response(answer="The requested evidence is unavailable."),
    ]
    result = monitor.ask("Question", ticker="SYN")
    assert result.tool_trace[0].outcome["error"] == error
    history = client.responses.create.call_args_list[1].kwargs["input"]
    assert json.loads(history[-1]["output"])["error"] == error


def test_stale_result_is_visible_and_cannot_supply_old_facts(
    document_service_factory, sdk_response
):
    service = document_service_factory()
    service.client.responses.parse.return_value = sdk_response(CovenantExtraction())
    service.process_document("SYN")
    service.model = "changed-model"
    tools = DocumentTools(service)
    result = tools.execute("get_document_extraction", {"document_id": "SYN"})
    assert result["data"]["status"] == "stale" and result["data"]["result"] is None
    assert result["sources"] == []


def test_scoped_agent_cannot_process_other_issuer(document_service_factory):
    service = document_service_factory()
    tools = DocumentTools(service, ticker="OTHER")
    result = tools.execute("process_document", {"document_id": "SYN"})
    assert result["error"] == "service_error"
    service.client.responses.parse.assert_not_called()


def test_six_tool_round_limit_does_not_execute_seventh_call(document_service_factory):
    monitor, client = agent(document_service_factory())
    client.responses.create.return_value = response(("list_documents", {"ticker": None}))
    result = monitor.ask("Question")
    assert not result.complete and result.error == "tool_round_limit"
    assert len(result.tool_trace) == 6 and client.responses.create.call_count == 7


@pytest.mark.parametrize(
    "sdk_result,error",
    [
        (response(status="incomplete"), "model_incomplete"),
        (response(status="failed"), "model_error"),
        (response(refusal="Cannot answer"), "model_refusal"),
        (response(), "empty_response"),
    ],
)
def test_model_failures_are_explicit(sdk_result, error, document_service_factory):
    monitor, client = agent(document_service_factory())
    client.responses.create.return_value = sdk_result
    result = monitor.ask("Question")
    assert not result.complete and result.error == error


def test_api_failure_retains_executed_trace(document_service_factory):
    monitor, client = agent(document_service_factory())
    client.responses.create.side_effect = [
        response(("list_documents", {"ticker": None})),
        APIError(
            "Offline test failure",
            request=httpx.Request("POST", "https://example.invalid"),
            body=None,
        ),
    ]
    result = monitor.ask("Question")
    assert result.error == "model_error" and len(result.tool_trace) == 1


def test_tool_schemas_are_strict_and_configuration_is_not_exposed(document_service_factory):
    definitions = DocumentTools(document_service_factory()).definitions
    assert len(definitions) == 4
    for tool in definitions:
        schema = tool["parameters"]
        assert tool["strict"] and schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        assert "force" not in schema["properties"] and "client" not in schema["properties"]


def test_installed_sdk_serializes_tool_call_continuation(document_service_factory):
    captured = []
    count = 0

    def respond(request):
        nonlocal count
        captured.append(json.loads(request.content))
        count += 1
        item = (
            response(("search_evidence", {"query": "leverage", "ticker": "SYN"}))
            if count == 1
            else response(answer="See SYN, the cited amendment.")
        )
        data = item.model_dump(exclude_none=True)
        data.update(
            {
                "object": "response",
                "created_at": 0,
                "model": "gpt-4o-mini",
                "error": None,
                "incomplete_details": None,
                "instructions": None,
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
                "temperature": 1,
                "top_p": 1,
                "text": {"format": {"type": "text"}},
                "truncation": "disabled",
                "usage": None,
            }
        )
        return httpx.Response(200, json=data)

    with OpenAI(
        api_key="offline-test-key", http_client=httpx.Client(transport=httpx.MockTransport(respond))
    ) as client:
        result = MonitoringAgent(client=client, service=document_service_factory()).ask(
            "Question", "SYN"
        )
    assert result.complete and len(result.tool_trace) == 1
    assert captured[0]["tools"][0]["type"] == "function"
    assert captured[1]["input"][-1]["type"] == "function_call_output"
    assert "Maximum leverage" in captured[1]["input"][-1]["output"]
