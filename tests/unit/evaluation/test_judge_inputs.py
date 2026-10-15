"""Capture actual application contracts without Evidently or model requests."""

import json

from credit_monitoring.domain import (
    AllCompanyCovenantExtraction,
    AllCompanyExtractionResult,
    CovenantExtraction,
    ExtractionResult,
    RetrievedRecord,
    SourceReference,
)
from credit_monitoring.domain.agent import AgentAnswer, ToolExecution
from credit_monitoring.evaluation.judge_inputs import (
    capture_answer,
    capture_extraction,
    capture_retrieval,
    write_judge_inputs,
)


def test_extraction_uses_original_source_not_catalog_notes(synthetic_records):
    record = {**synthetic_records["base"], "notes": "BENCHMARK ANSWER DO NOT SEND"}
    result = ExtractionResult(prompt_version="test", extraction=CovenantExtraction())
    captured = capture_extraction("case", "Extract terms", result, [record])
    assert captured["context"][0]["text"] == record["content"]
    assert "BENCHMARK ANSWER" not in json.dumps(captured)
    assert json.loads(captured["output"]) == result.extraction.model_dump(mode="json")


def test_retrieval_preserves_order_and_empty_results(synthetic_records):
    records = [synthetic_records["open"], synthetic_records["base"]]
    captured = capture_retrieval("case", "Find thresholds", records)
    assert [p["document_id"] for p in captured["context"]] == ["SYN_OPEN", "SYN_BASE"]
    assert capture_retrieval("empty", "Find thresholds", [])["output"] == "[]"


def test_batch_extraction_preserves_company_grouping():
    result = AllCompanyExtractionResult(
        prompt_version="batch-test",
        extraction=AllCompanyCovenantExtraction(
            summary="No evidence for the catalog company.",
            companies=[
                {
                    "company": "Synthetic Issuer",
                    "ticker": "SYN",
                    "extraction": CovenantExtraction(gaps=["No evidence."]),
                }
            ],
        ),
    )
    captured = capture_extraction("batch", "Extract all companies", result, [])
    assert json.loads(captured["output"])["companies"][0]["ticker"] == "SYN"


def test_answer_preserves_actual_trace_and_marks_incomplete_outputs(synthetic_records, tmp_path):
    answer = AgentAnswer(
        answer="Supported answer",
        confidence="medium",
        confidence_explanation="Limited supporting evidence.",
        tool_trace=[
            ToolExecution(
                call_id="call",
                name="search_evidence",
                arguments={"query": "threshold"},
                outcome=[RetrievedRecord.from_record(synthetic_records["base"])],
                sources=[
                    SourceReference(
                        document_id=synthetic_records["base"]["document_id"],
                        citation=synthetic_records["base"]["citation"],
                    )
                ],
            )
        ],
    )
    captured = capture_answer("case", "What threshold?", answer, [synthetic_records["base"]])
    assert captured["tool_trace"][0] == answer.tool_trace[0].model_dump(mode="json")
    assert captured["tool_trace"][0]["outcome"][0]["text"] == synthetic_records["base"]["content"]
    assert (
        captured["tool_trace"][0]["sources"][0]["document_id"]
        == synthetic_records["base"]["document_id"]
    )
    assert captured["metadata"]["complete"] is True
    assert captured["metadata"]["confidence"] == "medium"
    assert captured["metadata"]["confidence_explanation"] == "Limited supporting evidence."
    path = tmp_path / "domain-answer.jsonl"
    write_judge_inputs(path, [captured])
    assert json.loads(path.read_text()) == captured
    incomplete = answer.model_copy(update={"complete": False, "error": "tool_round_limit"})
    assert capture_answer("case", "Question", incomplete, [])["output"] is None


def test_plain_rag_or_narrator_answer_and_jsonl_roundtrip(tmp_path, synthetic_records):
    captured = capture_answer("case", "What threshold?", "5.00x", [synthetic_records["base"]])
    path = tmp_path / "cases.jsonl"
    write_judge_inputs(path, [captured])
    assert json.loads(path.read_text()) == captured
