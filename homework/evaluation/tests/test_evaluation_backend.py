"""Exercise source readiness, isolated attempts, persistence and feedback telemetry."""

import asyncio
import hashlib
import json
from contextlib import nullcontext

import evaluation_backend as backend
import pytest


def test_all_27_questions_have_prepared_sources_and_restored_exhibit_provenance():
    cases = backend.load_cases()
    assert len(cases) == 27
    assert not {
        c["case_id"]: missing for c in cases if (missing := backend.workbench.missing_sources(c))
    }
    manifest = json.loads((backend.DATASET / "data/manifest.json").read_text())
    restored = [s for s in manifest["sources"] if s["kind"] == "additional_official_sec_exhibit"]
    assert len(restored) == 2 and manifest["additions"]["official_exhibits_ready"] == 2
    for source in restored:
        assert source["availability"] == "ready"
        for name, details in source["files"].items():
            content = (backend.DATASET / "data" / name).read_bytes()
            assert len(content) == details["bytes"]
            assert hashlib.sha256(content).hexdigest() == details["sha256"]
    references = backend.workbench.by_id(
        backend.workbench.read_rows(backend.DATASET / "references.jsonl")
    )
    for key in ("E09", "P05"):
        assert references[key]["passages"]
        assert not any(c.startswith("SESSION SOURCE GAP:") for c in references[key]["criteria"])
        for passage in references[key]["passages"]:
            source = backend.DATASET / "data/markdown" / f"{passage['document_id']}.md"
            assert (
                source.read_text()[passage["source_start"] : passage["source_end"]]
                == passage["text"]
            )


def test_answers_are_reused_and_feedback_is_bound_to_exact_response(tmp_path, agent_calls):
    current = backend.EvaluationRound(output_root=tmp_path)
    answer = asyncio.run(current.generate())
    assert asyncio.run(current.generate()) is answer
    assert len(agent_calls) == 1
    for invalid in (None, 0, "direct", "unknown"):
        with pytest.raises(ValueError, match="Choose a response category"):
            current.rate(invalid, "Comment")
    assert current.index == 0
    current.rate("incorrect", "The calculation needs checking.")
    feedback = json.loads((answer.folder / "feedback.json").read_text())
    assert feedback["category"] == "incorrect" and "rating" not in feedback
    assert feedback["comment"] == "The calculation needs checking."
    assert feedback["case_id"] == "E01"
    assert feedback["interaction_id"] == answer.interaction_id
    assert feedback["response_sha256"] == backend.workbench.fingerprint(
        answer.folder / "answer.json"
    )
    assert current.index == 1 and current.attempt is None
    with pytest.raises(ValueError, match="Generate a complete"):
        current.rate("correct", "")
    second = asyncio.run(current.generate())
    assert second.folder != answer.folder
    rows = current.summary()
    assert [row["case_id"] for row in rows] == ["E01", "E02"]
    assert all("answer" not in row and "question" not in row for row in rows)
    assert rows[0]["category"] == "incorrect"
    assert rows[0]["comment"] == "The calculation needs checking."
    assert rows[0]["submitted"]
    assert rows[1]["category"] is None and not rows[1]["submitted"]
    assert len(agent_calls) == 2
    other = backend.EvaluationRound(output_root=tmp_path)
    assert other.index == 0 and other.folder != current.folder
    assert other.summary() == [
        {"case_id": "E01", "category": None, "comment": "", "submitted": False, "status": "not_run"}
    ]


def test_mixed_ratings_and_skips_preserve_order_and_do_not_rate_skipped_answers(
    tmp_path, agent_calls
):
    current = backend.EvaluationRound(output_root=tmp_path, cases=backend.load_cases()[:3])
    current.skip()
    assert current.index == 1 and not agent_calls
    assert current.summary()[0]["status"] == "skipped"
    asyncio.run(current.generate())
    current.rate("correct", "Reviewed")
    attempt = asyncio.run(current.generate())
    current.skip()
    assert current.complete and current._ended and len(agent_calls) == 2
    rows = current.summary()
    assert [row["case_id"] for row in rows] == ["E01", "E02", "E03"]
    assert rows[0]["status"] == rows[2]["status"] == "skipped"
    assert rows[1]["category"] == "correct" and rows[1]["comment"] == "Reviewed"
    assert sum(row["submitted"] for row in rows) == 1
    assert not (attempt.folder / "feedback.json").exists()
    assert len(list(current.folder.glob("**/feedback.json"))) == 1
    assert len(list(current.folder.glob("*/skip.json"))) == 2
    with pytest.raises(ValueError, match="round is complete"):
        current.skip()


@pytest.mark.parametrize("capture_content", [False, True])
def test_logfire_feedback_and_generation_share_identity(
    tmp_path, monkeypatch, agent_calls, capture_content
):
    records = []
    monkeypatch.setattr(backend, "is_observability_configured", lambda: True)
    monkeypatch.setattr(backend, "session_scope", lambda _: nullcontext())
    monkeypatch.setattr(backend, "capture_content_enabled", lambda: capture_content)
    monkeypatch.setattr(backend.logfire, "info", lambda message, **fields: records.append(fields))
    current = backend.EvaluationRound(output_root=tmp_path)
    answer = asyncio.run(current.generate())
    current.rate("correct", "Helpful explanation")
    events = {record["event_name"]: record for record in records}
    feedback = events["user.feedback"]
    presented = events["evaluation.answer_presented"]
    assert feedback["chat_id"] == presented["chat_id"] == current.session.session_id
    assert feedback["interaction_id"] == presented["interaction_id"] == answer.interaction_id
    assert feedback["case_id"] == presented["case_id"] == "E01"
    assert feedback["category"] == "correct" and feedback["has_comment"]
    assert "rating" not in feedback
    assert ("comment" in feedback) is capture_content
    assert ("question" in events["evaluation.question_started"]) is capture_content


def test_missing_sources_do_not_call_model_and_explicit_retry_uses_new_attempt(
    tmp_path, monkeypatch, agent_calls
):
    current = backend.EvaluationRound(output_root=tmp_path)
    monkeypatch.setattr(backend.workbench, "missing_sources", lambda _: ["MISSING"])
    failed = asyncio.run(current.generate())
    assert not failed.answer["complete"] and "MISSING" in failed.answer["error"]
    assert not agent_calls
    with pytest.raises(ValueError, match="Generate a complete"):
        current.rate("incorrect", "")
    monkeypatch.setattr(backend.workbench, "missing_sources", lambda _: [])
    current.retry()
    success = asyncio.run(current.generate())
    assert success.folder != failed.folder and len(agent_calls) == 1
    assert current.index == 0


def test_feedback_write_failure_preserves_answer_and_progress(tmp_path, monkeypatch, agent_calls):
    current = backend.EvaluationRound(output_root=tmp_path)
    attempt = asyncio.run(current.generate())
    original = backend.workbench.save

    def failed_save(path, value):
        if path.name == "feedback.json":
            raise OSError("Storage unavailable")
        original(path, value)

    monkeypatch.setattr(backend.workbench, "save", failed_save)
    with pytest.raises(OSError, match="Storage unavailable"):
        current.rate("correct", "")
    assert current.index == 0 and current.attempt is attempt
    assert len(agent_calls) == 1
