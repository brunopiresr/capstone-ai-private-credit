"""MinSearch index and ranked retrieval for existing SEC evidence records."""

from typing import Any

from minsearch import Index


def build_index(documents: list[dict[str, Any]]) -> Index | None:
    if not documents:
        return None
    index = Index(
        text_fields=["company", "ticker", "document_type", "role", "notes", "content"],
        keyword_fields=["document_id", "company", "ticker", "document_type", "role", "period_end"],
    )
    index.fit(documents)
    return index


def search(
    query: str, *, index: Index | None, document_count: int, ticker: str | None = None
) -> list[dict[str, Any]]:
    if index is None or document_count == 0:
        return []
    ranked_records = index.search(
        query,
        filter_dict={"ticker": ticker} if ticker else None,
        num_results=document_count,
    )
    results, records_per_filing = [], {}
    for record in ranked_records:
        document_id = record["document_id"]
        if records_per_filing.get(document_id, 0) < 2:
            results.append(record)
            records_per_filing[document_id] = records_per_filing.get(document_id, 0) + 1
    return results
