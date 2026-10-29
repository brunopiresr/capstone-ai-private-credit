"""Fresh-process SDK check for feedback parenting across evaluation rerenders."""

# ruff: noqa: E402

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ["LOGFIRE_SEND_TO_LOGFIRE"] = "false"
os.environ["LOGFIRE_CAPTURE_CONTENT"] = sys.argv[2]
os.environ["LOGFIRE_MIN_LEVEL"] = "info"
os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import evaluation_backend as backend
import logfire
from logfire.testing import SimpleSpanProcessor, TestExporter

from credit_monitoring.domain.agent import AgentAnswer
from credit_monitoring.observability import configure_observability
from credit_monitoring.observability.session import get_active_session

PRIVATE_COMMENT = "PRIVATE EVALUATION COMMENT"


def main():
    exporter = TestExporter()
    configure_sdk = logfire.configure
    failed = False

    def make_agent(case, folder, model, *, tracing_enabled):
        async def ask_async(*args, **kwargs):
            with logfire.span("Synthetic agent response"):
                return AgentAnswer(
                    answer="Synthetic test answer",
                    complete=not failed,
                    error="synthetic_failure" if failed else None,
                )

        return SimpleNamespace(ask_async=ask_async)

    # The subprocess owns SDK configuration and cannot send data or call a live model.
    with (
        patch("socket.socket.connect", side_effect=AssertionError("Unexpected network request")),
        patch.object(
            logfire,
            "configure",
            side_effect=lambda **kwargs: configure_sdk(
                **kwargs, additional_span_processors=[SimpleSpanProcessor(exporter)]
            ),
        ),
        patch.object(backend.workbench, "make_agent", make_agent),
    ):
        configure_observability()
        idle = logfire.get_context()
        current = backend.EvaluationRound(
            output_root=Path(sys.argv[1]), cases=backend.load_cases()[:2]
        )
        first = asyncio.run(current.generate())
        assert first.request_context and asyncio.run(current.generate()) is first
        assert get_active_session() is None and logfire.get_context() == idle
        # Model a Streamlit reload retaining the round and answer, then feedback arriving
        # while an unrelated trace is active. The exact request must win as parent.
        current = backend.EvaluationRound.resume(SimpleNamespace(**vars(current)))
        with logfire.span("Unrelated UI activity"):
            unrelated = logfire.get_context()
            current.rate("correct", PRIVATE_COMMENT)
            assert logfire.get_context() == unrelated and get_active_session() is None
        second = asyncio.run(current.generate())
        current.rate("unsupported_claims", "")
        assert current.complete

        fresh = backend.EvaluationRound(
            output_root=Path(sys.argv[1]),
            cases=backend.load_cases()[:1],
            previous_chat_id=current.session.session_id,
        )
        failed = True
        abandoned = asyncio.run(fresh.generate())
        failed = False
        fresh.retry()
        retried = asyncio.run(fresh.generate())
        fresh.rate("unclear", "")
        assert get_active_session() is None and logfire.get_context() == idle
        assert logfire.force_flush(timeout_millis=2000)

    records = exporter.exported_spans_as_dict()
    requests = {
        record["attributes"]["interaction_id"]: record
        for record in records
        if record["attributes"].get("event_name") == "evaluation.request"
    }
    feedback = [r for r in records if r["attributes"].get("event_name") == "user.feedback"]
    assert len(requests) == 4 and len(feedback) == 3
    for record in requests.values():
        attributes = record["attributes"]
        expected = f"evaluation.request {attributes['case_id']} · {attributes['feature']}"
        assert record["name"] == attributes["logfire.msg"] == expected
        children = [
            r
            for r in records
            if (r.get("parent") or {}).get("span_id") == record["context"]["span_id"]
        ]
        assert any(r["name"] == "Synthetic agent response" for r in children)
    for record in feedback:
        attributes = record["attributes"]
        parent = requests[attributes["interaction_id"]]
        assert record["parent"]["span_id"] == parent["context"]["span_id"]
        assert record["context"]["trace_id"] == parent["context"]["trace_id"]
        assert attributes["case_id"] == parent["attributes"]["case_id"]
        assert attributes["chat_id"] == parent["attributes"]["chat_id"]
        assert record["start_time"] >= parent["end_time"]
        category_label = backend.RESPONSE_CATEGORIES[attributes["category"]]
        expected = f"user.feedback {attributes['case_id']} · {category_label}"
        assert record["name"] == attributes["logfire.msg"] == expected
        assert attributes["gen_ai.conversation.id"] == attributes["chat_id"]
    assert not any(r["attributes"]["interaction_id"] == abandoned.interaction_id for r in feedback)
    assert (
        requests[abandoned.interaction_id]["context"]["span_id"]
        != requests[retried.interaction_id]["context"]["span_id"]
    )
    assert (
        requests[first.interaction_id]["context"]["trace_id"]
        == requests[second.interaction_id]["context"]["trace_id"]
    )
    assert (
        requests[first.interaction_id]["context"]["trace_id"]
        != requests[retried.interaction_id]["context"]["trace_id"]
    )
    assert (PRIVATE_COMMENT in json.dumps(records)) is (sys.argv[2] == "true")
    print(
        json.dumps(
            {"requests": len(requests), "feedback": len(feedback), "parenting_verified": True}
        )
    )


if __name__ == "__main__":
    main()
