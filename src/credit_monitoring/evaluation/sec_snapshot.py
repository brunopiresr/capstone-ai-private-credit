"""Freeze selected cache states and report public comparison coverage without model calls."""

import csv
import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from credit_monitoring.domain import ExtractionResult
from credit_monitoring.evaluation.sec_gold import validate_gold_case


def content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def encoded(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str) + "\n"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def capture_snapshot(database: Path, catalog: Path, source_directory: Path) -> dict:
    """Select newest state, including failures, never an older successful fallback."""
    database = database.resolve()
    if not database.is_file():
        raise FileNotFoundError(f"Extraction database does not exist: {database}")
    catalog_records = {row["document_id"]: row for row in read_csv(catalog)}
    documents = {}
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT * FROM document_extractions ORDER BY updated_at DESC, cache_key DESC"
        )
        for row in rows:
            document_id = row["document_id"]
            if document_id in documents:
                continue
            source = source_directory / f"{document_id}.md"
            source_exists = bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", document_id))
            source_exists = source_exists and source.is_file()
            result = json.loads(row["result_json"]) if row["result_json"] else None
            documents[document_id] = {
                "cache_key": row["cache_key"],
                "status": row["status"],
                "updated_at": row["updated_at"],
                "total_sections": row["total_sections"],
                "metadata": json.loads(row["metadata_json"]),
                "configuration": json.loads(row["configuration_json"]),
                "result": result,
                "error": row["error"],
                "payload_sha256": content_hash(encoded(result).encode()) if result else None,
                "source_url": catalog_records.get(document_id, {}).get("source_url"),
                "source_available": source_exists,
                "source_sha256": content_hash(source.read_bytes()) if source_exists else None,
            }
    return {
        "snapshot_version": 1,
        "selection": "Newest updated_at, then cache_key descending; latest failed state retained.",
        "database_sha256": content_hash(database.read_bytes()),
        "documents": documents,
    }


def compare_snapshot(snapshot: dict, gold_cases: list[dict], *, strict: bool = False) -> dict:
    """Report unsupported targets separately from supported-fact acceptance."""
    if snapshot.get("snapshot_version") != 1:
        raise ValueError("Unsupported observation snapshot version.")
    extractions = {}
    for document_id, document in snapshot["documents"].items():
        payload = document["result"]
        if payload and content_hash(encoded(payload).encode()) != document["payload_sha256"]:
            raise ValueError(f"Observation checksum mismatch: {document_id}")
        if document["status"] == "complete" and payload:
            extractions[document_id] = ExtractionResult.model_validate(payload).extraction
    cases = []
    for gold in gold_cases:
        comparison = validate_gold_case(gold, extractions)
        source_ids = set(gold["source_document_ids"].split(";"))
        observed = bool(source_ids & extractions.keys())
        required = {"ticker", "borrower", "covenant_name", "covenant_type", "source_document_ids"}
        required |= {"test_date", "threshold_value", "operator"} & comparison.checks.keys()
        missing_required = sorted(required & comparison.missing.keys())
        failed = bool(comparison.mismatches or missing_required)
        if not comparison.missing_source_documents:
            failed = failed or bool(comparison.missing)
        if strict and comparison.missing_source_documents:
            failed = True
        status = (
            "unevaluable"
            if not observed
            else "failed"
            if failed
            else "partial"
            if comparison.missing_source_documents or comparison.missing
            else "supported_facts_match"
        )
        cases.append(
            {
                **comparison.__dict__,
                "status": status,
                "missing_required": missing_required,
                "is_complete": comparison.is_complete,
                "selected_cache_keys": {
                    key: snapshot["documents"][key]["cache_key"]
                    for key in sorted(source_ids & snapshot["documents"].keys())
                },
            }
        )
    statuses = Counter(case["status"] for case in cases)
    field_counts = Counter(check["status"] for case in cases for check in case["checks"].values())
    evaluable = len(cases) - statuses["unevaluable"]
    success = bool(evaluable) and not statuses["failed"]
    if strict and statuses["unevaluable"]:
        success = False
    return {
        "strict_sources": strict,
        "success": success,
        "case_count": len(cases),
        "evaluable_case_count": evaluable,
        "case_status_counts": dict(statuses),
        "field_count": sum(field_counts.values()),
        "field_status_counts": dict(field_counts),
        "unsupported_field_count": sum(len(case["unsupported"]) for case in cases),
        "cases": cases,
    }


def render_report(report: dict) -> str:
    lines = [
        "# Public SEC snapshot comparison",
        "",
        f"Evaluable cases: {report['evaluable_case_count']} / {report['case_count']}.",
        f"Case statuses: {report['case_status_counts']}.",
        f"Field statuses: {report['field_status_counts']}.",
        f"Unsupported target fields: {report['unsupported_field_count']}.",
        "",
        "Partial matches do not establish complete extraction accuracy.",
        "",
        "| Case | Status | Mismatches | Missing facts | Missing sources | Unsupported |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for case in report["cases"]:

        def fields(status: str) -> str:
            return ", ".join(
                key for key, check in case["checks"].items() if check["status"] == status
            )

        lines.append(
            f"| {case['case_id']} | {case['status']} | {fields('mismatch')} | "
            f"{fields('missing')} | {', '.join(case['missing_source_documents'])} | "
            f"{', '.join(case['unsupported'])} |"
        )
    return "\n".join(lines) + "\n"
