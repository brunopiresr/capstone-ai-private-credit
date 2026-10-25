"""Task-local workflow attribution for native Logfire model-request spans."""

from collections.abc import Iterator
from contextlib import contextmanager

import logfire

ACTIVITY_LABELS = {
    "evidence_chat": "Evidence chat",
    "assessment_assistant": "Assessment assistant",
    "credit_coordinator": "Credit coordinator",
    "bullish_review": "Bullish review",
    "bearish_review": "Bearish review",
    "recommendation": "Recommendation",
    "narrative": "Narrative",
    "document_extraction": "Document extraction",
    "other": "Other",
}


@contextmanager
def activity_scope(activity: str, *, default: bool = False) -> Iterator[None]:
    """Override nested stages, or provide a default without replacing the caller's stage."""
    if default and logfire.get_baggage().get("cost.activity"):
        yield
    else:
        with logfire.set_baggage(**{"cost.activity": activity}):
            yield
