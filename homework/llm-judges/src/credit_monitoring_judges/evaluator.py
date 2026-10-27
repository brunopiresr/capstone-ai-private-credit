"""Run real Evidently descriptors and retain evaluation coverage and failures."""

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import pandas as pd
from evidently import DataDefinition, Dataset, Report
from evidently.descriptors import LLMEval
from evidently.llm.models import LLMMessage
from evidently.llm.templates import MulticlassClassificationPromptTemplate
from evidently.presets import TextEvals

from credit_monitoring_judges.models import JudgeCase, JudgeKind, JudgeResult
from credit_monitoring_judges.prompts import CATEGORIES, CRITERIA, RUBRIC_VERSION, SYSTEM_MESSAGE


def make_descriptor(kind: JudgeKind, model: str):
    """One call yields both a category and a concise explanation."""
    template = MulticlassClassificationPromptTemplate(
        criteria=CRITERIA[kind],
        category_criteria=CATEGORIES,
        uncertainty="insufficient_evidence",
        include_reasoning=True,
        include_score=False,
        pre_messages=[LLMMessage.system(SYSTEM_MESSAGE)],
    )
    return LLMEval(
        "output",
        provider="openai",
        model=model,
        template=template,
        additional_columns={
            name: name for name in ("question", "context", "tool_trace", "reference", "metadata")
        },
        alias="judgment",
    )


def prompt_row(case: JudgeCase) -> dict[str, str]:
    """Keep manual labels and case IDs outside the judge prompt."""
    return {
        "output": case.output or "",
        "question": case.question,
        "context": json.dumps([p.model_dump(exclude_none=True) for p in case.context]),
        "tool_trace": json.dumps(case.tool_trace),
        "reference": case.reference or "Not supplied.",
        "metadata": json.dumps(case.metadata),
    }


def evaluate_case(case: JudgeCase, *, model: str, max_input_chars: int) -> JudgeResult:
    common = {
        "case_id": case.case_id,
        "judge": case.judge,
        "expected_label": case.expected_label,
    }
    if case.output is None or not case.output.strip():
        return JudgeResult(
            **common, status="skipped", reason="No completed method output was captured."
        )
    row = prompt_row(case)
    if sum(map(len, row.values())) > max_input_chars:
        return JudgeResult(
            **common,
            status="skipped",
            reason="Input exceeds max_input_chars; no evidence was silently truncated.",
        )
    try:
        dataset = Dataset.from_pandas(
            pd.DataFrame([row]),
            data_definition=DataDefinition(),
            descriptors=[make_descriptor(case.judge, model)],
        )
        scored = dataset.as_dataframe().iloc[0]
        label = scored["judgment"]
        reason = scored["judgment reasoning"]
        if label not in CATEGORIES or not isinstance(reason, str) or not reason.strip():
            return JudgeResult(
                **common, status="error", reason="Judge returned an invalid label or explanation."
            )
        return JudgeResult(**common, status="evaluated", label=label, reason=reason)
    except Exception as error:
        # Provider errors can include request bodies. Keep snapshots/reports free of credentials.
        return JudgeResult(
            **common,
            status="error",
            reason=f"Evidently evaluation failed ({type(error).__name__}).",
        )


def summarize(results: list[JudgeResult]) -> dict:
    summary = {"total": len(results), "by_judge": {}}
    for kind in ("extraction", "retrieval", "answer"):
        selected = [result for result in results if result.judge == kind]
        evaluated = [result for result in selected if result.status == "evaluated"]
        decisive = [result for result in evaluated if result.label in ("pass", "fail")]
        calibration = [result for result in evaluated if result.expected_label is not None]
        summary["by_judge"][kind] = {
            "total": len(selected),
            "statuses": dict(Counter(result.status for result in selected)),
            "labels": dict(Counter(result.label for result in evaluated)),
            "decisive_coverage": len(decisive) / len(selected) if selected else None,
            "pass_rate": (
                sum(result.label == "pass" for result in decisive) / len(decisive)
                if decisive
                else None
            ),
            "calibration_cases": len(calibration),
            "manual_label_agreement": (
                sum(result.label == result.expected_label for result in calibration)
                / len(calibration)
                if calibration
                else None
            ),
        }
    return summary


def write_artifacts(
    directory: Path,
    cases: list[JudgeCase],
    results: list[JudgeResult],
    *,
    model: str,
    input_path: Path,
    max_input_chars: int,
) -> None:
    """Build a local Evidently report without re-running any LLM descriptors."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "inputs.jsonl").write_text(
        "".join(case.model_dump_json() + "\n" for case in cases), encoding="utf-8"
    )
    (directory / "results.jsonl").write_text(
        "".join(result.model_dump_json() + "\n" for result in results), encoding="utf-8"
    )
    (directory / "summary.json").write_text(
        json.dumps(summarize(results), indent=2) + "\n", encoding="utf-8"
    )
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "evidently_version": version("evidently"),
        "provider": "openai",
        "model": model,
        "rubric_version": RUBRIC_VERSION,
        "rubrics": CRITERIA,
        "categories": CATEGORIES,
        "system_message": SYSTEM_MESSAGE,
        "input_file": str(input_path.resolve()),
        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "max_input_chars": max_input_chars,
        "case_count": len(cases),
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    frame = pd.DataFrame([result.model_dump() for result in results]).fillna("not_evaluated")
    dataset = Dataset.from_pandas(
        frame,
        data_definition=DataDefinition(
            categorical_columns=["judge", "status", "label"], text_columns=["reason"]
        ),
    )
    snapshot = Report([TextEvals(columns=["judge", "status", "label"])]).run(dataset, None)
    snapshot.save_html(str(directory / "report.html"))
    (directory / "report.json").write_text(snapshot.json(), encoding="utf-8")
