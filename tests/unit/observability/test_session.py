"""Application session ownership and cleanup; SDK operations are replaced by stubs."""

import asyncio
from contextlib import contextmanager
from unittest.mock import Mock
from uuid import UUID

import pytest

import credit_monitoring.observability.session as sessions


@pytest.fixture(autouse=True)
def unconfigured_monitoring(monkeypatch):
    monkeypatch.setenv("LOGFIRE_SEND_TO_LOGFIRE", "false")
    monkeypatch.setattr(sessions, "is_observability_configured", lambda: False)
    assert sessions.get_active_session() is None
    yield
    assert sessions.get_active_session() is None


def test_session_defaults_are_independent_and_do_not_capture_context():
    first, second = sessions.SessionContext(), sessions.SessionContext()
    assert UUID(first.session_id)
    assert first.session_id != second.session_id
    assert first.carrier is None and second.carrier is None


def test_unconfigured_scope_reuses_nested_session_without_sdk_calls(monkeypatch):
    capture = Mock(side_effect=AssertionError("Unconfigured session must stay quiet"))
    monkeypatch.setattr(sessions, "_capture_session_trace", capture)
    with sessions.session_scope() as outer:
        assert sessions.get_active_session() is outer
        with sessions.session_scope() as nested:
            assert nested is outer
        with sessions.session_scope(outer) as explicit:
            assert explicit is outer
        assert sessions.get_active_session() is outer
    assert outer.carrier is None
    capture.assert_not_called()


def test_independent_scope_restores_outer_session_after_failure():
    first, second = sessions.SessionContext(), sessions.SessionContext()
    with sessions.session_scope(first):
        with pytest.raises(ValueError, match="Expected failure"):
            with sessions.session_scope(second) as active:
                assert active is second
                assert sessions.get_active_session() is second
                raise ValueError("Expected failure")
        assert sessions.get_active_session() is first


def test_configured_scope_captures_once_and_does_not_reattach_nested_scope(monkeypatch):
    monkeypatch.setattr(sessions, "is_observability_configured", lambda: True)
    carrier = {"traceparent": "opaque-context-carrier"}
    capture = Mock(return_value=carrier)
    monkeypatch.setattr(sessions, "_capture_session_trace", capture)
    events = []

    @contextmanager
    def baggage(**attributes):
        events.append(("baggage", attributes))
        yield

    @contextmanager
    def attach(actual):
        events.append(("attach", actual))
        try:
            yield
        finally:
            events.append(("detach", actual))

    monkeypatch.setattr(sessions.logfire, "set_baggage", baggage)
    monkeypatch.setattr(sessions.logfire, "attach_context", attach)
    retained = sessions.SessionContext()
    for _ in range(2):
        with sessions.session_scope(retained):
            before_nested = list(events)
            with sessions.session_scope():
                assert sessions.get_active_session() is retained
            with sessions.session_scope(retained):
                assert sessions.get_active_session() is retained
            assert events == before_nested
    capture.assert_called_once_with()
    assert retained.carrier is carrier
    assert events == [
        event
        for _ in range(2)
        for event in (
            ("baggage", {"gen_ai.conversation.id": retained.session_id}),
            ("attach", carrier),
            ("detach", carrier),
        )
    ]


def test_session_context_is_restored_if_carrier_capture_fails(monkeypatch):
    monkeypatch.setattr(sessions, "is_observability_configured", lambda: True)

    @contextmanager
    def baggage(**attributes):
        yield

    monkeypatch.setattr(sessions.logfire, "set_baggage", baggage)
    monkeypatch.setattr(
        sessions, "_capture_session_trace", Mock(side_effect=RuntimeError("Capture failed"))
    )
    retained = sessions.SessionContext()
    with pytest.raises(RuntimeError, match="Capture failed"):
        with sessions.session_scope(retained):
            pytest.fail("Work must not start after capture failure")
    assert retained.carrier is None


def test_tasks_and_worker_threads_inherit_session_without_leaking():
    async def exercise():
        with sessions.session_scope() as retained:

            async def child():
                await asyncio.sleep(0)
                with sessions.session_scope() as nested:
                    assert nested is retained
                    return await asyncio.to_thread(sessions.get_active_session)

            children = await asyncio.gather(child(), child())
            assert all(child is retained for child in children)
        assert sessions.get_active_session() is None

    asyncio.run(exercise())


def test_cancellation_releases_session_in_consuming_task():
    async def exercise():
        started = asyncio.Event()
        cleaned = []

        async def work():
            try:
                with sessions.session_scope():
                    started.set()
                    await asyncio.Event().wait()
            finally:
                cleaned.append(sessions.get_active_session())

        task = asyncio.create_task(work())
        await started.wait()
        assert sessions.get_active_session() is None
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned == [None]

    asyncio.run(exercise())
