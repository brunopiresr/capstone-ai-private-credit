"""Ranking preservation and two-per-filing cap; no new retrieval infrastructure."""

from unittest.mock import Mock

from credit_monitoring.retrieval.lexical.sec import build_index, search


def test_search_keeps_two_best_records_per_filing_and_filters_ticker():
    ranked = [{"document_id": "SYN_A", "content": str(i)} for i in range(3)]
    ranked.append({"document_id": "SYN_B", "content": "other"})
    index = Mock()
    index.search.return_value = ranked
    results = search("leverage", index=index, document_count=4, ticker="SYN")
    assert results == [ranked[0], ranked[1], ranked[3]]
    index.search.assert_called_once_with("leverage", filter_dict={"ticker": "SYN"}, num_results=4)


def test_empty_corpus_has_no_index_or_results():
    assert build_index([]) is None
    assert search("leverage", index=None, document_count=0) == []


def test_real_index_selects_covenant_over_decoys_and_excludes_other_issuer():
    from credit_monitoring.retrieval.lexical.local import LocalEvidenceSearch

    def record(document_id, ticker, content):
        return {
            "document_id": document_id,
            "ticker": ticker,
            "company": ticker,
            "document_type": "Agreement",
            "role": "fixture",
            "notes": "",
            "period_end": "2025-09-30",
            "content": content,
            "citation": document_id,
            "offset_coordinate_system": "markdown",
        }

    documents = [
        record("A_COV", "AAA", "Maximum total leverage ratio must not exceed 5.00 to 1.00."),
        record("A_DECOY", "AAA", "The company leases office space and markets seasonal products."),
        record(
            "B_COV", "BBB", "Maximum total leverage ratio leverage ratio leverage covenant 9.00."
        ),
    ]
    searcher = LocalEvidenceSearch()
    results = searcher.search(documents, "maximum total leverage ratio", "AAA")
    assert results[0]["document_id"] == "A_COV"
    assert all(item["ticker"] == "AAA" for item in results)
    assert all(item["document_id"] != "B_COV" for item in results)
    # Corpus membership and metadata changes invalidate the retained index as well as text.
    documents[0]["ticker"] = "BBB"
    assert all(
        item["document_id"] != "A_COV"
        for item in searcher.search(documents, "maximum total leverage ratio", "AAA")
    )
    assert searcher.search([], "maximum leverage", "AAA") == []
