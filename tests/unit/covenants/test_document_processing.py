"""Full-source delivery, persistent reuse, section recovery, and exact schedule preservation."""

import csv
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from model_helpers import ScriptedModel

from credit_monitoring.application.bootstrap import create_document_service
from credit_monitoring.covenants.assembly import combine_extractions
from credit_monitoring.covenants.extraction import ExtractionIncompleteError
from credit_monitoring.domain import (
    CovenantExtraction,
    CovenantTerm,
    SourceEvidence,
    ThresholdScheduleEntry,
)
from credit_monitoring.ingestion.chunking.sections import SectionTooLargeError, split_document
from credit_monitoring.ingestion.converters.sec_markdown import CONVERSION_VERSION, load_markdown

FIXTURE = Path(__file__).parents[2] / "fixtures/sec_covenant_v2/fmc_amendment_schedule.md"


def test_cleaner_upgrade_invalidates_extraction_without_deleting_old_record(
    document_service_factory, generation_response, monkeypatch
):
    service = document_service_factory()
    marker = service.markdown_dir / ".SYN.conversion-version"
    service.model.respond.return_value = generation_response(CovenantExtraction())
    with monkeypatch.context() as old_version:
        for module in (
            "credit_monitoring.application.document_processing_service",
            "credit_monitoring.ingestion.converters.sec_markdown",
        ):
            old_version.setattr(f"{module}.CONVERSION_VERSION", "beautifulsoup-clean-v1")
        marker.write_text("beautifulsoup-clean-v1")
        first = service.process_document("SYN")
    stale = service.get_document_extraction("SYN")
    assert stale.status == "stale" and stale.result is None
    assert service.model.respond.call_count == 1
    service.html_dir.mkdir()
    (service.html_dir / "SYN.html").write_text("<p>Maximum leverage ratio 4.00x.</p>")
    service.converter = Mock()
    service.converter.convert_local.return_value = SimpleNamespace(
        markdown=(service.markdown_dir / "SYN.md").read_text()
    )
    second = service.process_document("SYN")
    assert second.status == "complete" and not second.cache_hit
    assert first.cache_key != second.cache_key
    assert service.repository.get("SYN", first.cache_key) is not None
    assert marker.read_text() == CONVERSION_VERSION
    assert service.model.respond.call_count == 2


@pytest.fixture
def multi_document_service(document_service_factory, generation_response):
    service = document_service_factory()
    original = service.catalog_record("SYN")
    rows = [
        original,
        {**original, "document_id": "SECOND", "ticker": "OTHER"},
        {**original, "document_id": "THIRD"},
    ]
    with service.source_file.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(original))
        writer.writeheader()
        writer.writerows(rows)
    for row in rows[1:]:
        document_id = row["document_id"]
        (service.markdown_dir / f"{document_id}.md").write_text("Maximum leverage ratio 4.00x.")
        (service.markdown_dir / f".{document_id}.conversion-version").write_text(CONVERSION_VERSION)
    service.model.respond.return_value = generation_response(CovenantExtraction())
    return service


def test_process_all_documents_preserves_order_cache_and_force(multi_document_service):
    service = multi_document_service
    first = service.process_all_documents(max_workers=1)
    assert [outcome.document_id for outcome in first] == ["SYN", "SECOND", "THIRD"]
    assert all(outcome.status == "complete" and not outcome.cache_hit for outcome in first)
    assert service.model.respond.call_count == 3
    cached = service.process_all_documents(max_workers=1)
    assert all(outcome.cache_hit and outcome.result is not None for outcome in cached)
    assert service.model.respond.call_count == 3
    forced = service.process_all_documents(force=True, max_workers=1)
    assert all(outcome.status == "complete" and not outcome.cache_hit for outcome in forced)
    assert service.model.respond.call_count == 6


def test_batch_logs_live_progress_timings_and_cache_reuse(
    multi_document_service, generation_response, caplog
):
    service = multi_document_service
    caplog.set_level(logging.INFO, logger="credit_monitoring")

    def respond(**kwargs):
        # The caller can see the active section before the blocking request returns.
        assert caplog.records[-1].getMessage().startswith("Extract section started")
        return generation_response(CovenantExtraction())

    service.model.respond.side_effect = respond
    service.process_all_documents(ticker="SYN", max_workers=1)
    messages = [record.getMessage() for record in caplog.records]
    assert any("document=1/2 document_id=SYN" in message for message in messages)
    assert any("document=2/2 document_id=THIRD" in message for message in messages)
    assert not any("document_id=SECOND" in message for message in messages)
    for action in (
        "Load Markdown",
        "Check extraction cache",
        "Split document",
        "Prepare section cache",
        "Extract section",
        "Save section",
        "Combine extractions",
        "Save document result",
    ):
        assert any(message.startswith(f"{action} started") for message in messages)
        assert any(
            message.startswith(f"{action} complete") and "elapsed_s=" in message
            for message in messages
        )
    assert "section=1/1 model=function:synthetic chars=" in caplog.text
    assert "Batch summary total_documents=2 completed=2 failed=0 cache_hits=0" in caplog.text
    assert "Maximum leverage" not in caplog.text
    assert "retrieved_records" not in caplog.text

    caplog.clear()
    service.process_all_documents(ticker="SYN", max_workers=1)
    assert "Extraction cache hit document_id=SYN" in caplog.text
    assert "Extract section started" not in caplog.text
    assert "Batch summary total_documents=2 completed=2 failed=0 cache_hits=2" in caplog.text
    assert service.model.respond.call_count == 2


def test_process_all_documents_filters_ticker(multi_document_service):
    service = multi_document_service
    outcomes = service.process_all_documents(ticker="SYN", max_workers=1)
    assert [outcome.document_id for outcome in outcomes] == ["SYN", "THIRD"]
    assert service.get_document_extraction("SECOND").status == "missing"
    assert service.model.respond.call_count == 2
    assert service.process_all_documents(ticker="UNKNOWN", max_workers=1) == []
    assert service.model.respond.call_count == 2


@pytest.mark.parametrize("failure_stage", ["source", "model"])
def test_process_all_documents_continues_after_failure(
    failure_stage, multi_document_service, generation_response, monkeypatch, caplog
):
    service = multi_document_service
    caplog.set_level(logging.INFO, logger="credit_monitoring")
    if failure_stage == "source":

        def failing_source(record, **kwargs):
            if record["document_id"] == "SECOND":
                raise OSError("Source is unavailable")
            return load_markdown(record, **kwargs)

        monkeypatch.setattr(
            "credit_monitoring.application.document_processing_service.load_markdown",
            failing_source,
        )
    else:
        service.model.respond.side_effect = [
            generation_response(CovenantExtraction()),
            generation_response(status="incomplete"),
            generation_response(CovenantExtraction()),
        ]
    outcomes = service.process_all_documents(max_workers=1)
    assert [outcome.status for outcome in outcomes] == ["complete", "failed", "complete"]
    failed = outcomes[1]
    assert failed.document_id == "SECOND" and failed.ticker == "OTHER"
    assert failed.citation == service.get_document_extraction("SECOND").citation
    assert failed.result is None and not failed.cache_hit
    assert ("OSError" if failure_stage == "source" else "ExtractionIncompleteError") in failed.error
    assert service.get_document_extraction("THIRD").status == "complete"
    if failure_stage == "model":
        assert service.get_document_extraction("SECOND").status == "failed"
    failed_action = "Load Markdown" if failure_stage == "source" else "Extract section"
    assert f"{failed_action} failed document_id=SECOND" in caplog.text
    assert "Batch summary total_documents=3 completed=2 failed=1 cache_hits=0" in caplog.text
    assert any(
        record.levelno == logging.ERROR
        and "Batch document finished document=2/3 document_id=SECOND status=failed"
        in record.getMessage()
        for record in caplog.records
    )


def test_process_all_documents_empty_catalog_and_invalid_catalog(multi_document_service, caplog):
    service = multi_document_service
    caplog.set_level(logging.INFO, logger="credit_monitoring")
    header = service.source_file.read_text().splitlines()[0]
    service.source_file.write_text(header + "\n")
    assert service.process_all_documents(max_workers=1) == []
    assert "Batch summary total_documents=0 completed=0 failed=0 cache_hits=0" in caplog.text
    service.source_file.write_text("document_id,company\nSYN,Synthetic\n")
    with pytest.raises(ValueError, match="Catalog rows require"):
        service.process_all_documents(max_workers=1)
    assert "Load and validate catalog failed" in caplog.text
    service.model.respond.assert_not_called()


def test_fmc_all_quarters_reach_model_and_survive_json(
    document_service_factory, generation_response
):
    text = FIXTURE.read_text()
    service = document_service_factory(text)
    record = service.catalog_record("SYN")
    citation = service.get_document_extraction("SYN").citation
    terms = []
    first, second = text.split("Minimum Interest Coverage Ratio.", 1)
    for name, kind, table, expected_count in (
        ("Maximum Leverage Ratio", "leverage", first, 19),
        ("Minimum Interest Coverage Ratio", "interest_coverage", second, 17),
    ):
        entries = []
        for match in re.finditer(
            r"(?m)^\| ([A-Za-z]+ \d+, \d{4}) \|.*?\| (\d+\.\d+ to 1\.00) \|.*$", table
        ):
            evidence = SourceEvidence(
                document_id="SYN",
                citation=citation,
                evidence_quote=match.group(),
                markdown_path=str(service.markdown_dir / "SYN.md"),
                source_start=0,
                source_end=len(text),
            )
            entries.append(
                ThresholdScheduleEntry(
                    threshold=match[2],
                    period_end_dates=[datetime.strptime(match[1], "%B %d, %Y").date()],
                    evidence=evidence,
                )
            )
        assert len(entries) == expected_count
        terms.append(
            CovenantTerm(
                covenant_name=name,
                covenant_type=kind,
                threshold_schedule=entries,
                evidence=entries[0].evidence,
            )
        )
    expected = CovenantExtraction(issuer=record["company"], covenants=terms)
    service.model.respond.return_value = generation_response(expected)
    result = service.process_document("SYN")
    payload = json.loads(service.model.respond.call_args.kwargs["messages"][0].parts[0].content)
    assert payload["retrieved_records"][0]["text"] == text
    assert "| December 31, 2027 |" in payload["retrieved_records"][0]["text"]
    assert result.result.extraction == expected
    serialized = json.loads(result.model_dump_json())
    schedules = [c["threshold_schedule"] for c in serialized["result"]["extraction"]["covenants"]]
    assert [len(s) for s in schedules] == [19, 17]
    assert schedules[0][0]["threshold"] == "4.00 to 1.00"
    assert schedules[0][-1]["period_end_dates"] == ["2027-12-31"]
    assert result.result.validation is None and serialized["result"]["validation"] is None


def test_cache_survives_new_service_and_force_reprocesses(
    document_service_factory, generation_response
):
    service = document_service_factory()
    service.model.respond.return_value = generation_response(CovenantExtraction())
    first = service.process_document("SYN")
    assert not first.cache_hit and first.status == "complete"
    restored = create_document_service(
        model=ScriptedModel(),
        source_file=service.source_file,
        html_dir=service.html_dir,
        markdown_dir=service.markdown_dir,
        database_path=service.repository.database_path,
    )
    cached = restored.process_document("SYN")
    assert cached.cache_hit and cached.cache_key == first.cache_key
    restored.model.respond.assert_not_called()
    forced = service.process_document("SYN", force=True)
    assert not forced.cache_hit and service.model.respond.call_count == 2


@pytest.mark.parametrize(
    "change", ["content", "metadata", "model", "budget", "prompt", "schema", "segmentation"]
)
def test_changed_inputs_invalidate_cache(
    change, document_service_factory, generation_response, monkeypatch
):
    service = document_service_factory()
    service.model.respond.return_value = generation_response(CovenantExtraction())
    first = service.process_document("SYN")
    if change == "content":
        path = service.markdown_dir / "SYN.md"
        path.write_text(path.read_text() + "\nNew disclosure.\n")
    elif change == "metadata":
        rows = list(csv.DictReader(service.source_file.open()))
        rows[0]["document_date"] = "2025-02-04"
        with service.source_file.open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    elif change == "model":
        service.model._model_name = "another-test-model"
    elif change == "budget":
        service.max_chars = 1000
    else:
        constant = {
            "prompt": "EXTRACTION_PROMPT_VERSION",
            "schema": "RESULT_SCHEMA_VERSION",
            "segmentation": "SEGMENTATION_VERSION",
        }[change]
        monkeypatch.setattr(
            f"credit_monitoring.application.document_processing_service.{constant}",
            "changed-version",
        )
    stale = service.get_document_extraction("SYN")
    assert stale.status == "stale" and stale.result is None
    second = service.process_document("SYN")
    assert second.cache_key != first.cache_key and not second.cache_hit
    assert service.model.respond.call_count == 2


def test_empty_new_catalog_metadata_preserves_legacy_cache(
    document_service_factory, generation_response
):
    service = document_service_factory()
    service.model.respond.return_value = generation_response(CovenantExtraction())
    first = service.process_document("SYN")
    record = service.catalog_record("SYN")
    for name in (
        "accession_number",
        "filing_index_url",
        "html_identified_via",
        "link_verified_as_of",
        "selection_note",
        "reference_ticker",
    ):
        record[name] = ""

    def save():
        with service.source_file.open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(record))
            writer.writeheader()
            writer.writerow(record)

    save()
    reused = service.process_document("SYN")
    assert reused.cache_hit and reused.cache_key == first.cache_key
    assert service.model.respond.call_count == 1
    record["accession_number"] = "new-accession"
    save()
    assert service.get_document_extraction("SYN").status == "stale"


def test_failed_sections_resume_without_publishing_partial_facts(
    document_service_factory, generation_response, caplog
):
    text = "# Source\n\n" + "\n\n".join("Paragraph " + str(i) + " x" * 20 for i in range(8))
    service = document_service_factory(text, max_chars=150)
    count = len(split_document(text, max_chars=150))
    assert count > 2
    service.model.respond.side_effect = [
        generation_response(CovenantExtraction(gaps=["First section gap"])),
        generation_response(status="incomplete"),
    ]
    with pytest.raises(ExtractionIncompleteError):
        service.process_document("SYN")
    failed = service.get_document_extraction("SYN")
    assert failed.status == "failed" and failed.result is None
    assert failed.completed_sections == 1
    service.model.respond.reset_mock()
    service.model.respond.side_effect = None
    service.model.respond.return_value = generation_response(CovenantExtraction())
    caplog.set_level(logging.INFO, logger="credit_monitoring")
    resumed = service.process_document("SYN")
    assert resumed.status == "complete" and resumed.completed_sections == count
    assert service.model.respond.call_count == count - 1
    assert resumed.result.extraction.gaps == ["First section gap"]
    assert f"total_sections={count} cached_sections=1" in caplog.text
    assert f"Section cache hit document_id=SYN section=1/{count}" in caplog.text
    assert f"Extract section started document_id=SYN section=1/{count}" not in caplog.text


def test_failed_forced_run_does_not_return_previous_success(
    document_service_factory, generation_response
):
    service = document_service_factory()
    service.model.respond.return_value = generation_response(CovenantExtraction())
    service.process_document("SYN")
    service.model.respond.return_value = generation_response(status="incomplete")
    with pytest.raises(ExtractionIncompleteError):
        service.process_document("SYN", force=True)
    result = service.get_document_extraction("SYN")
    assert result.status == "failed" and result.result is None


def test_search_and_discovery_do_not_call_model_or_require_stored_facts(document_service_factory):
    service = document_service_factory()
    documents = service.list_document_extractions("SYN")
    assert documents[0].status == "missing"
    assert service.list_document_extractions("OTHER") == []
    results = service.search_evidence("maximum leverage", "SYN")
    assert results and results[0]["content"] == (service.markdown_dir / "SYN.md").read_text()
    assert results[0]["offset_coordinate_system"] == "markdown"
    assert service.search_evidence("leverage", "OTHER") == []
    service.model.respond.assert_not_called()


def test_search_indexes_later_rows_without_keyword_filtering(document_service_factory):
    text = "Background paragraph.\n\n" * 300 + "UniqueFiscalQuarterTail 4.25 to 1.00."
    service = document_service_factory(text)
    results = service.search_evidence("UniqueFiscalQuarterTail")
    assert any("UniqueFiscalQuarterTail" in r["content"] for r in results)
    for r in results:
        assert r["content"] == text[r["source_start"] : r["source_end"]]


def test_unknown_unavailable_and_oversized_sources_are_explicit(document_service_factory):
    service = document_service_factory("one giant paragraph" * 100, max_chars=100)
    with pytest.raises(ValueError, match="Unknown catalog"):
        service.process_document("NO_SUCH_ID")
    with pytest.raises(SectionTooLargeError):
        service.process_document("SYN")
    assert service.get_document_extraction("SYN").result is None
    (service.markdown_dir / "SYN.md").unlink()
    assert service.get_document_extraction("SYN").status == "unavailable"
    service.model.respond.assert_not_called()


def test_malformed_catalog_is_an_explicit_error(document_service_factory):
    service = document_service_factory()
    service.source_file.write_text("document_id,company\nSYN,Synthetic\n")
    with pytest.raises(ValueError, match="Catalog rows require"):
        service.list_document_extractions()
    service.model.respond.assert_not_called()


def test_disabled_validators_are_not_invoked(
    document_service_factory, generation_response, monkeypatch
):
    def fail(*args, **kwargs):
        raise AssertionError("Automatic verification should be disabled")

    monkeypatch.setattr("credit_monitoring.verification.extraction.validate_extraction", fail)
    monkeypatch.setattr("credit_monitoring.verification.extraction.validate_all_companies", fail)
    service = document_service_factory()
    service.model.respond.return_value = generation_response(CovenantExtraction())
    assert service.process_document("SYN").result.validation is None


def test_exact_duplicates_removed_but_distinct_versions_preserved(synthetic_records, evidence_for):
    evidence = evidence_for(synthetic_records["base"])
    term = CovenantTerm(covenant_name="Leverage", covenant_type="leverage", evidence=evidence)
    different = term.model_copy(update={"effective_date_or_period": "Later version"})
    combined = combine_extractions(
        [
            CovenantExtraction(issuer="First issuer", covenants=[term]),
            CovenantExtraction(issuer="Other issuer", covenants=[term, different]),
        ]
    )
    assert combined.covenants == [term, different]
    assert combined.issuer is None and combined.conflicts


def test_search_retains_late_passages_offsets_and_reflects_source_edits(document_service_factory):
    text = "Ordinary operational discussion. " * 200
    text += "\nMinimum interest coverage ratio is 3.00 to 1.00.\n"
    service = document_service_factory(text)
    results = service.search_evidence("minimum interest coverage ratio", "SYN")
    selected = next(item for item in results if "3.00 to 1.00" in item["content"])
    assert selected["source_start"] > 0
    assert selected["content"] == text[selected["source_start"] : selected["source_end"]]
    assert selected["offset_coordinate_system"] == "markdown"
    assert selected["citation"] == service.get_document_extraction("SYN").citation
    updated = text.replace("3.00 to 1.00", "4.00 to 1.00")
    (service.markdown_dir / "SYN.md").write_text(updated)
    results = service.search_evidence("minimum interest coverage ratio", "SYN")
    assert any("4.00 to 1.00" in item["content"] for item in results)
    assert not any("3.00 to 1.00" in item["content"] for item in results)
    service.model.respond.assert_not_called()
