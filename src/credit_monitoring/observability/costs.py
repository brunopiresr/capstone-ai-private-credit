"""Query session usage from Logfire and price native model requests exactly once."""

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

import httpx
from logfire.query_client import (
    AsyncLogfireQueryClient,
    LogfireQueryClient,
    QueryExecutionError,
    QueryRateLimitedError,
    QueryRequestError,
)

from credit_monitoring.observability.activity import ACTIVITY_LABELS
from credit_monitoring.observability.pricing import PRICING_VERSION, find_price
from credit_monitoring.observability.session import SessionContext


@dataclass
class ActivityCost:
    activity: str
    label: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    request_count: int = 0
    cost: Decimal | None = Decimal(0)
    known_cost: Decimal = Decimal(0)
    issues: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SessionCostSummary:
    session_id: str
    status: Literal["available", "pending", "partial", "unavailable"]
    total_cost: Decimal | None = None
    known_cost: Decimal = Decimal(0)
    input_tokens: int = 0
    output_tokens: int = 0
    activities: tuple[ActivityCost, ...] = ()
    currency: str = "USD"
    pricing_version: str = PRICING_VERSION
    queried_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    error_code: str | None = None
    retryable: bool = False
    retry_after: float | None = None


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _token_count(value) -> int | None:
    # Native instrumentation omits zero counts. Missing *all* usage is handled separately.
    if value is None:
        return 0
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return None


class CostTrackingService:
    """Stateless read API: no local agent usage or SDK cost estimates enter calculations."""

    def __init__(self, *, page_size: int = 1000) -> None:
        if page_size <= 0:
            raise ValueError("Page size must be positive.")
        self.page_size = page_size
        self.read_token = os.getenv("LOGFIRE_READ_TOKEN", "").strip()
        self.base_url = os.getenv("LOGFIRE_BASE_URL") or None
        self.service_name = os.getenv("LOGFIRE_SERVICE_NAME", "credit-monitoring")
        self.environment = os.getenv("LOGFIRE_ENVIRONMENT", "")

    def configuration_status(self, session: SessionContext) -> SessionCostSummary | None:
        """Explain disabled tracking without making any network requests."""
        reason = None
        if os.getenv("LOGFIRE_SEND_TO_LOGFIRE", "").strip().lower() in {"false", "0", "no"}:
            reason = "export_disabled"
        elif not self.read_token:
            reason = "missing_read_token"
        if reason:
            return SessionCostSummary(session.session_id, "unavailable", error_code=reason)
        return None

    def _query(self, session: SessionContext, queried_at: datetime, offset: int) -> str:
        projections = {
            "session_id": "gen_ai.conversation.id",
            "operation": "gen_ai.operation.name",
            "activity": "cost.activity",
            "provider": "gen_ai.provider.name",
            "legacy_provider": "gen_ai.system",
            "request_model": "gen_ai.request.model",
            "response_model": "gen_ai.response.model",
            "input_tokens": "gen_ai.usage.input_tokens",
            "output_tokens": "gen_ai.usage.output_tokens",
            "cached_input_tokens": "gen_ai.usage.cache_read.input_tokens",
        }
        fields = ", ".join(
            f"attributes->>{_literal(attribute)} AS {alias}"
            for alias, attribute in projections.items()
        )
        # Freeze ingestion time too, so arriving records cannot shift OFFSET pages.
        return (
            "SELECT trace_id, span_id, start_timestamp, end_timestamp, kind, "
            f"{fields} FROM records WHERE kind = 'span' AND end_timestamp IS NOT NULL "
            "AND attributes->>'gen_ai.operation.name' = 'chat' "
            f"AND attributes->>'gen_ai.conversation.id' = {_literal(session.session_id)} "
            f"AND service_name = {_literal(self.service_name)} "
            f"AND created_at <= {_literal(queried_at.isoformat())}::timestamptz "
            "ORDER BY start_timestamp, trace_id, span_id "
            f"LIMIT {self.page_size} OFFSET {offset}"
        )

    def _options(self, session: SessionContext, queried_at: datetime) -> dict:
        return {
            "min_timestamp": session.created_at,
            "max_timestamp": queried_at,
            "environment": self.environment,
            "limit": self.page_size,
        }

    def get_session_cost(self, session: SessionContext) -> SessionCostSummary:
        """Return a newly queried snapshot, including explicit unavailable/partial states."""
        if unavailable := self.configuration_status(session):
            return unavailable
        queried_at = datetime.now(UTC)
        rows = []
        try:
            with LogfireQueryClient(
                read_token=self.read_token, base_url=self.base_url, timeout=httpx.Timeout(3)
            ) as client:
                while True:
                    page = client.query_json_rows(
                        self._query(session, queried_at, len(rows)),
                        **self._options(session, queried_at),
                    )["rows"]
                    rows.extend(page)
                    if len(page) < self.page_size:
                        break
            return self._summarize(session, rows, queried_at)
        except Exception as error:
            return self._failure(session, error)

    async def get_session_cost_async(self, session: SessionContext) -> SessionCostSummary:
        """Async equivalent; each invocation owns and closes its HTTP client."""
        if unavailable := self.configuration_status(session):
            return unavailable
        queried_at = datetime.now(UTC)
        rows = []
        try:
            async with AsyncLogfireQueryClient(
                read_token=self.read_token, base_url=self.base_url, timeout=httpx.Timeout(3)
            ) as client:
                while True:
                    page = (await client.query_json_rows(
                        self._query(session, queried_at, len(rows)),
                        **self._options(session, queried_at),
                    ))["rows"]
                    rows.extend(page)
                    if len(page) < self.page_size:
                        break
            return self._summarize(session, rows, queried_at)
        except Exception as error:
            return self._failure(session, error)

    @staticmethod
    def _failure(session: SessionContext, error: Exception) -> SessionCostSummary:
        # The public SDK's UnexpectedResponseError exposes HTTP status in this prefix.
        auth_error = str(error).startswith((
            "Unexpected response status code 401:", "Unexpected response status code 403:"
        )) or (
            isinstance(error, httpx.HTTPStatusError) and error.response.status_code in {401, 403}
        )
        rate_limited = isinstance(error, QueryRateLimitedError)
        retryable = not auth_error and not isinstance(
            error, (QueryRequestError, QueryExecutionError)
        )
        if getattr(error, "retryable", None) is False:
            retryable = False
        return SessionCostSummary(
            session.session_id,
            "unavailable",
            error_code="authentication_failed" if auth_error else (
                "rate_limited" if rate_limited else "query_failed"
            ),
            retryable=retryable,
            retry_after=getattr(error, "retry_after", None),
        )

    @staticmethod
    def _summarize(
        session: SessionContext, rows: list[dict], queried_at: datetime
    ) -> SessionCostSummary:
        activities: dict[str, ActivityCost] = {}
        seen = set()
        for row in rows:
            if (
                row["session_id"] != session.session_id or row["kind"] != "span"
                or not row["end_timestamp"] or row["operation"] != "chat"
            ):
                continue
            identity = (row["trace_id"], row["span_id"])
            if identity in seen:
                continue
            seen.add(identity)
            key = row.get("activity") or "other"
            if key not in ACTIVITY_LABELS:
                key = "other"
            activity = activities.setdefault(key, ActivityCost(key, ACTIVITY_LABELS[key]))
            activity.request_count += 1
            values = [row.get(name) for name in (
                "input_tokens", "output_tokens", "cached_input_tokens"
            )]
            counts = [_token_count(value) for value in values]
            input_tokens, output_tokens, cached_tokens = counts
            activity.input_tokens += input_tokens or 0
            activity.output_tokens += output_tokens or 0
            activity.cached_input_tokens += cached_tokens or 0
            issue = None
            if all(value is None for value in values):
                issue = "missing_usage"
            elif None in counts or cached_tokens > input_tokens:
                issue = "invalid_usage"
            else:
                timestamp = row["start_timestamp"]
                if isinstance(timestamp, str):
                    timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                price = find_price(
                    row.get("provider") or row.get("legacy_provider") or "",
                    row.get("response_model") or row.get("request_model") or "",
                    timestamp.astimezone(UTC).date(),
                )
                if price is None:
                    issue = "unpriced_model"
                else:
                    activity.known_cost += (
                        (input_tokens - cached_tokens) * price.input_rate
                        + cached_tokens * price.cached_input_rate
                        + output_tokens * price.output_rate
                    ) / Decimal(1_000_000)
            if issue and issue not in activity.issues:
                activity.issues.append(issue)
        grouped = tuple(activities[key] for key in sorted(activities))
        for activity in grouped:
            activity.cost = None if activity.issues else activity.known_cost
        partial = any(activity.issues for activity in grouped)
        known = sum((activity.known_cost for activity in grouped), Decimal(0))
        return SessionCostSummary(
            session.session_id,
            "partial" if partial else ("available" if grouped else "pending"),
            total_cost=known if grouped and not partial else None,
            known_cost=known,
            input_tokens=sum(activity.input_tokens for activity in grouped),
            output_tokens=sum(activity.output_tokens for activity in grouped),
            activities=grouped,
            queried_at=queried_at,
        )
