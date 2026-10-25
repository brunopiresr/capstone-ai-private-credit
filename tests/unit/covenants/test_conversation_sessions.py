"""Conversation identity and cleanup; five-turn telemetry export is opt-in."""

import asyncio
from contextlib import aclosing
from pathlib import Path

import logfire
import pytest
from dotenv import load_dotenv
from model_helpers import ScriptedModel, model_response

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.observability import SessionContext, configure_observability, session_scope
from credit_monitoring.observability.session import get_active_session


@pytest.fixture(autouse=True)
def disable_monitoring(monkeypatch):
    monkeypatch.setenv("LOGFIRE_SEND_TO_LOGFIRE", "false")
    monkeypatch.setattr("credit_monitoring.observability.configuration._configured", False)
    assert get_active_session() is None
    yield
    assert get_active_session() is None


@pytest.fixture
def conversation_logfire(pytestconfig, monkeypatch, disable_monitoring):
    enabled = pytestconfig.getoption("--conversation-logfire")
    if not enabled:
        yield False
        return

    load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)
    monkeypatch.setenv("LOGFIRE_SEND_TO_LOGFIRE", "true")
    configure_observability()
    try:
        yield True
    finally:
        assert logfire.force_flush(), "Logfire telemetry flush did not complete"


def test_conversation_retains_explicit_active_or_new_session(document_service_factory):
    agent = CreditAssessmentAgent(service=document_service_factory(), model=ScriptedModel())
    explicit = SessionContext(name="Explicit quarterly review")
    with session_scope(SessionContext(name="Inherited quarterly review")) as active:
        supplied = agent.start_conversation(session=explicit)
        inherited = agent.start_conversation()
        assert supplied.session_id == explicit.session_id
        assert inherited.session_id == active.session_id
        assert get_active_session() is active
    first, second = agent.start_conversation(), agent.start_conversation()
    assert len({first.session_id, second.session_id, explicit.session_id, active.session_id}) == 4
    with pytest.raises(AttributeError):
        first.session_id = "replacement"


def test_five_synchronous_turns_share_retained_session_and_leave_idle_context_clear(
    document_service_factory,
    conversation_logfire,
):
    seen = []
    idle_context = logfire.get_context() if conversation_logfire else None

    async def callback(event):
        seen.append(get_active_session())

    retained = SessionContext(name="Five-turn quarterly review")
    model = ScriptedModel()
    agent = CreditAssessmentAgent(service=document_service_factory(), model=model)
    conversation = agent.start_conversation(session=retained)
    for number in range(5):
        answer = conversation.ask(f"Question {number}", event_stream_handler=callback)
        assert answer.complete
        assert get_active_session() is None
        if conversation_logfire:
            assert logfire.get_context() == idle_context
    assert seen and all(session is retained for session in seen)
    history = repr(model.respond.call_args.kwargs["messages"])
    assert all(f"Question {number}" in history for number in range(5))
    conversation.close()
    conversation.close()
    if conversation_logfire:
        assert retained.carrier is not None
        assert logfire.get_context() == idle_context
    else:
        assert retained.carrier is None
    assert conversation.session_id == retained.session_id
    with pytest.raises(RuntimeError, match="Conversation is closed"):
        conversation.ask("Later")


def test_callback_failure_restores_callers_session_and_releases_turn(document_service_factory):
    retained = SessionContext()
    agent = CreditAssessmentAgent(service=document_service_factory(), model=ScriptedModel())
    conversation = agent.start_conversation(session=retained)

    async def fail(event):
        assert get_active_session() is retained
        raise ValueError("Callback failed")

    async def exercise():
        with session_scope() as caller:
            with pytest.raises(ValueError, match="Callback failed"):
                await conversation.ask_async("First question", event_stream_handler=fail)
            assert get_active_session() is caller
            assert (await conversation.ask_async("Retry")).complete
            assert get_active_session() is caller

    asyncio.run(exercise())


def test_interrupted_stream_restores_context_in_consuming_task(document_service_factory):
    retained = SessionContext()
    agent = CreditAssessmentAgent(service=document_service_factory(), model=ScriptedModel())
    conversation = agent.start_conversation(session=retained)

    async def exercise():
        with session_scope() as caller:
            async with aclosing(conversation.stream_async("Interrupted")) as stream:
                async for event in stream:
                    assert get_active_session() is retained
                    if event.kind == "answer_update":
                        break
            assert get_active_session() is caller
            assert (await conversation.ask_async("Retry")).complete
            assert get_active_session() is caller

    asyncio.run(exercise())


def test_cancelled_turn_restores_context_and_keeps_conversation_usable(document_service_factory):
    retained = SessionContext()
    model = ScriptedModel()
    agent = CreditAssessmentAgent(service=document_service_factory(), model=model)
    conversation = agent.start_conversation(session=retained)

    async def exercise():
        started = asyncio.Event()
        cleanup = []

        async def respond(**kwargs):
            assert get_active_session() is retained
            started.set()
            await asyncio.Event().wait()

        async def consume():
            try:
                await conversation.ask_async("Cancel me")
            finally:
                cleanup.append(get_active_session())

        model.respond.side_effect = respond
        with session_scope() as caller:
            task = asyncio.create_task(consume())
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert cleanup == [caller]
            assert get_active_session() is caller
            model.respond.side_effect = None
            model.respond.return_value = model_response(answer="Recovered")
            assert (await conversation.ask_async("Retry")).complete

    asyncio.run(exercise())
