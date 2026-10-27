"""Browser-session events correlated with agent traces, without content by default."""

from collections.abc import Callable
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from time import monotonic
from typing import Any

import logfire

from credit_monitoring.observability.configuration import (
    capture_content_enabled,
    is_observability_configured,
)
from credit_monitoring.observability.session import SessionContext, session_scope

FOLLOW_UP_TYPES = ("Unspecified", "Clarification", "Correction", "Deeper analysis", "New topic")
FEEDBACK_REASONS = ("Unspecified", "Incorrect", "Unclear", "Incomplete", "Slow")


@dataclass
class UserEvents:
    """One UI session. Only explicit actions advance estimated active time.

    Gaps over five minutes and time spent waiting for the agent are excluded.
    This measures observed engagement, not browser visibility or exact reading time.
    """

    session: SessionContext
    clock: Callable[[], float] = field(default=monotonic, repr=False)
    idle_seconds: float = 300
    question_count: int = field(default=0, init=False)
    active_seconds: float = field(default=0, init=False)
    _started: float = field(init=False, repr=False)
    _last_activity: float = field(init=False, repr=False)
    _cursor: float = field(init=False, repr=False)
    _submissions: dict[str, float] = field(default_factory=dict, init=False, repr=False)
    _completed: dict[str, float] = field(default_factory=dict, init=False, repr=False)
    _ended: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self._started = self._last_activity = self._cursor = self.clock()

    @classmethod
    def resume(cls, previous: UserEvents) -> UserEvents:
        """Refresh methods after a Streamlit reload while retaining session state."""
        if type(previous) is cls:
            return previous
        current = cls(previous.session, clock=previous.clock, idle_seconds=previous.idle_seconds)
        for descriptor in fields(cls):
            if not descriptor.init and hasattr(previous, descriptor.name):
                setattr(current, descriptor.name, getattr(previous, descriptor.name))
        return current

    def _touch(self) -> None:
        now = self.clock()
        gap = max(0, now - self._cursor)
        if gap <= self.idle_seconds:
            self.active_seconds += gap
        self._cursor = self._last_activity = now

    def _emit(self, event_name: str, mode: str, **attributes: Any) -> None:
        if not is_observability_configured():
            return
        with session_scope(self.session):
            logfire.info(
                event_name,
                event_name=event_name,
                # Reuse the app's chat_id: the default SDK scrubber removes
                # attributes and event values containing the word "session".
                chat_id=self.session.session_id,
                mode=mode,
                event_time=datetime.now(UTC).isoformat(),
                elapsed_seconds=round(max(0, self.clock() - self._started), 3),
                observed_duration_seconds=round(self._last_activity - self._started, 3),
                active_seconds=round(self.active_seconds, 3),
                question_count=self.question_count,
                **attributes,
            )

    def start(self, mode: str, *, previous_chat_id: str | None = None) -> None:
        self._emit("user.started", mode, previous_chat_id=previous_chat_id)

    def reset_context(
        self,
        mode: str,
        *,
        cleared_turn_count: int,
        cleared_modes: list[str],
        interaction_id: str | None = None,
    ) -> None:
        self._touch()
        self._emit(
            "user.reset_context",
            mode,
            cleared_turn_count=cleared_turn_count,
            cleared_modes=cleared_modes,
            interaction_id=interaction_id,
            reason="user_requested",
        )

    def click(self, mode: str, target: str, **attributes: Any) -> None:
        self._touch()
        self._emit("user.click", mode, target=target, **attributes)

    def source_opened(self, mode: str, interaction_id: str, source_index: int) -> None:
        # Index identifies the source in the answer without exporting citation text.
        self.click(mode, "source", interaction_id=interaction_id, source_index=source_index)

    def submit(
        self,
        mode: str,
        interaction_id: str,
        question: str,
        *,
        previous_interaction_id: str | None = None,
        follow_up_type: str = "Unspecified",
        retry_of: str | None = None,
        previous_error: str | None = None,
    ) -> None:
        if interaction_id in self._submissions:
            return
        if follow_up_type not in FOLLOW_UP_TYPES:
            raise ValueError("Unknown follow-up type.")
        self._touch()
        self._submissions[interaction_id] = self.clock()
        self.question_count += 1
        attributes = {
            "interaction_id": interaction_id,
            "previous_interaction_id": previous_interaction_id,
            "turn_number": self.question_count,
            "question_length": len(question),
        }
        if capture_content_enabled():
            attributes["question"] = question
        self._emit("user.question_submitted", mode, **attributes)
        if retry_of is not None:
            previous_finished = self._completed.get(retry_of)
            self._emit(
                "user.retry",
                mode,
                **attributes,
                retry_of=retry_of,
                previous_error=previous_error,
                retry_delay_seconds=(
                    round(max(0, self.clock() - previous_finished), 3)
                    if previous_finished is not None
                    else None
                ),
            )
        elif previous_interaction_id is not None:
            self._emit(
                "user.follow_up",
                mode,
                **attributes,
                follow_up_type=follow_up_type,
                is_follow_up=follow_up_type != "New topic",
                previous_error=previous_error,
            )

    def answer_presented(self, mode: str, interaction_id: str, error: str | None) -> None:
        if interaction_id in self._completed or interaction_id not in self._submissions:
            return
        now = self.clock()
        self._completed[interaction_id] = now
        # Waiting for a response is measured separately from estimated user activity.
        self._cursor = now
        self._emit(
            "user.answer_presented",
            mode,
            interaction_id=interaction_id,
            response_seconds=round(max(0, now - self._submissions[interaction_id]), 3),
            status="error" if error else "complete",
            error_type=error,
        )

    def feedback(
        self, mode: str, interaction_id: str, rating: int, reason: str, comment: str
    ) -> None:
        if rating not in (0, 1) or reason not in FEEDBACK_REASONS:
            raise ValueError("Unknown feedback rating or reason.")
        self._touch()
        attributes = {"comment": comment} if capture_content_enabled() else {}
        self._emit(
            "user.feedback",
            mode,
            interaction_id=interaction_id,
            rating="positive" if rating == 1 else "negative",
            reason=reason,
            has_comment=bool(comment.strip()),
            **attributes,
        )

    def end(self, mode: str, reason: str = "reset") -> None:
        if self._ended:
            return
        self._ended = True
        self._emit("user.ended", mode, end_reason=reason)
