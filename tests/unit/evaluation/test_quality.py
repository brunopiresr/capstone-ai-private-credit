import hashlib
import json

import pytest

from credit_monitoring.evaluation.agent_batch import SUITE
from credit_monitoring.evaluation.quality import (
    RequirementFinding,
    dimension_scores,
    historical_claim_link,
    validate_findings,
)


def test_frozen_reserved_inputs_and_original_source_have_not_changed():
    folder = SUITE / "frozen"
    manifest = json.loads((folder / "reserved-manifest.json").read_text())
    assert len(manifest["reserved_ids"]) >= 20
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
    original = json.loads((folder / "original.json").read_text())
    assert original["source_matches_capture"]
    assert (
        hashlib.sha256((folder / "original-configuration.tar.gz").read_bytes()).hexdigest()
        == (original["bundle_sha256"])
    )


def test_absent_content_cannot_be_credited_from_tools_or_invented_quotes():
    packet = {"requirements": {"r1": "Observed availability"}, "final_answer": "Testing active."}
    for quote in (None, "Availability was 24%"):
        with pytest.raises(ValueError):
            validate_findings(
                [
                    RequirementFinding(
                        requirement_id="r1", verdict="pass", excerpt=quote, reason="Seen in tool"
                    )
                ],
                packet,
            )
    validate_findings(
        [
            RequirementFinding(
                requirement_id="r1", verdict="fail", excerpt=None, reason="Absent from final answer"
            )
        ],
        packet,
    )


def test_unrelated_appended_run_id_is_not_claim_coverage():
    assert not historical_claim_link(
        "Compliant.\n\nrun-A result-A", ["run-A", "result-A"], ["compliant"]
    )
    assert historical_claim_link(
        "compliant [run-A / result-A]", ["run-A", "result-A"], ["compliant"]
    )


def test_missing_semantic_grades_and_inapplicable_dimensions_remain_visible():
    scores = dimension_scores([{"name": "completed", "passed": False}], {"label": None})
    assert scores["execution"] == {"passed": 0, "denominator": 1, "missing": 0}
    assert scores["semantic"] == {"passed": 0, "denominator": 1, "missing": 1}
    assert scores["financial"]["denominator"] == 0


def test_sentence_period_does_not_hide_a_cited_status():
    assert historical_claim_link(
        "The result is a breach.\nSource: run-A, result-A", ["run-A", "result-A"], ["breach"]
    )
    assert not historical_claim_link(
        "Actual 13.125.\nSource: run-A, result-A", ["run-A", "result-A"], ["3.125"]
    )


@pytest.mark.parametrize(
    "text,fact",
    [("Compliant.", "compliant"), ("Actual 3.125x.", "3.125"), ("Threshold 4.0x.", "4")],
)
def test_citation_facts_accept_displayed_case_and_ratio_units(text, fact):
    assert historical_claim_link(text + "\nSource: run-A, result-A", ["run-A", "result-A"], [fact])
