"""Workflow baggage overrides are scoped across tasks, threads and failures."""

import asyncio

import logfire
import pytest

from credit_monitoring.observability.activity import activity_scope


def current():
    return logfire.get_baggage().get("cost.activity")


def test_nested_default_override_and_error_restore_caller_baggage():
    assert current() is None
    with activity_scope("evidence_chat"):
        with activity_scope("assessment_assistant", default=True):
            assert current() == "evidence_chat"
        with pytest.raises(ValueError):
            with activity_scope("document_extraction"):
                assert current() == "document_extraction"
                raise ValueError("synthetic failure")
        assert current() == "evidence_chat"
    assert current() is None


@pytest.mark.asyncio
async def test_concurrent_reviewers_and_threads_keep_separate_activity_and_restore_after_cancel():
    async def reviewer(role):
        with activity_scope(role):
            await asyncio.sleep(0)
            assert current() == role
            assert await asyncio.to_thread(current) == role
        assert current() == "credit_coordinator"

    started = asyncio.Event()

    async def cancelled():
        with activity_scope("bullish_review"):
            started.set()
            await asyncio.Event().wait()

    with activity_scope("credit_coordinator"):
        await asyncio.gather(reviewer("bullish_review"), reviewer("bearish_review"))
        task = asyncio.create_task(cancelled())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert current() == "credit_coordinator"
    assert current() is None
