"""Exercise the public Logfire query client over a fake HTTP transport, never a model."""

import json
import re
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from credit_monitoring.observability import costs
from credit_monitoring.observability.pricing import find_price
from credit_monitoring.observability.session import SessionContext

START = datetime(2026, 10, 25, tzinfo=UTC)


def request_row(span="1", **overrides):
    return {
        "trace_id": "trace", "span_id": span, "session_id": "session",
        "kind": "span", "operation": "chat", "end_timestamp": START.isoformat(),
        "start_timestamp": START.isoformat(), "provider": "openai",
        "request_model": "gpt-4o-mini", "response_model": "gpt-4o-mini-2024-07-18",
        "input_tokens": "1000", "output_tokens": "100", "cached_input_tokens": "200",
        "activity": "evidence_chat", **overrides,
    }


@pytest.fixture
def query_api(monkeypatch):
    monkeypatch.setenv("LOGFIRE_SEND_TO_LOGFIRE", "true")
    monkeypatch.setenv("LOGFIRE_READ_TOKEN", "synthetic-read-token")
    monkeypatch.setenv("LOGFIRE_BASE_URL", "https://logfire-eu.pydantic.dev")
    monkeypatch.setenv("LOGFIRE_SERVICE_NAME", "credit-monitoring")
    monkeypatch.setenv("LOGFIRE_ENVIRONMENT", "development")
    state = {"rows": [], "calls": [], "status": 200, "headers": {}}

    def handler(request):
        body = json.loads(request.content)
        state["calls"].append(body)
        assert request.url == "https://logfire-eu.pydantic.dev/v2/query"
        assert request.headers["authorization"] == "synthetic-read-token"
        if state["status"] != 200:
            return httpx.Response(state["status"], headers=state["headers"], text="test error")
        offset = int(re.search(r"OFFSET (\d+)", body["sql"])[1])
        page = state["rows"][offset:offset + body["limit"]]
        return httpx.Response(200, json={"schema": {"fields": []}, "data": page})

    sync, asynchronous = costs.LogfireQueryClient, costs.AsyncLogfireQueryClient
    monkeypatch.setattr(costs, "LogfireQueryClient", lambda **kw: sync(
        **kw, transport=httpx.MockTransport(handler)
    ))
    monkeypatch.setattr(costs, "AsyncLogfireQueryClient", lambda **kw: asynchronous(
        **kw, transport=httpx.MockTransport(handler)
    ))
    return state


def session():
    return SessionContext("session", created_at=START)


def test_price_cache_alias_and_repeated_snapshots(query_api):
    query_api["rows"] = [request_row()]
    service = costs.CostTrackingService()
    summary = service.get_session_cost(session())
    assert summary.status == "available"
    assert summary.total_cost == summary.known_cost == Decimal("0.000195")
    assert (summary.input_tokens, summary.output_tokens) == (1000, 100)
    assert summary.activities[0].cached_input_tokens == 200
    assert service.get_session_cost(session()).total_cost == summary.total_cost
    assert summary.currency == "USD" and summary.pricing_version == "2026-10-25.1"
    body = query_api["calls"][0]
    assert body["min_timestamp"] == START.isoformat()
    assert body["deployment_environment"] == ["development"]
    assert body["max_timestamp"] == summary.queried_at.isoformat()
    assert "gen_ai.conversation.id' = 'session'" in body["sql"]
    assert "service_name = 'credit-monitoring'" in body["sql"]
    assert "created_at <=" in body["sql"]
    assert "gen_ai.aggregated_usage" not in body["sql"]
    assert "all_messages" not in body["sql"]


@pytest.mark.asyncio
async def test_async_matches_sync_and_paginates_without_double_counting(query_api):
    query_api["rows"] = [
        request_row("1"), request_row("1"),
        request_row("2", activity="bullish_review"),
        request_row("3", activity="bearish_review"),
        request_row("4", activity="recommendation"),
        request_row("5", activity="credit_coordinator"),
    ]
    service = costs.CostTrackingService(page_size=2)
    summary = await service.get_session_cost_async(session())
    assert len(query_api["calls"]) == 4  # Includes the final empty page.
    assert len({call["max_timestamp"] for call in query_api["calls"]}) == 1
    assert summary.total_cost == 5 * Decimal("0.000195")
    assert len(summary.activities) == 5
    assert sum(item.request_count for item in summary.activities) == 5
    assert service.get_session_cost(session()).activities == summary.activities


def test_partial_usage_and_unpriced_models_keep_known_amounts(query_api):
    query_api["rows"] = [
        request_row(),
        request_row("2", activity="bullish_review", response_model="unknown-model"),
        request_row("3", activity="bearish_review", input_tokens=None,
                    output_tokens=None, cached_input_tokens=None),
        request_row("4", activity="recommendation", provider="unknown-provider"),
    ]
    summary = costs.CostTrackingService().get_session_cost(session())
    assert summary.status == "partial" and summary.total_cost is None
    assert summary.known_cost == Decimal("0.000195")
    assert summary.input_tokens == 3000 and summary.output_tokens == 300
    by_activity = {item.activity: item for item in summary.activities}
    assert by_activity["evidence_chat"].cost == summary.known_cost
    assert by_activity["bullish_review"].cost is None
    assert by_activity["bullish_review"].issues == ["unpriced_model"]
    assert by_activity["bearish_review"].issues == ["missing_usage"]


@pytest.mark.parametrize("input_tokens,output_tokens,cached,expected,issue", [
    (None, "100", None, Decimal("0.00006"), None),
    ("1000", None, None, Decimal("0.00015"), None),
    ("0", "0", "0", Decimal(0), None),
    ("100", "1", "101", None, "invalid_usage"),
    ("-1", "1", None, None, "invalid_usage"),
    ("1.5", "1", None, None, "invalid_usage"),
    (True, "1", None, None, "invalid_usage"),
])
def test_native_zero_omission_and_malformed_usage(
    query_api, input_tokens, output_tokens, cached, expected, issue
):
    query_api["rows"] = [request_row(
        input_tokens=input_tokens, output_tokens=output_tokens, cached_input_tokens=cached
    )]
    summary = costs.CostTrackingService().get_session_cost(session())
    assert summary.total_cost == expected
    assert summary.activities[0].issues == ([issue] if issue else [])


def test_excludes_foreign_sessions_aggregates_and_pending_records(query_api):
    query_api["rows"] = [
        request_row(), request_row("2", session_id="other-session"),
        request_row("3", operation="invoke_agent"),
        request_row("4", kind="pending_span"), request_row("5", end_timestamp=None),
        request_row("6", activity=None),
    ]
    summary = costs.CostTrackingService().get_session_cost(session())
    assert summary.total_cost == Decimal("0.00039")
    assert {item.activity for item in summary.activities} == {"evidence_chat", "other"}


def test_missing_response_model_and_legacy_provider_fall_back(query_api):
    query_api["rows"] = [request_row(response_model=None, provider=None, legacy_provider="openai")]
    assert costs.CostTrackingService().get_session_cost(session()).total_cost == Decimal("0.000195")
    assert find_price("openai", "gpt-4o-mini", datetime(2024, 7, 17).date()) is None


@pytest.mark.parametrize("status,code,retryable", [
    (401, "authentication_failed", False), (403, "authentication_failed", False),
    (429, "rate_limited", True), (503, "query_failed", True),
    (422, "query_failed", False), (400, "query_failed", False),
])
def test_query_failures_are_explicit_and_never_expose_response_text(
    query_api, status, code, retryable
):
    query_api.update(status=status, headers={"Retry-After": "12"})
    summary = costs.CostTrackingService().get_session_cost(session())
    assert summary.status == "unavailable" and summary.total_cost is None
    assert summary.error_code == code and summary.retryable == retryable
    assert summary.retry_after == 12
    assert "test error" not in repr(summary)


@pytest.mark.asyncio
async def test_disabled_or_missing_read_credentials_do_not_query(query_api, monkeypatch):
    monkeypatch.setenv("LOGFIRE_SEND_TO_LOGFIRE", "false")
    summary = costs.CostTrackingService().get_session_cost(session())
    assert summary.error_code == "export_disabled"
    monkeypatch.setenv("LOGFIRE_SEND_TO_LOGFIRE", "true")
    monkeypatch.delenv("LOGFIRE_READ_TOKEN")
    summary = await costs.CostTrackingService().get_session_cost_async(session())
    assert summary.error_code == "missing_read_token"
    assert not query_api["calls"]


def test_empty_query_is_pending_and_delayed_usage_appears(query_api):
    service = costs.CostTrackingService()
    first = service.get_session_cost(session())
    assert first.status == "pending" and first.total_cost is None
    query_api["rows"] = [request_row()]
    assert service.get_session_cost(session()).status == "available"


def test_timeout_and_sql_literal_escaping(query_api, monkeypatch):
    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("synthetic timeout")

    monkeypatch.setattr(costs, "LogfireQueryClient", timeout)
    result = costs.CostTrackingService().get_session_cost(session())
    assert result.status == "unavailable" and result.retryable
    service = costs.CostTrackingService()
    unsafe = SessionContext("session' OR true --")
    assert "'session'' OR true --'" in service._query(unsafe, START, 0)
