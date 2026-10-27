"""User behavior, timing, privacy and correlation at the application boundary."""

import pytest
import user_events as module

import credit_monitoring.observability.session as sessions


@pytest.fixture
def tracking(monkeypatch):
    records = []
    now = [100.0]
    monkeypatch.setattr(module, "is_observability_configured", lambda: True)
    monkeypatch.setattr(module, "capture_content_enabled", lambda: False)
    monkeypatch.setattr(sessions, "is_observability_configured", lambda: False)

    def emit(message, **attributes):
        assert sessions.get_active_session() is tracker.session
        assert message == attributes["event_name"]
        records.append(attributes)

    monkeypatch.setattr(module.logfire, "info", emit)
    tracker = module.UserEvents(sessions.SessionContext(), clock=lambda: now[0])
    return tracker, records, now


@pytest.mark.parametrize("capture_content", [False, True])
def test_content_policy_applies_to_questions_and_feedback(tracking, monkeypatch, capture_content):
    tracker, records, _ = tracking
    monkeypatch.setattr(module, "capture_content_enabled", lambda: capture_content)
    tracker.submit("Evidence Search", "answer-1", "PRIVATE QUESTION")
    tracker.feedback("Evidence Search", "answer-1", 0, "Incorrect", "PRIVATE COMMENT")
    assert ("PRIVATE QUESTION" in str(records)) is capture_content
    assert ("PRIVATE COMMENT" in str(records)) is capture_content
    assert records[-1]["rating"] == "negative"
    assert records[-1]["reason"] == "Incorrect" and records[-1]["has_comment"]
    assert all(record["chat_id"] == tracker.session.session_id for record in records)
    assert all(record["interaction_id"] == "answer-1" for record in records)
    assert sessions.get_active_session() is None


def test_followups_and_retry_preserve_answer_and_error_relationships(tracking):
    tracker, records, now = tracking
    tracker.submit("Credit Analysis", "first", "Review the borrower")
    now[0] += 2
    tracker.answer_presented("Credit Analysis", "first", "TimeoutError")
    now[0] += 8
    tracker.submit(
        "Credit Analysis",
        "retry",
        "Review the borrower",
        previous_interaction_id="first",
        retry_of="first",
        previous_error="TimeoutError",
    )
    retry = records[-1]
    assert retry["event_name"] == "user.retry"
    assert retry["retry_of"] == retry["previous_interaction_id"] == "first"
    assert retry["previous_error"] == "TimeoutError" and retry["retry_delay_seconds"] == 8
    tracker.submit(
        "Credit Analysis",
        "followup",
        "Explain headroom",
        previous_interaction_id="retry",
        follow_up_type="Clarification",
    )
    assert records[-1]["event_name"] == "user.follow_up"
    assert records[-1]["previous_interaction_id"] == "retry"
    assert records[-1]["follow_up_type"] == "Clarification"
    tracker.submit(
        "Credit Analysis",
        "new",
        "Another borrower",
        previous_interaction_id="followup",
        follow_up_type="New topic",
    )
    assert records[-1]["is_follow_up"] is False


def test_duration_excludes_idle_gaps_and_model_wait_and_end_is_idempotent(tracking):
    tracker, records, now = tracking
    tracker.start("Evidence Search")
    now[0] += 10
    tracker.submit("Evidence Search", "first", "Find evidence")
    now[0] += 40
    tracker.answer_presented("Evidence Search", "first", None)
    assert records[-1]["response_seconds"] == 40
    now[0] += 5
    tracker.source_opened("Evidence Search", "first", 0)
    now[0] += 600  # A tab left idle does not add ten minutes of active usage.
    tracker.click("Evidence Search", "reset")
    tracker.end("Evidence Search")
    tracker.end("Evidence Search")
    summary = records[-1]
    assert summary["event_name"] == "user.ended"
    assert summary["active_seconds"] == 15
    assert summary["observed_duration_seconds"] == summary["elapsed_seconds"] == 655
    assert summary["question_count"] == 1
    assert sum(record["event_name"] == "user.ended" for record in records) == 1


def test_duplicate_execution_and_unconfigured_logging_are_quiet(tracking, monkeypatch):
    tracker, records, _ = tracking
    tracker.submit("Credit Analysis", "first", "Review")
    tracker.submit("Credit Analysis", "first", "Review")
    tracker.answer_presented("Credit Analysis", "first", None)
    tracker.answer_presented("Credit Analysis", "first", None)
    assert len(records) == 2 and tracker.question_count == 1
    monkeypatch.setattr(module, "is_observability_configured", lambda: False)
    tracker.click("Credit Analysis", "mode")
    assert len(records) == 2


def test_independent_sessions_do_not_share_counters(tracking):
    first, _, _ = tracking
    second = module.UserEvents(sessions.SessionContext())
    first.submit("Credit Analysis", "first", "Review")
    assert first.question_count == 1 and second.question_count == 0
    assert first.session.session_id != second.session.session_id


def test_reset_context_records_cleared_history_without_question_content(tracking):
    tracker, records, _ = tracking
    tracker.submit("Credit Analysis", "answer-1", "PRIVATE QUESTION")
    tracker.reset_context(
        "Credit Analysis",
        cleared_turn_count=3,
        cleared_modes=["Evidence Search", "Credit Analysis"],
        interaction_id="answer-1",
    )
    reset = records[-1]
    assert reset["event_name"] == "user.reset_context"
    assert reset["interaction_id"] == "answer-1"
    assert reset["cleared_turn_count"] == 3
    assert reset["cleared_modes"] == ["Evidence Search", "Credit Analysis"]
    assert reset["reason"] == "user_requested"
    assert "PRIVATE QUESTION" not in str(records)


def test_resume_replaces_stale_emitter_and_preserves_history_and_timing(tracking):
    tracker, records, now = tracking

    class OldUserEvents(module.UserEvents):
        def _emit(self, *args, **kwargs):
            raise AssertionError("Old emitter would use User event: {event_name}")

    old = OldUserEvents(tracker.session, clock=tracker.clock)
    now[0] += 10
    # State comes from a successful turn before the source-code reload.
    tracker.submit("Credit Analysis", "answer-1", "PRIVATE QUESTION")
    now[0] += 5
    tracker.answer_presented("Credit Analysis", "answer-1", "TimeoutError")
    old.__dict__.update(vars(tracker))
    now[0] += 20
    current = module.UserEvents.resume(old)
    assert type(current) is module.UserEvents
    assert current.session is tracker.session
    assert current.question_count == 1
    current.submit(
        "Credit Analysis",
        "answer-2",
        "Retry",
        retry_of="answer-1",
        previous_interaction_id="answer-1",
        previous_error="TimeoutError",
    )
    retry = records[-1]
    assert retry["event_name"] == "user.retry" and retry["retry_delay_seconds"] == 20
    assert retry["elapsed_seconds"] == 35 and retry["active_seconds"] == 30
    assert retry["question_count"] == 2
    assert module.UserEvents.resume(current) is current
