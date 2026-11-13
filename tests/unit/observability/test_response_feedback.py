"""Feedback validation and best-effort delivery without model or network calls."""

from datetime import date
from unittest.mock import Mock

import pytest

from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.web_v2.components import chat


@pytest.mark.parametrize(
    "kind, value, category, comment",
    [
        ("unknown", 1, None, ""),
        ("feedback", 2, None, ""),
        ("feedback", True, None, ""),
        ("review", None, "Accuracy", ""),
        ("review", 0, "Accuracy", ""),
        ("review", 6, "Accuracy", ""),
        ("review", 4, None, ""),
        ("review", 4, "Unknown", ""),
        ("review", 4, "Helpful", "x" * 2001),
    ],
)
def test_invalid_feedback_does_not_record_submission(kind, value, category, comment):
    message = {"interaction_id": "response"}
    with pytest.raises(ValueError):
        chat.submit_feedback(
            message, Mock(), "analyst", kind, value, category=category, comment=comment
        )
    assert message == {"interaction_id": "response"}


@pytest.mark.parametrize("configured", [False, True])
def test_unavailable_telemetry_keeps_submission_without_retry(monkeypatch, configured):
    monkeypatch.setattr(chat, "is_observability_configured", lambda: configured)
    logger = Mock()
    logger.emit.side_effect = RuntimeError("Telemetry unavailable")
    monkeypatch.setattr(chat, "get_logger", lambda _: logger)
    assessment = RiskAssessment(
        assessment_run_id="saved-assessment",
        borrower_id="SYN001",
        period_end=date(2025, 9, 30),
        information_cutoff=date(2025, 9, 30),
        results=[],
    )
    message = {"interaction_id": "response", "response_origin": "structured_fallback"}
    chat.submit_feedback(message, assessment, "analyst", "review", 5, category="Helpful")
    chat.submit_feedback(message, assessment, "analyst", "review", 1, category="Accuracy")
    assert message["review"]["score"] == 5
    assert logger.emit.call_count == int(configured)
