"""Offline extraction helper tests with temporary files and injected converters."""

import logging
from types import SimpleNamespace
from unittest.mock import Mock

from credit_monitoring.domain import RetrievedRecord
from credit_monitoring.ingestion.chunking.evidence import (
    chunk_evidence_documents,
    prepare_documents,
    select_relevant_evidence,
)
from credit_monitoring.ingestion.cleaners.sec_html import clean_html
from credit_monitoring.ingestion.converters.sec_markdown import CONVERSION_VERSION, load_markdown
from credit_monitoring.ingestion.loaders.sec import download_sec_filing


def test_html_cleanup_keeps_substantive_tables():
    html = '<nav>menu</nav><script>bad()</script><div class="cookie"><span>cookie</span></div>'
    html += "<table><tr><td>Maximum Leverage Ratio</td><td>5.00</td></tr></table>"
    result = clean_html(html)
    assert "Maximum Leverage Ratio" in result and "<table>" in result
    assert "menu" not in result and "bad()" not in result and "cookie" not in result


def test_keyword_neighbors_truncation_and_empty_selection():
    selected = select_relevant_evidence(
        "before\nLeverage ratio 5.00\nafter\nunrelated", max_chars=500
    )
    assert selected.text == "before\nLeverage ratio 5.00\nafter"
    assert not selected.truncated
    assert select_relevant_evidence("EBITDA " + "x" * 100, max_chars=20).truncated
    assert select_relevant_evidence("No relevant keywords.").text == ""


def test_prepare_documents_does_not_fabricate_offsets(synthetic_records):
    record = prepare_documents([synthetic_records["base"]])[0]
    assert record["source_start"] is None and record["source_end"] is None
    assert RetrievedRecord.from_record(record).source_start is None


def test_gitsource_start_is_in_selected_excerpt_coordinates(synthetic_records):
    original = {
        **synthetic_records["base"],
        "source_length": len(synthetic_records["base"]["content"]),
        "offset_coordinate_system": "selected_excerpt",
    }
    chunks = chunk_evidence_documents([original], size=100, step=50)
    assert chunks[1]["source_start"] == 50 and chunks[1]["source_end"] is None
    assert chunks[1]["content"] == original["content"][50:150]


def test_download_uses_caller_identity_without_real_http():
    session = Mock()
    session.get.return_value.content = b"synthetic html"
    assert (
        download_sec_filing(
            "https://example.invalid/fixture",
            user_agent="Fixture fixture@example.invalid",
            session=session,
        )
        == "synthetic html"
    )
    assert (
        session.get.call_args.kwargs["headers"]["User-Agent"] == "Fixture fixture@example.invalid"
    )


def test_conversion_reuses_versioned_markdown_and_reconverts_stale_cache(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="credit_monitoring")
    html_dir, markdown_dir = tmp_path / "html", tmp_path / "markdown"
    html_dir.mkdir()
    markdown_dir.mkdir()
    (html_dir / "SYN.html").write_text("<table><tr><td>covenant</td></tr></table>")
    record = {"document_id": "SYN", "source_url": "https://example.invalid/fixture"}
    converter = Mock()
    converter.convert_local.return_value = SimpleNamespace(markdown="synthetic covenant markdown")
    args = dict(html_dir=html_dir, markdown_dir=markdown_dir, user_agent="", converter=converter)
    assert load_markdown(record, **args) == "synthetic covenant markdown"
    assert "HTML cache hit document_id=SYN" in caplog.text
    assert "Clean SEC HTML complete document_id=SYN elapsed_s=" in caplog.text
    assert "Convert HTML to Markdown complete document_id=SYN elapsed_s=" in caplog.text
    assert "Save Markdown cache complete document_id=SYN elapsed_s=" in caplog.text
    assert "synthetic covenant markdown" not in caplog.text
    assert (markdown_dir / ".SYN.conversion-version").read_text() == CONVERSION_VERSION
    caplog.clear()
    load_markdown(record, **args)
    assert converter.convert_local.call_count == 1
    assert "Markdown cache hit document_id=SYN" in caplog.text
    assert "Convert HTML to Markdown started" not in caplog.text
    (markdown_dir / ".SYN.conversion-version").write_text("stale")
    load_markdown(record, **args)
    assert converter.convert_local.call_count == 2


def test_download_and_conversion_log_before_blocking_work(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="credit_monitoring")

    def download(*args, **kwargs):
        assert caplog.messages[-1] == "Download SEC HTML started document_id=SYN"
        return "<p>synthetic source</p>"

    def convert(*args):
        assert caplog.messages[-1] == "Convert HTML to Markdown started document_id=SYN"
        return SimpleNamespace(markdown="synthetic markdown")

    monkeypatch.setattr(
        "credit_monitoring.ingestion.converters.sec_markdown.download_sec_filing", download
    )
    monkeypatch.setattr(
        "credit_monitoring.ingestion.converters.sec_markdown.throttle_download", lambda: None
    )
    markdown = load_markdown(
        {"document_id": "SYN", "source_url": "https://example.invalid/fixture"},
        html_dir=tmp_path / "html",
        markdown_dir=tmp_path / "markdown",
        user_agent="",
        converter=SimpleNamespace(convert_local=convert),
    )
    assert markdown == "synthetic markdown"
    assert "Download SEC HTML complete document_id=SYN elapsed_s=" in caplog.text
