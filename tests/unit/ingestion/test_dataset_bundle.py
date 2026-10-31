"""Portable import validation using a package reconstructed from versioned source inputs."""

import csv
import io
import json
import zipfile
from collections import Counter

import pytest

from credit_monitoring.ingestion.loaders import bundle
from credit_monitoring.paths import APP_SYNTHETIC_DIR, DATA_ROOT, EVALUATION_DIR


def rows(path):
    return list(csv.DictReader(io.StringIO(path.read_text())))


@pytest.fixture
def package(tmp_path):
    """No dependency on the ignored delivery ZIP in CI or a fresh checkout."""
    target = tmp_path / "data"
    synthetic = target / "app/synthetic"
    synthetic.mkdir(parents=True)
    members = {}
    borrowers = rows(APP_SYNTHETIC_DIR / "synthetic_borrowers.csv")
    new_borrowers = [r for r in borrowers if r["borrower_id"] >= "SYN013"]
    members[bundle.BORROWERS] = bundle._serialize(
        [
            {
                "borrower_id": r["borrower_id"],
                "borrower_name": r["borrower_name"],
                "industry": r["industry"],
                "borrower_type": "FICTIONAL",
                "scenario_family": r["scenario"].upper(),
                "scenario_description": r["description"],
                "quarters": "6",
                "covenant_count": "2" if "SYN018" <= r["borrower_id"] <= "SYN022" else "1",
            }
            for r in new_borrowers
        ]
    )
    financials = rows(APP_SYNTHETIC_DIR / "synthetic_quarterly_financials.csv")
    members[bundle.FINANCIALS] = bundle._serialize(
        [
            {
                "financial_record_id": f"{r['borrower_id']}-{r['period_end']}",
                "borrower_id": r["borrower_id"],
                "period_end": r["period_end"],
                "currency": r["currency"],
                "unit": "USD_millions",
                **{source: r[metric] for source, metric in bundle.METRIC_MAP.items()},
                "debt_source_status": r["debt_source_status"],
                "input_note": r["notes"],
            }
            for r in financials
            if r["borrower_id"] >= "SYN013"
        ]
    )
    terms = rows(APP_SYNTHETIC_DIR / "synthetic_covenant_terms.csv")
    new_terms = {}
    for row in terms:
        if row["borrower_id"] < "SYN013":
            continue
        key = f"{row['borrower_id']}-{row['covenant_id']}"
        if key not in new_terms:
            new_terms[key] = {
                "borrower_id": row["borrower_id"],
                "covenant_id": key,
                "covenant_name": row["covenant_name"],
                "formula_id": row["metric_formula"],
                "direction": "MAX" if row["operator"] == "<=" else "MIN",
                "threshold_schedule": [],
                "waived_periods": row["waived_periods"],
                "waiver_scope": "TEST_ONLY",
                "springing_operator": "LT" if row["springing_trigger_pct"] else "",
                **{source: row[dest] for source, dest in bundle.RULE_MAP.items()},
            }
        new_terms[key]["threshold_schedule"].append(
            {
                "effective_from": row["effective_start"],
                "effective_through": row["effective_end"],
                "threshold": float(row["threshold"]),
            }
        )
    for row in new_terms.values():
        row["threshold_schedule"] = json.dumps(row["threshold_schedule"], separators=(",", ":"))
    members["synthetic_covenants.csv"] = bundle._serialize(list(new_terms.values()))
    members[bundle.GOLD] = (EVALUATION_DIR / "synthetic_bundle_gold_cases.csv").read_bytes()
    gold = bundle._csv(members[bundle.GOLD])
    members["synthetic_manifest.json"] = json.dumps(
        {
            "fictional_borrowers": 25,
            "quarterly_financial_records": 150,
            "covenants": 30,
            "gold_cases": 180,
            "periods": list(bundle.PERIODS),
            "status_counts": dict(Counter(r["expected_status"] for r in gold)),
        }
    ).encode()
    sources = rows(DATA_ROOT / "app/sec/public_sec_documents.csv")
    new_sources = [
        {
            "sec_source_id": r["document_id"],
            "issuer_name": r["company"],
            "reference_ticker": r["ticker"],
            "cik": r["cik"],
            "form_type": r["document_type"],
            "period_end": r["period_end"],
            "filing_date": r["document_date"],
            "primary_html_url": r["source_url"],
            **{k: r[k] for k in ("accession_number", "filing_index_url", "selection_note")},
        }
        for r in sources
        if r["document_id"].startswith("SEC-")
    ]
    # Preserve every metadata field the importer projects into the catalog.
    for r in new_sources:
        r["html_identified_via"] = "SEC_EDGAR_PRIMARY_DOCUMENT"
        r["link_verified_as_of"] = "2026-10-29"
    members[bundle.SEC] = bundle._serialize(new_sources)
    members["sec_filing_manifest_40.json"] = json.dumps(new_sources).encode()
    for name, content in (
        ("synthetic_borrowers.csv", borrowers),
        ("synthetic_quarterly_financials.csv", financials),
        ("synthetic_covenant_terms.csv", terms),
    ):
        (synthetic / name).write_bytes(
            bundle._serialize([r for r in content if r["borrower_id"] < "SYN013"])
        )
    catalog = target / "app/sec/public_sec_documents.csv"
    catalog.parent.mkdir()
    catalog.write_bytes(
        bundle._serialize([r for r in sources if not r["document_id"].startswith("SEC-")])
    )
    archive = tmp_path / "bundle.zip"

    def save():
        with zipfile.ZipFile(archive, "w") as zipped:
            for name, content in members.items():
                zipped.writestr(name, content)

    save()
    return archive, target, members, save


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_validation_only_import_and_repeated_apply_are_idempotent(package):
    archive, root, _, _ = package
    before = snapshot(root)
    assert len(bundle.import_bundle(archive, root)["changed_files"]) == 6
    assert snapshot(root) == before
    bundle.import_bundle(archive, root, apply=True)
    assert len(rows(root / "app/synthetic/synthetic_borrowers.csv")) == 37
    after = snapshot(root)
    assert bundle.import_bundle(archive, root, apply=True)["changed_files"] == []
    assert snapshot(root) == after


@pytest.mark.parametrize(
    "problem", ["missing_value", "duplicate", "overlap", "waiver", "nan", "conflict"]
)
def test_invalid_package_or_authored_conflict_never_changes_outputs(package, problem):
    archive, root, members, save = package
    if problem == "conflict":
        bundle.import_bundle(archive, root, apply=True)
        data = bundle._csv(members[bundle.FINANCIALS])
        data[0]["total_debt_musd"] = "999"
        members[bundle.FINANCIALS] = bundle._serialize(data)
    elif problem in ("duplicate", "missing_value", "nan"):
        data = bundle._csv(members[bundle.FINANCIALS])
        if problem == "duplicate":
            data[1] = data[0]
        elif problem == "missing_value":
            data[0]["period_end"] = "2025-02-30"
        else:
            data[0]["total_debt_musd"] = "nan"
        members[bundle.FINANCIALS] = bundle._serialize(data)
    else:
        data = bundle._csv(members["synthetic_covenants.csv"])
        if problem == "waiver":
            data[0]["waived_periods"] = '["2027-03-31"]'
        else:
            schedule = json.loads(data[0]["threshold_schedule"])
            data[0]["threshold_schedule"] = json.dumps(schedule + schedule)
        members["synthetic_covenants.csv"] = bundle._serialize(data)
    save()
    before = snapshot(root)
    with pytest.raises(ValueError):
        bundle.import_bundle(archive, root, apply=True)
    assert snapshot(root) == before
