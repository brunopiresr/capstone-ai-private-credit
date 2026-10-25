"""Console callback stream ownership and compatibility with ordinary async iterables."""

import asyncio
from contextvars import ContextVar
from unittest.mock import Mock

import pytest

from credit_monitoring.agents.events import AgentEvent, AgentEventCallback


def test_callback_print_failure_closes_stream_in_consuming_task_and_restores_context(monkeypatch):
    context = ContextVar("callback_test_context", default="caller")
    cleaned = []
    failure = Mock(side_effect=OSError("Console unavailable"))
    monkeypatch.setattr("credit_monitoring.agents.events.print", failure, raising=False)

    async def exercise():
        consuming_task = asyncio.current_task()

        async def events():
            token = context.set("stream")
            try:
                yield AgentEvent(kind="model_start", agent_name="Synthetic agent")
                pytest.fail("Callback must stop reading after printing fails")
            finally:
                context.reset(token)
                cleaned.append((asyncio.current_task(), context.get()))

        with pytest.raises(OSError, match="Console unavailable"):
            await AgentEventCallback().print_function_calls(events())
        # Check before asyncio.run() can finalize abandoned generators in another task.
        assert cleaned == [(consuming_task, "caller")]
        assert context.get() == "caller"

    asyncio.run(exercise())
    failure.assert_called_once_with("MODEL REQUEST (Synthetic agent)", flush=True)


def test_callback_accepts_async_iterable_with_iterator_without_aclose(capsys):
    class PlainIterator:
        def __init__(self):
            self.events = iter(
                [
                    AgentEvent(kind="model_start", agent_name="Synthetic agent"),
                    AgentEvent(kind="run_end", agent_name="Synthetic agent"),
                ]
            )

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.events)
            except StopIteration:
                raise StopAsyncIteration from None

    class Events:
        def __aiter__(self):
            return PlainIterator()

    asyncio.run(AgentEventCallback().print_function_calls(Events()))
    assert capsys.readouterr().out.splitlines() == [
        "MODEL REQUEST (Synthetic agent)",
        "AGENT FINISHED (Synthetic agent): complete",
    ]
