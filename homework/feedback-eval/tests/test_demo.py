"""Meaningful demo checks; all model responses and Logfire data stay offline."""

import json
import sys
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from streamlit.testing.v1 import AppTest

DEMO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_DIR))
import backend as be  # noqa: E402


def approved(**kwargs):
    return be.Case(
        case_id="one",
        question="Status?",
        answer="Waived [S1].",
        evidence="S1: test waived",
        expected="Waived, not compliant; cite S1.",
        status="approved",
        reviewer="Test reviewer",
        **kwargs,
    )


def test_import_native_logfire_deduplicates_reviews_and_does_not_guess():
    def record(attrs, trace="t1"):
        return {"trace_id": trace, "attributes": json.dumps(attrs)}

    feedback = record(
        {
            "interaction_id": "i1",
            "event_name": "user.feedback",
            "feedback_id": "r1",
            "comment": "Not compliant",
        }
    )
    rows = [
        feedback,
        feedback,
        record(
            {
                "gen_ai.input.messages": json.dumps(
                    [
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "type": "text",
                                    "content": '{"question":"Status?","borrower_id":"DEMO"}',
                                }
                            ],
                        },
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "type": "tool_call_response",
                                    "name": "assess",
                                    "result": {"status": "waived"},
                                }
                            ],
                        },
                    ]
                ),
                "gen_ai.output.messages": [
                    {"role": "assistant", "parts": [{"type": "text", "content": "Compliant"}]}
                ],
            }
        ),
        record(
            {"interaction_id": "orphan", "event_name": "user.feedback", "feedback_id": "r2"}, "t2"
        ),
    ]
    cases = be.import_cases(json.dumps({"rows": rows}))
    assert len(cases) == 2
    assert cases[0].question == "Status?"
    assert cases[0].answer == "Compliant"
    assert "waived" in cases[0].evidence
    assert len(cases[0].reviews) == 1
    assert cases[0].status == "pending"
    assert cases[1].question == cases[1].answer == cases[1].evidence == ""


def test_shared_trace_is_not_attached_to_arbitrary_turn():
    rows = [
        {"trace_id": "t1", "attributes": {"interaction_id": iid, "event_name": "user.feedback"}}
        for iid in ("i1", "i2")
    ]
    rows.append({"trace_id": "t1", "attributes": {"answer": "ambiguous answer"}})
    assert all(not c.answer for c in be.import_cases(json.dumps(rows)))


def test_approval_and_split_validation(tmp_path):
    case = approved(group="family")
    path = tmp_path / "cases.jsonl"
    with pytest.raises(ValueError, match="approval needs"):
        be.save_cases(path, [case.model_copy(update={"evidence": ""})])
    with pytest.raises(ValueError, match="both dev and holdout"):
        be.save_cases(path, [case, case.model_copy(update={"case_id": "two", "split": "holdout"})])
    be.save_cases(path, [case])
    assert be.load_cases(path) == [case]
    assert be.import_cases(path.read_text())[0].status == "pending"


@pytest.mark.asyncio
async def test_fresh_comparison_hides_references_and_preserves_judge_errors(tmp_path):
    packets = []

    async def caller(model, prompt, packet, output_type=str):
        packets.append((prompt, packet))
        if output_type is str:
            assert "expected" not in packet and "answer" not in packet and "reviews" not in packet
            return {"output": "Waived [S1].", "input_tokens": 10, "output_tokens": 5}
        if len(packets) == 4:
            raise RuntimeError("provider unavailable")
        assert packet["expected"] == approved().expected
        return {
            "output": be.Grade(label="pass", reason="Correctly says waived", excerpt="Waived [S1].")
        }

    configs = [
        {"name": "A", "model": "mock", "prompt": "a"},
        {"name": "B", "model": "mock", "prompt": "b"},
    ]
    folder = await be.run_evaluation(
        [approved(), approved().model_copy(update={"case_id": "pending", "status": "pending"})],
        configs,
        caller=caller,
        output_root=tmp_path,
    )
    summary = json.loads((folder / "summary.json").read_text())
    assert len(packets) == 4
    assert summary[0]["pass_rate"] == 1
    assert summary[1]["error"] == 1 and summary[1]["pass_rate"] == 0
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["status"] == "complete" and manifest["max_requests"] == 4
    assert (folder / "REPORT.md").exists()


@pytest.mark.asyncio
async def test_captured_mode_and_excerpt_validation(tmp_path):
    async def caller(model, prompt, packet, output_type=str):
        assert output_type is be.Grade
        return {"output": be.Grade(label="pass", reason="Wrong excerpt", excerpt="invented")}

    folder = await be.run_evaluation(
        [approved()], [{"name": "Captured"}], captured=True, caller=caller, output_root=tmp_path
    )
    row = json.loads((folder / "results.jsonl").read_text())
    assert row["label"] == "error" and row["stage"] == "judge"
    assert "excerpt" in row["reason"]


@pytest.mark.asyncio
async def test_real_agent_adapter_with_scripted_model():
    async def reply(messages, info):
        if info.output_tools:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {
                            "label": "pass",
                            "reason": "Matches",
                            "excerpt": "Waived",
                        },
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("Waived")])

    model = FunctionModel(reply)
    generated = await be.call_model(model, "Answer", {"question": "Status?"})
    judged = await be.call_model(model, be.RUBRIC, {"answer": generated["output"]}, be.Grade)
    assert generated["output"] == "Waived"
    assert judged["output"].label == "pass"


def test_review_ui_persists_approval_and_rejects_empty_reviewer(tmp_path, monkeypatch):
    monkeypatch.setattr(be, "DATA", tmp_path)
    app = AppTest.from_file(str(DEMO_DIR / "app.py"), default_timeout=15).run()
    assert not app.exception
    next(b for b in app.button if b.label == "Load 4 demo cases").click().run()
    assert len(be.load_cases(tmp_path / "cases.jsonl")) == 4
    next(s for s in app.selectbox if s.label == "Status").select("approved")
    next(b for b in app.button if b.label == "Save review").click().run()
    assert any("approval needs" in e.value for e in app.error)
    next(t for t in app.text_input if t.label == "Reviewer").set_value("Demo reviewer")
    next(b for b in app.button if b.label == "Save review").click().run()
    assert not app.exception
    assert be.load_cases(tmp_path / "cases.jsonl")[0].status == "approved"
    # A browser rerun reads the saved reference; importing the demo preserves it.
    next(b for b in app.button if b.label == "Load 4 demo cases").click().run()
    assert be.load_cases(tmp_path / "cases.jsonl")[0].reviewer == "Demo reviewer"

    original_run = be.run_evaluation

    async def caller(model, prompt, packet, output_type=str):
        if output_type is str:
            return {"output": "Waived [S1]."}
        return {"output": be.Grade(label="fail", reason="Missing actual ratio and limit.")}

    async def offline_run(*args, **kwargs):
        return await original_run(*args, **kwargs, caller=caller)

    monkeypatch.setattr(be, "run_evaluation", offline_run)
    app.checkbox[0].check()
    next(b for b in app.button if b.label == "Run evaluation").click().run()
    assert not app.exception
    assert len(app.dataframe) == 1
    assert app.dataframe[0].value.iloc[0]["fail"] == 1
    assert len(list((tmp_path / "runs").glob("*/REPORT.md"))) == 1
    app.checkbox[0].uncheck()
    next(b for b in app.button if b.label == "Run evaluation").click().run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 2
    next(s for s in app.selectbox if s.label == "Preferred configuration").select("Candidate")
    next(t for t in app.text_area if t.label == "Why keep this configuration?").set_value(
        "Demonstration decision; inspect failures before choosing a configuration."
    )
    next(b for b in app.button if b.label == "Save tuning decision").click().run()
    assert not app.exception
    decision = next((tmp_path / "runs").glob("*/decision.json"))
    assert json.loads(decision.read_text())["configuration"] == "Candidate"
