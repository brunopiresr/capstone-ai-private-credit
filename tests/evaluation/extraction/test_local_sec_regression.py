"""Optional provenance regression using an existing local SEC source, without model calls."""

from pathlib import Path

import pytest

from credit_monitoring.domain import CovenantExtraction, CovenantTerm, SourceEvidence
from credit_monitoring.ingestion.loaders.sec import load_catalog
from credit_monitoring.verification.extraction import validate_extraction

ROOT = Path(__file__).parents[3]
SOURCE = ROOT / "data/sec_documents/markdown/DOC_AVD_AMD8_2025.md"


@pytest.mark.skipif(not SOURCE.exists(), reason="Optional ignored local SEC Markdown is absent.")
def test_existing_local_quote_has_exact_provenance():
    record = next(
        r
        for r in load_catalog(ROOT / "data/public_sec_documents.csv")
        if r["document_id"] == "DOC_AVD_AMD8_2025"
    )
    quote = next(
        line for line in SOURCE.read_text().splitlines() if "Maximum Total Leverage Ratio" in line
    )
    label_date = record.get("document_date") or record.get("period_end") or "date not listed"
    citation = (
        f"{record['company']}, {record['document_type']} ({label_date}), "
        f"{record['document_id']} — {record['source_url']}"
    )
    supplied = {**record, "citation": citation, "content": quote, "markdown_path": str(SOURCE)}
    extraction = CovenantExtraction(
        covenants=[
            CovenantTerm(
                covenant_name="Maximum Total Leverage Ratio",
                covenant_type="leverage",
                evidence=SourceEvidence(
                    evidence_quote=quote,
                    document_id=record["document_id"],
                    citation=citation,
                    markdown_path=str(SOURCE),
                ),
            )
        ],
        gaps=["This provenance-only regression does not extract threshold schedules."],
    )
    assert validate_extraction(extraction, [supplied]).is_valid
