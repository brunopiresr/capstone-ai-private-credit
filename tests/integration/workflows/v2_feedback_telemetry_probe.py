"""Fresh-process proof that delayed feedback scores retain the original response context."""

# Configure paths and disable transport before importing application instrumentation.
# ruff: noqa: E402

import json
import os
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path
from time import time_ns
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ["LOGFIRE_SEND_TO_LOGFIRE"] = "false"
os.environ["LOGFIRE_CAPTURE_CONTENT"] = sys.argv[1]
os.environ["LOGFIRE_MIN_LEVEL"] = "info"
os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
os.environ["OPENAI_API_KEY"] = "unused-synthetic-credential"

import logfire
from logfire.testing import SimpleSpanProcessor, TestExporter, TestLogExporter
from model_helpers import ScriptedModel
from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor
from pydantic_ai import models

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.observability import configure_observability
from credit_monitoring.web.telemetry import web_session_scope
from credit_monitoring.web_v2.components import chat

PRIVATE_COMMENT = "PRIVATE FEEDBACK COMMENT"
PRIVATE_QUESTION = "PRIVATE QUESTION CONTENT"


def main():
    models.ALLOW_MODEL_REQUESTS = False
    exporter = TestExporter()
    log_exporter = TestLogExporter(time_ns)
    configure_sdk = logfire.configure
    model = ScriptedModel()
    assessment = RiskAssessment(
        assessment_run_id="synthetic-assessment",
        borrower_id="SYN001",
        period_end=date(2025, 9, 30),
        information_cutoff=date(2025, 9, 30),
        results=[],
    )
    workflow = SimpleNamespace(
        portfolio=SimpleNamespace(repository=SimpleNamespace(latest_review=lambda _: None))
    )

    def make_agent(**kwargs):
        return CreditAssessmentAgent(**{**kwargs, "model": model})

    with (
        patch("socket.socket.connect", side_effect=AssertionError("Unexpected network request")),
        patch.object(
            logfire,
            "configure",
            side_effect=lambda **kwargs: configure_sdk(
                **kwargs,
                additional_span_processors=[SimpleSpanProcessor(exporter)],
                advanced=logfire.AdvancedOptions(
                    log_record_processors=[SimpleLogRecordProcessor(log_exporter)]
                ),
            ),
        ),
        patch.object(chat, "CreditAssessmentAgent", make_agent),
        patch.object(chat.st, "session_state", {}),
        web_session_scope() as web_id,
    ):
        configure_observability()
        idle = logfire.get_context()
        messages = []
        for number in range(2):
            interaction_id = f"interaction-{number}"
            with logfire.set_baggage(interaction_id=interaction_id):
                message = chat._answer_question(workflow, assessment, PRIVATE_QUESTION)
            assert message["answer"].complete and message["agent_context"]
            message["interaction_id"] = interaction_id
            messages.append(deepcopy(message))  # Retained message after a UI rerun.
            assert logfire.get_context() == idle

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with logfire.set_baggage(interaction_id="interaction-fallback"):
                fallback = chat._answer_question(workflow, assessment, "Explain headroom")
            assert fallback["response_origin"] == "structured_fallback"
            assert fallback["agent_context"]
            fallback["interaction_id"] = "interaction-fallback"
            messages.append(deepcopy(fallback))

        # Exercise the real emitter after the response has ended and UI has rerun.
        for number, message in enumerate(messages):
            with logfire.span("Unrelated UI activity"):
                caller = logfire.get_context()
                chat.submit_feedback(message, assessment, "analyst", "feedback", number % 2)
                chat.submit_feedback(
                    message,
                    assessment,
                    "analyst",
                    "review",
                    4,
                    category="Accuracy",
                    comment=f"  {PRIVATE_COMMENT}  ",
                )
                # Changed resubmissions are ignored as well as identical ones.
                chat.submit_feedback(message, assessment, "analyst", "feedback", 1)
                chat.submit_feedback(message, assessment, "analyst", "review", 1, category="Other")
                assert logfire.get_context() == caller
        assert logfire.get_context() == idle
        assert model.respond.call_count == 2
        assert logfire.force_flush(timeout_millis=2000)

    records = exporter.exported_spans_as_dict()
    agents = {
        r["attributes"]["interaction_id"]: r
        for r in records
        if r["name"] == "invoke_agent Credit assessment agent"
    }
    fallbacks = [r for r in records if r["name"] == "assistant.fallback"]
    assert len(agents) == 2 and len(fallbacks) == 1
    responses = {**agents, "interaction-fallback": fallbacks[0]}
    feedback = [
        log.log_record
        for log in log_exporter.get_finished_logs()
        if log.log_record.event_name == "gen_ai.evaluation.result"
    ]
    assert len(feedback) == 6
    assert len({r["context"]["trace_id"] for r in agents.values()}) == 2
    assert len({record.attributes["feedback_id"] for record in feedback}) == 6
    for record in feedback:
        attributes = record.attributes
        parent = responses[attributes["interaction_id"]]
        assert record.span_id == parent["context"]["span_id"]
        assert record.trace_id == parent["context"]["trace_id"]
        assert record.timestamp >= parent["end_time"]
        assert attributes["session.id"] == parent["attributes"]["session.id"] == web_id
        if attributes["response_origin"] == "agent":
            assert (
                attributes["gen_ai.conversation.id"]
                == parent["attributes"]["gen_ai.conversation.id"]
            )
            assert attributes["gen_ai.evaluation.target"] == "Credit assessment agent"
        else:
            assert attributes["gen_ai.evaluation.target"] == "Structured fallback"
            assert "gen_ai.request.model" not in attributes
        if attributes["feedback_type"] == "review":
            assert attributes["gen_ai.evaluation.name"] == "user_review_score"
            assert attributes["gen_ai.evaluation.score.value"] == 4.0
            assert attributes["category"] == "Accuracy"
            assert attributes["comment"] == PRIVATE_COMMENT
        else:
            assert attributes["gen_ai.evaluation.name"] == "user_helpfulness"
            assert attributes["gen_ai.evaluation.score.value"] in {0.0, 1.0}
    assert (PRIVATE_QUESTION in json.dumps(records)) is (sys.argv[1] == "true")
    print(
        json.dumps(
            {
                "agent_spans": len(agents),
                "fallback_spans": len(fallbacks),
                "feedback_events": len(feedback),
            }
        )
    )


if __name__ == "__main__":
    main()
