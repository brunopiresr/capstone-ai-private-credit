"""Deterministic provenance/structure checks, without repairing extracted facts.

These checks cannot prove legal interpretation or semantic entailment. In particular,
exact quote inclusion is necessary evidence verification, not a legal conclusion.
"""

import re
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from pydantic import BaseModel

from credit_monitoring.domain import (
    AllCompanyCovenantExtraction,
    CovenantExtraction,
    RetrievedRecord,
    SourceEvidence,
    ValidationReport,
)

OPERATOR_DIRECTIONS = {
    "<": "maximum",
    "<=": "maximum",
    ">": "minimum",
    ">=": "minimum",
    "=": "other",
    None: "not_stated",
}


def _supported_operator(quote: str) -> str | None:
    """Check unambiguous guide phrases; this does not populate or repair an operator."""
    comparisons = (
        (r"\bless than\b", "<"),
        (r"\bnot exceeding\b", "<="),
        (r"\bgreater than\b", ">"),
        (r"\bat least\b", ">="),
        (r"\bequal to\b", "="),
    )
    explicit = {
        operator for pattern, operator in comparisons if re.search(pattern, quote, re.IGNORECASE)
    }
    explicit.update(re.findall(r"(?<![<>=])(?:<=|>=|<|>|=)(?![<>=])", quote))
    if len(explicit) == 1:
        return explicit.pop()
    if explicit:
        return None
    maximum = re.search(r"\bmaximum\b", quote, re.IGNORECASE)
    minimum = re.search(r"\bminimum\b", quote, re.IGNORECASE)
    if maximum and not minimum:
        return "<="
    if minimum and not maximum:
        return ">="
    return None


def _walk(value: Any, path: str = "") -> Iterable[tuple[str, BaseModel]]:
    if isinstance(value, BaseModel):
        yield path, value
        for name in type(value).model_fields:
            yield from _walk(getattr(value, name), f"{path}.{name}" if path else name)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _walk(item, f"{path}[{i}]")


def _record_checks(records: list[RetrievedRecord], report: ValidationReport) -> None:
    for i, record in enumerate(records):
        path = f"input_records[{i}]"
        if not record.document_id.strip() or not record.citation.strip():
            report.add(
                "error", "empty_source_identity", path, "Source ID and citation must be nonempty."
            )
        if not record.text.strip():
            report.add("warning", "empty_excerpt", path, "The retrieved excerpt is empty.")
        if record.truncated:
            report.add(
                "warning",
                "truncated_source",
                path,
                "Evidence selection truncated this source; "
                "unavailable clauses must remain gaps, not inferred facts.",
            )
        for name in ("source_start", "source_end", "source_length"):
            value = getattr(record, name)
            if value is not None and value < 0:
                report.add(
                    "error", "negative_source_offset", f"{path}.{name}", "Must be nonnegative."
                )
        if record.source_start is not None and record.source_end is not None:
            if record.source_start > record.source_end:
                report.add("error", "source_offset_order", path, "Start offset exceeds end offset.")
        if record.source_length is not None:
            for name in ("source_start", "source_end"):
                value = getattr(record, name)
                if value is not None and value > record.source_length:
                    report.add(
                        "error",
                        "source_offset_bounds",
                        f"{path}.{name}",
                        "Offset exceeds known length in the supplied coordinate system.",
                    )
        if record.offset_coordinate_system == "unknown" and (
            record.source_start is not None or record.source_end is not None
        ):
            report.add(
                "warning",
                "unknown_offset_coordinates",
                path,
                "Offset coordinates are unspecified; Markdown-file bounds cannot be assumed.",
            )


def _verify_evidence(
    evidence: SourceEvidence,
    path: str,
    records: list[RetrievedRecord],
    report: ValidationReport,
) -> None:
    paired = [
        r
        for r in records
        if r.document_id == evidence.document_id and r.citation == evidence.citation
    ]
    if not paired:
        report.add(
            "error",
            "source_pair_mismatch",
            path,
            "Document ID and citation do not match the same supplied record.",
        )
        return
    if not evidence.evidence_quote.strip():
        report.add(
            "error", "empty_evidence_quote", f"{path}.evidence_quote", "Evidence cannot be empty."
        )
        return
    quoted = [r for r in paired if evidence.evidence_quote in r.text]
    if not quoted:
        report.add(
            "error",
            "quote_not_verbatim",
            f"{path}.evidence_quote",
            "Quote is absent verbatim from matching text; review punctuation/Markdown "
            "transformations. Quotes assembled from multiple records are not verified.",
        )
        return
    metadata_fields = ("markdown_path", "source_start", "source_end")
    matching = [
        r for r in quoted if all(getattr(r, n) == getattr(evidence, n) for n in metadata_fields)
    ]
    if not matching:
        report.add(
            "error",
            "source_metadata_mismatch",
            path,
            "Path and offsets must be copied from the same quote-supporting record; "
            "missing metadata must stay null.",
        )
        return
    # Duplicate identical input records do not make provenance ambiguous. Distinct
    # overlapping records do when neither quote nor copied metadata distinguishes them.
    identities = {r.model_dump_json() for r in matching}
    if len(identities) > 1:
        report.add(
            "warning",
            "ambiguous_source_record",
            path,
            "More than one distinct record matches quote and metadata; provenance needs review.",
        )


def _date_in_quote(value: date, quote: str) -> bool:
    """Recognize explicit ISO or English dates; never resolve quarter labels/chronology."""
    if value.isoformat() in quote:
        return True
    months = (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    )
    month = months[value.month - 1]
    pattern = rf"\b(?:{month}|{month[:3]}\.?)\s+0?{value.day}(?:st|nd|rd|th)?\s*,?\s*{value.year}\b"
    return re.search(pattern, quote, re.IGNORECASE) is not None


def validate_extraction(
    extraction: CovenantExtraction,
    records: Iterable[RetrievedRecord | Mapping[str, Any]],
    *,
    catalog_tickers: Iterable[str] = (),
) -> ValidationReport:
    """Return errors/warnings with field paths; never mutate extraction or sources."""
    sources = [RetrievedRecord.from_record(r) for r in records]
    report = ValidationReport()
    _record_checks(sources, report)
    if not sources:
        report.add("warning", "no_evidence", "input_records", "No evidence records were supplied.")
    supplied_tickers = {r.ticker for r in sources if r.ticker} | set(catalog_tickers)
    if extraction.ticker is not None and extraction.ticker not in supplied_tickers:
        report.add(
            "error", "unsupported_ticker", "ticker", "Ticker was not supplied in these records."
        )
    for path, obj in _walk(extraction):
        if isinstance(obj, SourceEvidence):
            _verify_evidence(obj, path, sources, report)
            continue
        for start_name, end_name in (
            ("from_period_end", "through_period_end"),
            ("from_date", "through_date"),
        ):
            start, end = getattr(obj, start_name, None), getattr(obj, end_name, None)
            if start is not None and end is not None and start > end:
                report.add("error", "date_range_order", path, f"{start_name} exceeds {end_name}.")
        evidence = getattr(obj, "evidence", None)
        if evidence is not None:
            for name in ("threshold", "reported_value", "reported_result", "value"):
                value = getattr(obj, name, None)
                if value is not None and value not in evidence.evidence_quote:
                    report.add(
                        "error",
                        "value_not_in_quote",
                        f"{path}.{name}",
                        "Exact source value is not in this object's quote; split sources "
                        "or flag the unsupported combination instead of combining excerpts.",
                    )
            for name in type(obj).model_fields:
                value = getattr(obj, name)
                dates = value if isinstance(value, list) else [value]
                for item in dates:
                    if isinstance(item, date) and not _date_in_quote(item, evidence.evidence_quote):
                        report.add(
                            "warning",
                            "date_support_unverified",
                            f"{path}.{name}",
                            "Date is not recognizable in this supporting quote; review source "
                            "format/applicability or a possible unsupported multi-source fact.",
                        )
    for i, covenant in enumerate(extraction.covenants):
        path = f"covenants[{i}]"
        if covenant.threshold_direction != OPERATOR_DIRECTIONS[covenant.operator]:
            report.add(
                "error",
                "operator_direction_mismatch",
                f"{path}.threshold_direction",
                "Direction does not agree with the extracted operator.",
            )
        if covenant.operator is not None and not covenant.operator_quote:
            report.add(
                "error",
                "missing_operator_quote",
                f"{path}.operator_quote",
                "A populated operator requires a supporting verbatim phrase.",
            )
        if covenant.operator_quote and covenant.operator is not None:
            supported = _supported_operator(covenant.operator_quote)
            if supported is None:
                report.add(
                    "warning",
                    "operator_support_unverified",
                    f"{path}.operator_quote",
                    "Comparison phrase is ambiguous or outside recognized wording; review it.",
                )
            elif supported != covenant.operator:
                report.add(
                    "error",
                    "operator_wording_mismatch",
                    f"{path}.operator",
                    "Operator disagrees with explicit wording or Maximum/Minimum fallback.",
                )
            full_support = _supported_operator(covenant.evidence.evidence_quote)
            if full_support is not None and full_support != covenant.operator:
                report.add(
                    "error",
                    "operator_evidence_mismatch",
                    f"{path}.operator",
                    "The supporting excerpt establishes a different unambiguous comparison; "
                    "explicit wording takes precedence over a Maximum/Minimum label.",
                )
        if (
            covenant.operator_quote
            and covenant.operator_quote not in covenant.evidence.evidence_quote
        ):
            report.add(
                "error",
                "operator_quote_not_supported",
                f"{path}.operator_quote",
                "Operator phrase must be in this covenant's supporting quote.",
            )
        if covenant.operator is None:
            report.add(
                "warning", "missing_operator", f"{path}.operator", "Comparison is not stated."
            )
        if not covenant.threshold_schedule:
            report.add(
                "warning",
                "missing_threshold",
                f"{path}.threshold_schedule",
                "No threshold available; a relevant excerpt-level gap is needed.",
            )
            if not any("threshold" in gap.lower() for gap in extraction.gaps):
                report.add(
                    "warning", "missing_threshold_gap", "gaps", "No threshold gap was recorded."
                )
        name = covenant.metric_definition_name
        if name is not None:
            candidates = [d for d in extraction.financial_metric_definitions if d.name == name]
            if covenant.amendment_reference:
                scoped = [
                    d for d in candidates if d.amendment_reference == covenant.amendment_reference
                ]
                if scoped:
                    candidates = scoped
            if not candidates:
                report.add(
                    "error",
                    "missing_definition_target",
                    f"{path}.metric_definition_name",
                    "No extracted definition has this exact name; do not auto-link similar names.",
                )
            elif len(candidates) > 1:
                report.add(
                    "warning",
                    "ambiguous_definition_link",
                    f"{path}.metric_definition_name",
                    "Multiple versions match; this link needs explicit source review.",
                )
            if name not in covenant.evidence.evidence_quote:
                report.add(
                    "warning",
                    "definition_link_unverified",
                    f"{path}.metric_definition_name",
                    "Definition name is not in the covenant quote; explicit linkage needs review.",
                )
        elif extraction.financial_metric_definitions or "ebitda" in (covenant.metric or "").lower():
            report.add(
                "warning",
                "missing_definition_link",
                f"{path}.metric_definition_name",
                "No explicit contractual metric-definition link was extracted; do not infer it.",
            )
    for i, definition in enumerate(extraction.financial_metric_definitions):
        if definition.definition is None:
            report.add(
                "warning",
                "incomplete_definition",
                f"financial_metric_definitions[{i}].definition",
                "Full contractual definition is unavailable; retain supported adjustments.",
            )
            if not any("definition" in gap.lower() for gap in extraction.gaps):
                report.add(
                    "warning",
                    "missing_definition_gap",
                    "gaps",
                    "No missing-definition gap recorded.",
                )
    for i, warning in enumerate(extraction.extraction_warnings):
        report.add("warning", "source_extraction_warning", f"extraction_warnings[{i}]", warning)
    return report


def validate_all_companies(
    extraction: AllCompanyCovenantExtraction,
    records: Iterable[RetrievedRecord | Mapping[str, Any]],
    company_by_ticker: Mapping[str, str],
) -> ValidationReport:
    """Check coverage and company-specific provenance without selecting governing terms."""
    sources = [RetrievedRecord.from_record(r) for r in records]
    report = ValidationReport()
    _record_checks(sources, report)
    tickers = [company.ticker for company in extraction.companies]
    if len(tickers) != len(set(tickers)):
        report.add(
            "error", "duplicate_company", "companies", "Catalog ticker returned more than once."
        )
    for ticker in sorted(set(company_by_ticker) - set(tickers)):
        report.add("error", "missing_company", "companies", f"Catalog ticker {ticker} is missing.")
    for i, company in enumerate(extraction.companies):
        path = f"companies[{i}]"
        if company.ticker not in company_by_ticker:
            report.add(
                "error", "unexpected_company", f"{path}.ticker", "Ticker is not in the catalog."
            )
        elif company.company != company_by_ticker[company.ticker]:
            report.add(
                "error", "company_name_mismatch", f"{path}.company", "Name differs from catalog."
            )
        if company.extraction.ticker is not None and company.extraction.ticker != company.ticker:
            report.add(
                "error",
                "company_ticker_mismatch",
                f"{path}.extraction.ticker",
                "Nested extraction ticker differs from its batch entry.",
            )
        own_sources = [r for r in sources if r.ticker == company.ticker]
        child = validate_extraction(
            company.extraction,
            own_sources,
            catalog_tickers=[company.ticker] if company.ticker in company_by_ticker else [],
        )
        for issue in child.issues:
            report.add(issue.severity, issue.code, f"{path}.extraction.{issue.path}", issue.message)
    return report
