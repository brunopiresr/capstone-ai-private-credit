"""Streaming contracts, output validation and cancellation through real graphs."""

import asyncio
from contextlib import aclosing

import pytest
from model_helpers import ScriptedModel, model_response
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.agents.events import AgentEvent
from credit_monitoring.agents.tools.common import tool_outcome
from credit_monitoring.domain.agent import AgentAnswer


def test_stream_yields_partial_answer_before_confidence_and_finalizes(document_service_factory):
    async def generate(messages, info):
        yield {0: DeltaToolCall(name="final_result", json_args='{"answer":"First')}
        yield {0: DeltaToolCall(json_args=" sentence. More text")}
        yield {0: DeltaToolCall(json_args='", "confidence":"medium"')}
        yield {0: DeltaToolCall(json_args=', "confidence_explanation":"Limited evidence."}')}

    agent = CreditAssessmentAgent(
        service=document_service_factory(), model=FunctionModel(stream_function=generate)
    )

    async def collect():
        return [event async for event in agent.stream_async("Explain")]

    events = asyncio.run(collect())
    updates = [event.output for event in events if event.kind == "answer_update"]
    assert len(updates) > 2
    assert updates[0].answer == "First" and updates[0].confidence is None
    assert updates[1].answer == "First sentence. More text"
    final = events[-1]
    assert final.kind == "run_end" and final.answer.complete
    assert final.answer.confidence == "medium"
    assert final.answer.confidence_explanation == "Limited evidence."
    assert final.answer.tool_trace == []
    assert sum(event.kind == "run_end" for event in events) == 1
    for event in events:
        assert AgentEvent.model_validate_json(event.model_dump_json()) == event


@pytest.mark.parametrize(
    "invalid",
    [
        {"answer": "Missing confidence"},
        {"answer": "Missing explanation", "confidence": "low"},
        {
            "answer": "Bad confidence",
            "confidence": "certain",
            "confidence_explanation": "Unsupported",
        },
        {"answer": " ", "confidence": "high", "confidence_explanation": "Unsupported"},
    ],
)
def test_invalid_final_output_is_retried_and_never_accepted(document_service_factory, invalid):
    model = ScriptedModel(response=ModelResponse(parts=[ToolCallPart("final_result", invalid)]))
    answer = CreditAssessmentAgent(service=document_service_factory(), model=model).ask("Explain")
    assert not answer.complete and answer.confidence is None
    assert answer.confidence_explanation
    assert model.respond.call_count == 2
    assert answer.tool_trace == []


def test_output_validation_can_recover_within_budget(document_service_factory):
    model = ScriptedModel()
    model.respond.side_effect = [
        ModelResponse(parts=[ToolCallPart("final_result", {"answer": "Missing confidence"})]),
        model_response(answer="Corrected answer"),
    ]
    answer = CreditAssessmentAgent(service=document_service_factory(), model=model).ask("Explain")
    assert answer.complete and answer.confidence == "medium"
    assert model.respond.call_count == 2


def test_exhaustive_output_does_not_drop_accompanying_tools(document_service_factory):
    model = ScriptedModel()
    response = model_response(
        ("search_evidence", {"query": "maximum leverage"}), answer="Evidence found"
    )
    response.parts.reverse()  # Output tool arrives before the service tool.
    model.respond.return_value = response
    answer = CreditAssessmentAgent(
        service=document_service_factory(), model=model, max_tool_rounds=1
    ).ask("Explain")
    assert answer.complete
    assert [step.name for step in answer.tool_trace] == ["search_evidence"]
    assert [source.document_id for source in answer.sources] == ["SYN"]
    assert model.respond.call_count == 1


def test_cancelling_stream_keeps_successful_history_and_releases_turn(document_service_factory):
    async def exercise():
        started, release, cleaned = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def generate(messages, info):
            try:
                yield {0: DeltaToolCall(name="final_result", json_args='{"answer":"Provisional')}
                started.set()
                await release.wait()
                yield {
                    0: DeltaToolCall(
                        json_args='", "confidence":"low", "confidence_explanation":"Limited."}'
                    )
                }
            finally:
                cleaned.set()

        agent = CreditAssessmentAgent(service=document_service_factory(), model=ScriptedModel())
        chat = agent.start_conversation(ticker="SYN")
        first = await chat.ask_async("First successful question")
        history = list(chat._history)
        agent.model = FunctionModel(stream_function=generate)

        async def consume():
            async with aclosing(chat.stream_async("Cancelled question")) as stream:
                async for event in stream:
                    if event.kind == "answer_update":
                        await asyncio.sleep(0)

        task = asyncio.create_task(consume())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()
        assert chat._history == history
        assert not chat._in_progress and not chat.closed
        agent.model = ScriptedModel()
        recovered = await chat.ask_async("Follow up")
        assert first.complete and recovered.complete

    asyncio.run(exercise())


def test_closing_generator_discards_partial_turn(document_service_factory):
    async def exercise():
        model = ScriptedModel()
        agent = CreditAssessmentAgent(service=document_service_factory(), model=model)
        chat = agent.start_conversation()
        async with aclosing(chat.stream_async("Question")) as stream:
            async for event in stream:
                if event.kind == "answer_update":
                    break
        assert chat._history == [] and not chat._in_progress
        assert (await chat.ask_async("Try again")).complete

    asyncio.run(exercise())


def test_callback_exception_propagates_without_committing_history(document_service_factory):
    async def handler(event):
        if event.kind == "run_end":
            raise RuntimeError("UI failed")

    agent = CreditAssessmentAgent(service=document_service_factory(), model=ScriptedModel())
    chat = agent.start_conversation()
    with pytest.raises(RuntimeError, match="UI failed"):
        chat.ask("Question", event_stream_handler=handler)
    assert chat._history == [] and not chat._in_progress
    assert chat.ask("Try again").complete


def test_unexpected_service_exception_propagates(document_service_factory):
    service = document_service_factory()

    def fail(**kwargs):
        raise RuntimeError("Programming error")

    service.list_document_extractions = fail
    model = ScriptedModel(response=model_response(("list_documents", {})))
    with pytest.raises(RuntimeError, match="Programming error"):
        CreditAssessmentAgent(service=service, model=model).ask("List")


@pytest.mark.parametrize("delivery", ["callback", "iterator"])
def test_mutating_events_cannot_change_trace_sources_or_conversation_history(
    document_service_factory, delivery
):
    model = ScriptedModel()
    model.respond.side_effect = [
        model_response(("search_evidence", {"query": "maximum leverage"})),
        model_response(answer="The threshold is in SYN."),
        model_response(answer="The earlier SYN filing supports it."),
    ]
    agent = CreditAssessmentAgent(service=document_service_factory(), model=model)
    chat = agent.start_conversation(ticker="SYN")
    original_citation = agent.service.get_document_extraction("SYN").citation

    async def mutate(event):
        assert AgentEvent.model_validate_json(event.model_dump_json()) == event
        if event.kind == "tool_result":
            event.outcome[0].text = "Changed by consumer"
            event.sources[0].citation = "Changed by consumer"
        elif event.kind == "run_end":
            event.answer.sources[0].citation = "Changed by consumer"
            event.answer.tool_trace[0].outcome[0].text = "Changed by consumer"

    async def run():
        if delivery == "callback":
            answer = await chat.ask_async("Find evidence", event_stream_handler=mutate)
            assert answer.sources[0].citation == original_citation
            assert "Maximum leverage" in answer.tool_trace[0].outcome[0].text
        else:
            async with aclosing(chat.stream_async("Find evidence")) as stream:
                async for event in stream:
                    await mutate(event)
        return await chat.ask_async("Which filing supports it?")

    follow_up = asyncio.run(run())
    assert follow_up.complete and follow_up.sources[0].citation == original_citation
    history = model.respond.call_args.kwargs["messages"]
    evidence = next(
        tool_outcome(part.content)[0]
        for message in history
        for part in message.parts
        if getattr(part, "tool_name", None) == "search_evidence" and hasattr(part, "content")
    )
    assert "Maximum leverage" in evidence.text
    assert evidence.citation == original_citation


def test_injected_test_model_and_legacy_answers(document_service_factory):
    model = TestModel(
        call_tools=[],
        custom_output_args={
            "answer": "Answer",
            "confidence": "high",
            "confidence_explanation": "Supplied evidence.",
        },
    )
    agent = CreditAssessmentAgent(service=document_service_factory(), model=model)
    assert agent.ask("First").confidence == "high"
    assert agent.ask("Second").complete
    legacy = AgentAnswer.model_validate_json('{"answer":"Old answer"}')
    assert legacy.confidence is None and legacy.confidence_explanation == ""


def test_stream_failure_retains_only_provisional_output(document_service_factory):
    async def generate(messages, info):
        yield {0: DeltaToolCall(name="final_result", json_args='{"answer":"Partial')}
        raise ModelAPIError(model_name="synthetic", message="Connection lost")

    agent = CreditAssessmentAgent(
        service=document_service_factory(), model=FunctionModel(stream_function=generate)
    )

    async def collect():
        return [event async for event in agent.stream_async("Explain")]

    events = asyncio.run(collect())
    assert any(event.kind == "answer_update" for event in events)
    assert events[-1].kind == "run_end" and not events[-1].answer.complete
    assert events[-1].answer.error == "model_error"
    assert events[-1].answer.confidence is None
