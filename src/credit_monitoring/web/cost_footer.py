"""Shared chat footer; reconciliation only reads telemetry and never executes a turn."""

from dataclasses import dataclass
from time import monotonic

import streamlit as st

from credit_monitoring.observability.activity import ACTIVITY_LABELS
from credit_monitoring.observability.costs import CostTrackingService, SessionCostSummary
from credit_monitoring.observability.session import SessionContext

RETRY_TIMES = (0, 2, 5, 10, 20, 30)


@dataclass
class CostRefreshState:
    session_id: str
    snapshot: SessionCostSummary | None = None
    latest: SessionCostSummary | None = None
    started_at: float = 0
    next_attempt_at: float = 0
    blocked_until: float = 0
    attempts: int = 0
    active: bool = False
    stale: bool = False

    def start(self, now: float) -> None:
        self.started_at = now
        self.next_attempt_at = max(now, self.blocked_until)
        self.attempts = 0
        self.active = True

    def poll(self, session: SessionContext, service: CostTrackingService, now: float) -> None:
        if not self.active or now < self.next_attempt_at:
            return
        if now > self.started_at + RETRY_TIMES[-1] + 2:
            self.active = False
            return
        result = service.get_session_cost(session)
        self.latest = result
        self.attempts += 1
        if result.status in {"available", "partial"}:
            self.snapshot = result
            self.stale = False
        elif result.status == "unavailable":
            self.stale = self.snapshot is not None
        if result.retry_after is not None:
            self.blocked_until = now + result.retry_after
        if (
            (result.status == "unavailable" and not result.retryable)
            or self.attempts == len(RETRY_TIMES)
        ):
            self.active = False
        else:
            self.next_attempt_at = max(
                self.started_at + RETRY_TIMES[self.attempts], self.blocked_until
            )
            if self.next_attempt_at > self.started_at + RETRY_TIMES[-1]:
                self.active = False


def request_cost_refresh(session: SessionContext, *, key: str) -> None:
    """Call after tracing scopes close, even when a question fails or is cancelled."""
    state = st.session_state.get(key)
    if state is None or state.session_id != session.session_id:
        state = CostRefreshState(session.session_id)
        st.session_state[key] = state
    state.start(monotonic())


def _amount(value) -> str:
    return "Unavailable" if value is None else f"${value:.6f}"


@st.fragment(run_every=1)
def render_cost_footer(session: SessionContext | None, *, key: str) -> None:
    """The timer redraws only this footer; network reads stop after reconciliation."""
    st.markdown("**Estimated session cost**")
    if session is None:
        st.caption("$0.000000 USD · Input: 0 · Output: 0")
        return
    state = st.session_state.get(key)
    if state is None or state.session_id != session.session_id:
        state = CostRefreshState(session.session_id)
        st.session_state[key] = state
    service = CostTrackingService()
    if state.latest is None:
        state.latest = service.configuration_status(session)
    state.poll(session, service, monotonic())
    snapshot = state.snapshot
    if snapshot is not None:
        total = _amount(snapshot.total_cost)
        if snapshot.status == "partial":
            total = f"At least {_amount(snapshot.known_cost)} (partial)"
        st.caption(
            f"{total} USD · Input: {snapshot.input_tokens:,} · Output: {snapshot.output_tokens:,}"
        )
        st.caption(
            f"{'Stale snapshot' if state.stale else 'Snapshot'} as of "
            f"{snapshot.queried_at.strftime('%Y-%m-%d %H:%M:%S UTC')} · "
            "New Logfire records may arrive later."
        )
        with st.expander("Cost by activity"):
            st.dataframe(
                [
                    {
                        "Activity": ACTIVITY_LABELS.get(item.activity, item.label),
                        "Requests": item.request_count,
                        "Input tokens": item.input_tokens,
                        "Output tokens": item.output_tokens,
                        "Cached input tokens": item.cached_input_tokens,
                        "Cost (USD)": _amount(item.cost),
                        "Known cost (USD)": _amount(item.known_cost),
                        "Status": ", ".join(item.issues) or "Priced",
                    }
                    for item in snapshot.activities
                ],
                hide_index=True,
                use_container_width=True,
            )
            st.caption(f"Pricing version: {snapshot.pricing_version} · Model token costs only")
    elif not state.active and state.latest is None:
        st.caption("$0.000000 USD · Input: 0 · Output: 0")
    if state.active:
        st.caption("Updating cost…")
    if state.latest is not None and state.latest.status == "unavailable":
        messages = {
            "missing_read_token": "Set LOGFIRE_READ_TOKEN to enable cost tracking.",
            "export_disabled": "Logfire export is disabled.",
            "authentication_failed": "Check the Logfire read token and project access.",
            "rate_limited": "Logfire queries are rate limited. Retry after the waiting period.",
        }
        st.caption("Cost unavailable · " + messages.get(
            state.latest.error_code, "Logfire could not be queried."
        ))
    elif not state.active and state.latest is not None and state.latest.status == "pending":
        st.caption("Waiting for Logfire usage. Refresh cost to check again.")
    st.button(
        "Refresh cost", key=f"{key}_refresh",
        disabled=monotonic() < state.blocked_until,
        on_click=request_cost_refresh, args=(session,), kwargs={"key": key},
    )
