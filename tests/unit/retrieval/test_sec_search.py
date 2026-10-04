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
