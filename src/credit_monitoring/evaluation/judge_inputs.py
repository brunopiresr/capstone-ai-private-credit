"""Adapt project outputs to portable snapshots consumed by the isolated judges."""

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from credit_monitoring.domain import AllCompanyExtractionResult, ExtractionResult, RetrievedRecord
from credit_monitoring.domain.agent import AgentAnswer


def _passages(records: Iterable[RetrievedRecord | Mapping[str, Any]]) -> list[dict]:
    passages = []
    for value in records:
        record = RetrievedRecord.from_record(value)
        # Catalog notes can contain benchmark answers. They are not filing evidence.
        passages.append(
            {
                name: getattr(record, name)
                for name in (
                    "document_id",
                    "citation",
                    "text",
                    "ticker",
                    "source_start",
                    "source_end",
                )
            }
        )
    return passages


def capture_extraction(
    case_id: str,
    question: str,
    result: ExtractionResult | AllCompanyExtractionResult,
    records: Iterable[RetrievedRecord | Mapping[str, Any]],
) -> dict:
    """Capture section or document results with their actual original source scope."""
    return {
        "case_id": case_id,
        "judge": "extraction",
        "question": question,
        "output": result.extraction.model_dump_json(),
        "context": _passages(records),
        "metadata": {"prompt_version": result.prompt_version},
    }


def capture_retrieval(
    case_id: str,
    question: str,
    records: Iterable[RetrievedRecord | Mapping[str, Any]],
) -> dict:
    """Retain returned order; reference evidence may be added separately by evaluators."""
    passages = _passages(records)
    return {
        "case_id": case_id,
        "judge": "retrieval",
        "question": question,
        "output": json.dumps(passages, ensure_ascii=False),
        "context": passages,
    }


def capture_answer(
    case_id: str,
    question: str,
    answer: AgentAnswer | str,
    records: Iterable[RetrievedRecord | Mapping[str, Any]],
) -> dict:
    """Capture an agent/RAG/narrator answer with source text, not just source IDs."""
    captured = {
        "case_id": case_id,
        "judge": "answer",
        "question": question,
        "output": answer.answer if isinstance(answer, AgentAnswer) else answer,
        "context": _passages(records),
        "tool_trace": [],
        "metadata": {},
    }
    if isinstance(answer, AgentAnswer):
        captured["tool_trace"] = [item.model_dump(mode="json") for item in answer.tool_trace]
        captured["metadata"] = {"complete": answer.complete, "error": answer.error}
        if not answer.complete:
            captured["output"] = None
    return captured


def write_judge_inputs(path: Path, cases: Iterable[Mapping[str, Any]]) -> None:
    """Write explicit snapshots; this never runs generation or judging."""
    path.write_text(
        "".join(json.dumps(dict(case), ensure_ascii=False) + "\n" for case in cases),
        encoding="utf-8",
    )
