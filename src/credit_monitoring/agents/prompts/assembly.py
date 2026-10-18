"""JSON input envelopes shared by narrative and structured extraction callers."""

import json
from collections.abc import Iterable, Mapping
from typing import Any

from credit_monitoring.domain import RetrievedRecord


def build_prompt(
    query: str,
    search_results: Iterable[RetrievedRecord | Mapping[str, Any]],
    *,
    include_catalog_notes: bool = True,
) -> str:
    """Encode question and records as JSON so excerpts cannot break text delimiters."""
    records = [RetrievedRecord.from_record(r).envelope() for r in search_results]
    if not include_catalog_notes:
        # Descriptive notes can contain benchmark-like answers; extraction must
        # obtain financial facts from source text, not catalog summaries.
        for record in records:
            record["catalog_context"].pop("notes", None)
    return json.dumps(
        {"question": query, "retrieved_records": records}, ensure_ascii=False, indent=2
    )
