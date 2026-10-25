"""Reconciliation timing, delayed ingestion, stale data and rate-limit handling."""

from decimal import Decimal
from unittest.mock import Mock

import pytest

from credit_monitoring.observability.costs import SessionCostSummary
from credit_monitoring.observability.session import SessionContext
from credit_monitoring.web.cost_footer import RETRY_TIMES, CostRefreshState


def snapshot(session, amount="0.000195", **kwargs):
    return SessionCostSummary(
        session.session_id, "available", total_cost=Decimal(amount),
        known_cost=Decimal(amount), **kwargs,
    )


def test_retry_schedule_fetches_new_snapshots_and_stops_without_claiming_finality():
    session = SessionContext()
    state = CostRefreshState(session.session_id)
    service = Mock()
    service.get_session_cost.side_effect = [
        SessionCostSummary(session.session_id, "pending"),
        *[snapshot(session, str(index)) for index in range(1, 6)],
    ]
    state.start(100)
    for index, delay in enumerate(RETRY_TIMES):
        state.poll(session, service, 100 + delay)
        assert service.get_session_cost.call_count == index + 1
        if delay < RETRY_TIMES[-1]:
            state.poll(session, service, 100 + delay + 0.1)
            assert service.get_session_cost.call_count == index + 1
    assert state.snapshot.total_cost == Decimal(5)
    assert not state.active and not state.stale
    state.poll(session, service, 200)
    assert service.get_session_cost.call_count == 6


def test_failed_reads_retain_snapshot_and_recovery_replaces_it():
    session = SessionContext()
    state = CostRefreshState(session.session_id)
    first, recovered = snapshot(session), snapshot(session, "0.00039")
    service = Mock()
    service.get_session_cost.side_effect = [
        first, SessionCostSummary(session.session_id, "unavailable", retryable=True), recovered
    ]
    state.start(0)
    state.poll(session, service, 0)
    state.poll(session, service, 2)
    assert state.snapshot is first and state.stale
    state.poll(session, service, 5)
    assert state.snapshot is recovered and not state.stale


@pytest.mark.parametrize("code", ["authentication_failed", "missing_read_token", "export_disabled"])
def test_configuration_and_auth_failures_stop_automatic_queries(code):
    session = SessionContext()
    state = CostRefreshState(session.session_id)
    service = Mock()
    service.get_session_cost.return_value = SessionCostSummary(
        session.session_id, "unavailable", error_code=code
    )
    state.start(0)
    state.poll(session, service, 0)
    state.poll(session, service, 100)
    assert not state.active
    service.get_session_cost.assert_called_once_with(session)


def test_rate_limit_wait_is_respected_even_when_another_interaction_starts_refresh():
    session = SessionContext()
    state = CostRefreshState(session.session_id)
    service = Mock()
    service.get_session_cost.side_effect = [
        SessionCostSummary(
            session.session_id, "unavailable", error_code="rate_limited",
            retryable=True, retry_after=12,
        ), snapshot(session),
    ]
    state.start(0)
    state.poll(session, service, 0)
    state.start(3)
    state.poll(session, service, 11)
    service.get_session_cost.assert_called_once()
    state.poll(session, service, 12)
    assert service.get_session_cost.call_count == 2


def test_rate_limit_beyond_window_and_old_refresh_stop_automatically():
    session = SessionContext()
    state = CostRefreshState(session.session_id)
    service = Mock()
    service.get_session_cost.return_value = SessionCostSummary(
        session.session_id, "unavailable", retryable=True, retry_after=60
    )
    state.start(0)
    state.poll(session, service, 0)
    assert not state.active and state.blocked_until == 60
    state.start(61)
    state.poll(session, service, 100)
    assert not state.active and service.get_session_cost.call_count == 1


def test_interaction_restart_preserves_snapshot_and_restarts_schedule():
    session = SessionContext()
    state = CostRefreshState(session.session_id, snapshot=snapshot(session))
    service = Mock()
    service.get_session_cost.return_value = snapshot(session, "0.001")
    state.start(20)
    assert state.snapshot.total_cost == Decimal("0.000195")
    state.poll(session, service, 20)
    assert state.snapshot.total_cost == Decimal("0.001") and state.next_attempt_at == 22
