"""Fresh-process SDK acceptance check for the demo's two chat modes."""

# Imports follow environment/path setup so this standalone probe cannot enable export.
# ruff: noqa: E402

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ["LOGFIRE_SEND_TO_LOGFIRE"] = "false"
os.environ["LOGFIRE_CAPTURE_CONTENT"] = "false"
os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT.parent / "tests")]

import logfire
from demo_models import QUESTION, REVIEW_ARGS, review_model, text_response
from logfire.testing import SimpleSpanProcessor, TestExporter
from model_helpers import ScriptedModel, model_response
from monitoring_backend import CHAT_AGENT_NAMES, ChatBackend, ChatTurn
from pydantic_ai import models

from credit_monitoring.observability import SessionContext, configure_observability
from credit_monitoring.observability.session import get_active_session


def parent(record):
    return record["parent"]["span_id"] if record.get("parent") else None


def main():
    models.ALLOW_MODEL_REQUESTS = False
    exporter = TestExporter()
    original = logfire.configure
    with patch.object(
        logfire,
        "configure",
        side_effect=lambda **kwargs: original(
            **kwargs, additional_span_processors=[SimpleSpanProcessor(exporter)]
        ),
    ):
        configure_observability()
    model = ScriptedModel()
    chat = ChatBackend(
        session=SessionContext(name="Monitoring demo review"),
        model=model,
        review_model=review_model(),
        data_root=Path(sys.argv[1]),
        runtime_root=Path(sys.argv[2]),
    )
    scripts = [
        (
            "Evidence Search",
            "Find leverage evidence.",
            [
                model_response(("search_evidence", {"query": "maximum leverage"})),
                model_response(answer="Synthetic evidence found."),
            ],
        ),
        (
            "Credit Analysis",
            QUESTION,
            [
                model_response(("run_credit_review", REVIEW_ARGS)),
                text_response(),
            ],
        ),
        ("Credit Analysis", "Explain the headroom.", [text_response()]),
        (
            "Evidence Search",
            "Explain that citation.",
            [model_response(answer="The SYN filing supports it.")],
        ),
        ("Credit Analysis", "What are the review limitations?", [text_response()]),
    ]
    for mode, question, replies in scripts:
        model.respond.side_effect = replies
        result = asyncio.run(chat.run_turn(mode, question, ChatTurn()))
        assert not result.error, result
        assert get_active_session() is None
    logfire.force_flush(timeout_millis=2000)
    records = exporter.exported_spans_as_dict()
    traces = {record["context"]["trace_id"] for record in records}
    assert len(traces) == 1
    assert all(
        record["attributes"].get("gen_ai.conversation.id") == chat.session.session_id
        for record in records
    )
    anchor = next(r for r in records if r["name"] == "agent.session")
    turns = [r for r in records if r["name"] == "chat.interaction"]
    assert len(turns) == 5 and all(parent(r) == anchor["context"]["span_id"] for r in turns)
    interactions = {record["context"]["span_id"]: record for record in turns}
    for record in turns:
        attributes = record["attributes"]
        agent_name = CHAT_AGENT_NAMES[attributes["mode"]]
        assert attributes["agent_name"] == agent_name
        assert attributes["chat_name"] == chat.session.name
        assert attributes["chat_id"] == chat.session.session_id
        assert attributes["logfire.msg"] == (
            f"Chat interaction: {attributes['mode']} — {agent_name} — "
            f"{chat.session.name} [chat {chat.session.session_id}]"
        )
    agent_turns = [record for record in records if record["name"] == "agent.turn"]
    assert len(agent_turns) == 2
    for record in agent_turns:
        attributes = record["attributes"]
        assert interactions[parent(record)]["attributes"]["mode"] == "Evidence Search"
        assert attributes["agent_name"] == "Evidence search agent"
        assert attributes["chat_name"] == chat.session.name
        assert attributes["chat_id"] == chat.session.session_id
        assert attributes["logfire.msg"] == (
            f"Agent turn: Evidence search agent — {chat.session.name} "
            f"[chat {chat.session.session_id}]"
        )
        assert any(
            child["name"] == "invoke_agent Evidence search agent"
            and parent(child) == record["context"]["span_id"]
            for child in records
        )
    review = next(r for r in records if r["name"] == "credit.review")
    assessment = next(r for r in records if r["name"] == "credit.assessment")
    assert parent(assessment) == review["context"]["span_id"]
    roles = [r for r in records if r["name"].startswith("invoke_agent Credit review:")]
    assert len(roles) == 3 and all(parent(r) == review["context"]["span_id"] for r in roles)
    requests = [
        r for r in records if r["attributes"].get("gen_ai.operation.name") == "chat"
    ]
    assert {r["attributes"].get("cost.activity") for r in requests} == {
        "evidence_chat", "credit_coordinator", "bullish_review", "bearish_review",
        "recommendation",
    }
    for role in roles:
        expected = role["attributes"]["gen_ai.agent.name"].split(": ")[-1]
        expected = expected if expected == "recommendation" else f"{expected}_review"
        assert all(
            r["attributes"]["cost.activity"] == expected
            for r in requests if parent(r) == role["context"]["span_id"]
        )
    tool = next(r for r in records if r["name"].startswith("execute_tool run_credit_review"))
    assert parent(review) == tool["context"]["span_id"]
    previous = next(iter(traces))
    chat.close()
    fresh = ChatBackend(model=ScriptedModel(response=text_response()))
    asyncio.run(fresh.run_turn("Credit Analysis", "Which details do you need?", ChatTurn()))
    assert fresh.session.session_id != chat.session.session_id
    fresh_turn = next(
        r
        for r in exporter.exported_spans_as_dict()
        if r["name"] == "chat.interaction" and r["context"]["trace_id"] != previous
    )
    assert fresh_turn["attributes"]["chat_id"] == fresh.session.session_id
    assert fresh.session.session_id in fresh_turn["attributes"]["logfire.msg"]
    assert chat.session.session_id not in fresh_turn["attributes"]["logfire.msg"]
    print(
        json.dumps(
            {
                "interactions": len(turns),
                "records": len(records),
                "trace_id": f"{previous:032x}",
                "isolated_reset": True,
            }
        )
    )


if __name__ == "__main__":
    main()
