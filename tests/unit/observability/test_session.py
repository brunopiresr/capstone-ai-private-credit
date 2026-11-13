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
    assert first.name == second.name == "Credit assessment"


def test_session_name_is_trimmed_and_preserves_positional_identifier():
    session = sessions.SessionContext("existing-session", name="  Quarterly review — AAPL\t")
    assert session.session_id == "existing-session"
    assert session.name == "Quarterly review — AAPL"


@pytest.mark.parametrize("name", ["", " ", "\t\n"])
def test_blank_session_name_is_rejected(name):
    with pytest.raises(ValueError, match="Session name must not be blank"):
        sessions.SessionContext(name=name)


def test_unconfigured_scope_reuses_nested_session_without_sdk_calls(monkeypatch):
    baggage = Mock(side_effect=AssertionError("Unconfigured session must stay quiet"))
    monkeypatch.setattr(sessions.logfire, "set_baggage", baggage)
    with sessions.session_scope() as outer:
        assert sessions.get_active_session() is outer
        with sessions.session_scope() as nested:
            assert nested is outer
        with sessions.session_scope(outer) as explicit:
            assert explicit is outer
        assert sessions.get_active_session() is outer
    baggage.assert_not_called()


def test_independent_scope_restores_outer_session_after_failure():
    first, second = sessions.SessionContext(), sessions.SessionContext()
    with sessions.session_scope(first):
        with pytest.raises(ValueError, match="Expected failure"):
            with sessions.session_scope(second) as active:
                assert active is second
                assert sessions.get_active_session() is second
                raise ValueError("Expected failure")
        assert sessions.get_active_session() is first


@pytest.mark.parametrize("name", ["Credit assessment", "Quarterly review — AAPL"])
def test_configured_scope_binds_identity_without_changing_parent(monkeypatch, name):
    monkeypatch.setattr(sessions, "is_observability_configured", lambda: True)
    attach = Mock(side_effect=AssertionError("Session identity must not replace trace parents"))
    monkeypatch.setattr(sessions.logfire, "attach_context", attach)
    events = []

    @contextmanager
    def baggage(**attributes):
        events.append(attributes)
        yield

    monkeypatch.setattr(sessions.logfire, "set_baggage", baggage)
    retained = sessions.SessionContext(name=name)
    for _ in range(2):
        with sessions.session_scope(retained):
            before_nested = list(events)
            with sessions.session_scope():
                assert sessions.get_active_session() is retained
            with sessions.session_scope(retained):
                assert sessions.get_active_session() is retained
            assert events == before_nested
    assert events == [{"gen_ai.conversation.id": retained.session_id}] * 2
    attach.assert_not_called()


def test_session_context_is_restored_if_baggage_binding_fails(monkeypatch):
    monkeypatch.setattr(sessions, "is_observability_configured", lambda: True)
    monkeypatch.setattr(
        sessions.logfire, "set_baggage", Mock(side_effect=RuntimeError("Capture failed"))
    )
    with pytest.raises(RuntimeError, match="Capture failed"):
        with sessions.session_scope():
            pytest.fail("Work must not start after binding failure")


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
