"""Web identity survives reruns without retaining trace parents or leaking to other users."""

import asyncio
from uuid import UUID

import logfire
import pytest

from credit_monitoring.web import telemetry


@pytest.fixture
def browser(monkeypatch):
    state = {}
    monkeypatch.setattr(telemetry.st, "session_state", state)
    return state


def test_reruns_and_chat_clears_keep_web_identity_and_restore_caller(browser):
    original = logfire.get_context()
    with telemetry.web_session_scope() as first:
        assert str(UUID(first)) == first
        assert logfire.get_baggage()["session.id"] == first
        browser["chat_history"] = []
        with telemetry.web_session_scope() as nested:
            assert nested == first
    browser.pop("chat_history")
    with telemetry.web_session_scope() as second:
        assert second == first
    assert logfire.get_context() == original


def test_callback_binds_identity_outside_page_and_restores_after_failure(browser):
    @telemetry.with_web_session
    def callback():
        assert logfire.get_baggage()["session.id"] == browser[telemetry.WEB_SESSION_KEY]
        raise ValueError("callback failure")

    with logfire.set_baggage(**{"session.id": "caller"}):
        with pytest.raises(ValueError, match="callback failure"):
            callback()
        assert logfire.get_baggage()["session.id"] == "caller"


def test_concurrent_web_sessions_and_workers_do_not_exchange_identity(browser, monkeypatch):
    async def exercise():
        async def read_worker():
            await asyncio.sleep(0)
            return await asyncio.to_thread(lambda: logfire.get_baggage()["session.id"])

        with telemetry.web_session_scope() as first:
            task_a = asyncio.create_task(read_worker())
        monkeypatch.setattr(telemetry.st, "session_state", {})
        with telemetry.web_session_scope() as second:
            task_b = asyncio.create_task(read_worker())
        assert first != second
        assert await asyncio.gather(task_a, task_b) == [first, second]
        assert "session.id" not in logfire.get_baggage()

    asyncio.run(exercise())


def test_cancellation_restores_web_identity(browser):
    async def exercise():
        started = asyncio.Event()
        restored = []

        async def run():
            try:
                with telemetry.web_session_scope():
                    started.set()
                    await asyncio.Event().wait()
            finally:
                restored.append(logfire.get_baggage().get("session.id"))

        task = asyncio.create_task(run())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert restored == [None]

    asyncio.run(exercise())
