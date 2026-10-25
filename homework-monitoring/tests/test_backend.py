import asyncio
from copy import deepcopy
from datetime import date

import pytest
from demo_models import QUESTION, REVIEW_ARGS, review_model, text_response
from model_helpers import ScriptedModel, model_response
from monitoring_backend import ChatBackend, ChatTurn
from pydantic_ai import ModelRetry
from pydantic_ai.models.function import FunctionModel

from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.observability.session import get_active_session


def backend(tmp_path, data_root, model=None):
    return ChatBackend(
        model=model or ScriptedModel(response=text_response()),
        review_model=review_model(),
        data_root=data_root,
        runtime_root=tmp_path / "runtime",
    )


def ask(chat, mode, question=QUESTION, updates=None):
    return asyncio.run(
        chat.run_turn(
            mode,
            question,
            ChatTurn(),
            on_update=lambda turn: updates.append(deepcopy(turn)) if updates is not None else None,
        )
    )


def test_evidence_streams_real_tools_and_sources(tmp_path, data_root):
    model = ScriptedModel()
    model.respond.side_effect = [
        model_response(("list_documents", {})),
        model_response(("search_evidence", {"query": "maximum leverage", "ticker": "SYN"})),
        model_response(answer="Maximum leverage is 4.0; see SYN.", reasoning=True),
    ]
    chat = backend(tmp_path, data_root, model)
    updates = []
    result = ask(chat, "Evidence Search", "Find the leverage covenant for SYN.", updates)
    assert result.finished and result.error is None
    assert [tool["name"] for tool in result.tools] == ["list_documents", "search_evidence"]
    assert result.sources[0]["document_id"] == "SYN"
    assert result.sources[0]["citation"]
    assert any(not turn.finished and turn.content for turn in updates)
    assert "private-content" not in str(result)
    offered = model.respond.call_args_list[0].kwargs["info"].function_tools
    assert {tool.name for tool in offered} == {"list_documents", "search_evidence"}
    assert chat.evidence.session_id == chat.session.session_id
    assert get_active_session() is None
    assert not (tmp_path / "runtime" / "financials.sqlite3").exists()


def test_allowlist_validates_and_default_preserves_all_tools(tmp_path, data_root):
    chat = backend(tmp_path, data_root, ScriptedModel())
    ask(chat, "Evidence Search", "Hello")
    service = chat.evidence._agent.service
    default = CreditAssessmentAgent(service=service, model=ScriptedModel())
    assert default.document_tool_names is None
    with pytest.raises(ValueError, match="Unknown document tools"):
        CreditAssessmentAgent(service=service, document_tool_names=frozenset({"invented"}))


def test_credit_review_progress_reuse_refresh_and_changed_inputs(tmp_path, data_root):
    model = ScriptedModel()
    chat = backend(tmp_path, data_root, model)
    model.respond.side_effect = [
        model_response(("list_borrowers", {})),
        model_response(("run_credit_review", REVIEW_ARGS)),
        text_response(),
    ]
    updates = []
    first = ask(chat, "Credit Analysis", updates=updates)
    assert first.error is None, first
    assert first.review.status == "complete"
    assert first.review.snapshot.assessment_data["results"][0]["actual_value"] == pytest.approx(
        100 / 32
    )
    assert first.review.snapshot.assessment_data["ml_status"] == "stub"
    assert any(
        {a.key for a in turn.activities if a.state == "running"} >= {"bullish", "bearish"}
        for turn in updates
    )
    assert {a.key for a in first.activities} >= {
        "assessment",
        "bullish",
        "bearish",
        "recommendation",
    }
    original = first.review.review_id
    model.respond.side_effect = [text_response("The supplied headroom is positive.")]
    followup = ask(chat, "Credit Analysis", "Explain that headroom.")
    assert followup.error is None and not followup.tools
    assert chat._review.review_id == original
    model.respond.side_effect = [
        model_response(("run_credit_review", REVIEW_ARGS)),
        text_response(),
    ]
    cached = ask(chat, "Credit Analysis")
    assert cached.review.review_id == original
    model.respond.side_effect = [
        model_response(("run_credit_review", {**REVIEW_ARGS, "refresh": True})),
        text_response(),
    ]
    refreshed = ask(chat, "Credit Analysis", "Refresh the same review.")
    assert refreshed.review.review_id != original
    model.respond.side_effect = [
        model_response(("run_credit_review", {**REVIEW_ARGS, "borrower_id": "SYN002"})),
        text_response(),
    ]
    changed = ask(chat, "Credit Analysis", QUESTION.replace("SYN001", "SYN002"))
    assert changed.review.snapshot.borrower_id == "SYN002"
    assert changed.review.review_id != refreshed.review.review_id
    assert get_active_session() is None


def test_clarification_has_no_assessment_side_effects(tmp_path, data_root):
    chat = backend(
        tmp_path,
        data_root,
        ScriptedModel(
            response=text_response(
                "Please supply a borrower, reporting period, cutoff and credit criteria."
            )
        ),
    )
    result = ask(chat, "Credit Analysis", "Analyze a borrower.")
    assert result.error is None and not result.tools and result.review is None
    assert "Please supply" in result.content
    assert not chat.runtime_dir.exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"borrower_id": "unknown"},
        {"period_end": date(1900, 1, 1)},
        {"information_cutoff": date(2025, 1, 1)},
        {"credit_criteria": [" "]},
    ],
)
def test_invalid_requests_do_not_assess(tmp_path, data_root, changes):
    chat = backend(tmp_path, data_root)
    chat._turn = ChatTurn()
    args = {
        **REVIEW_ARGS,
        "period_end": date(2025, 9, 30),
        "information_cutoff": date(2025, 9, 30),
        **changes,
    }
    with pytest.raises(ModelRetry):
        asyncio.run(chat.run_credit_review(**args))
    assert not (chat.runtime_dir / "analytics.sqlite3").exists()


def test_missing_ml_artifact_retains_deterministic_results(tmp_path, data_root):
    model = ScriptedModel()
    args = {k: v for k, v in REVIEW_ARGS.items() if k != "ml_mode"}
    model.respond.side_effect = [model_response(("run_credit_review", args)), text_response()]
    result = ask(backend(tmp_path, data_root, model), "Credit Analysis")
    assert result.review is not None, result
    data = result.review.snapshot.assessment_data
    assert data["ml_status"] == "failed"
    assert data["results"][0]["actual_value"] == pytest.approx(100 / 32)
    assert data["prediction"]["breach_probability"] is None


def test_post_review_provider_failure_preserves_review_and_valid_history(tmp_path, data_root):
    model = ScriptedModel()
    model.respond.side_effect = [
        model_response(("run_credit_review", REVIEW_ARGS)),
        RuntimeError("provider failure"),
    ]
    chat = backend(tmp_path, data_root, model)
    result = ask(chat, "Credit Analysis")
    assert result.error == "RuntimeError" and result.review is not None
    assert result.finished and not any(a.state == "running" for a in result.activities)
    assert get_active_session() is None
    model.respond.side_effect = [text_response("Please try the request again.")]
    assert ask(chat, "Credit Analysis", "Try again.").error is None


@pytest.mark.parametrize("failed_roles", [("bullish",), ("bullish", "bearish")])
def test_failed_reviewers_preserve_results_and_defer(
    tmp_path, data_root, monkeypatch, failed_roles
):
    import monitoring_backend as module

    original = module.create_credit_review_service

    def fail(messages, info):
        raise RuntimeError("synthetic reviewer failure")

    def factory(**kwargs):
        service = original(**kwargs)
        for role in failed_roles:
            getattr(service, f"{role}_agent").model = FunctionModel(fail)
        return service

    monkeypatch.setattr(module, "create_credit_review_service", factory)
    model = ScriptedModel()
    model.respond.side_effect = [
        model_response(("run_credit_review", REVIEW_ARGS)),
        text_response(),
    ]
    result = ask(backend(tmp_path, data_root, model), "Credit Analysis")
    assert result.error == "credit_review_incomplete"
    assert result.review.recommendation.action == "defer"
    assert result.review.bullish.execution.status == "failed"
    assert result.review.snapshot.assessment_data["results"]
    assert any(a.key == "bullish" and a.state == "error" for a in result.activities)


def test_callback_failure_restores_context(tmp_path, data_root):
    chat = backend(tmp_path, data_root)

    def broken(turn):
        raise RuntimeError("synthetic UI callback failure")

    with pytest.raises(RuntimeError, match="callback"):
        asyncio.run(chat.run_turn("Credit Analysis", QUESTION, ChatTurn(), on_update=broken))
    assert get_active_session() is None and chat._turn is None


def test_cancellation_restores_context_and_releases_session(tmp_path, data_root):
    async def scenario():
        waiting = asyncio.Event()
        started = asyncio.Event()
        model = ScriptedModel()

        async def wait(**kwargs):
            started.set()
            await waiting.wait()

        model.respond.side_effect = wait
        chat = backend(tmp_path, data_root, model)
        turn = ChatTurn()
        task = asyncio.create_task(chat.run_turn("Credit Analysis", QUESTION, turn))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert turn.error == "cancelled" and turn.finished
        assert chat._turn is None and get_active_session() is None
        chat.close()
        with pytest.raises(RuntimeError, match="closed"):
            await chat.run_turn("Credit Analysis", QUESTION, ChatTurn())

    asyncio.run(scenario())
