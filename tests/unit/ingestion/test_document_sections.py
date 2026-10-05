"""Lossless sections protect tables, introduction clauses, and continuation rows."""

import pytest

from credit_monitoring.ingestion.chunking.sections import SectionTooLargeError, split_document


def test_full_source_coverage_and_separate_heading_coordinates():
    text = "# Agreement\n\n" + "\n\n".join("Paragraph " + str(i) + " x" * 10 for i in range(8))
    sections = split_document(text, max_chars=100)
    assert "".join(text[s.start : s.end] for s in sections) == text
    assert sections[1].context == ((0, len("# Agreement")),)
    document = {"content": text, "document_id": "SYN", "source_length": len(text)}
    for section in sections:
        records = section.records(document)
        assert sum(len(r["content"]) for r in records) <= 100
        for record in records:
            assert record["content"] == text[record["source_start"] : record["source_end"]]


def test_table_introduction_and_page_continuation_are_not_split():
    prefix = "# Agreement\n\n" + "Background. " * 8 + "\n\n"
    protected = (
        "Maximum ratio during relief:\n\n| Quarter | Threshold |\n| --- | --- |\n"
        "| June 2025 | 4.00 to 1.00 |\n\n2\n\n---\n\n"
        "| Quarter | Threshold |\n| --- | --- |\n| December 2027 | 3.75 to 1.00 |\n\n"
    )
    text = prefix + protected + "Afterwards. " * 10
    sections = split_document(text, max_chars=len(protected) + 20)
    containing = [s for s in sections if "June 2025" in text[s.start : s.end]]
    assert len(containing) == 1
    assert protected in text[containing[0].start : containing[0].end]
    assert "".join(text[s.start : s.end] for s in sections) == text


def test_oversized_table_or_paragraph_is_not_truncated():
    for text in ("single paragraph " * 100, "Intro.\n\n| Label | " + "x" * 1000 + " |"):
        with pytest.raises(SectionTooLargeError, match="no text was truncated"):
            split_document(text, max_chars=100)


def test_short_document_single_section_and_empty_input_errors():
    assert len(split_document("Whole document", max_chars=100)) == 1
    with pytest.raises(ValueError, match="empty"):
        split_document(" \n\n")
    with pytest.raises(ValueError, match="positive"):
        split_document("Document", max_chars=0)
