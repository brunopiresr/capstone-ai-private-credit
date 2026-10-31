"""Validate and normalize the standalone expansion without executing bundled code."""

import csv
import hashlib
import io
import json
import math
import sqlite3
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from credit_monitoring.covenants.structured import BUNDLE_FORMULAS, SyntheticCovenantReader
from credit_monitoring.domain.financials import FINANCIAL_METRICS
from credit_monitoring.ingestion.loaders.financials import load_financials
from credit_monitoring.ingestion.loaders.sec import validate_document_id

PERIODS = ("2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30")
BORROWERS = "synthetic_borrowers_SYN013_SYN037.csv"
FINANCIALS = "synthetic_financials_2025Q1_2026Q2.csv"
GOLD = "synthetic_gold_cases_180.csv"
SEC = "sec_filing_manifest_40.csv"
METRIC_MAP = {
    "total_debt_musd": "total_debt",
    "unrestricted_cash_musd": "cash",
    "base_ebitda_ttm_musd": "reported_ebitda",
    "eligible_addbacks_ttm_musd": "eligible_addbacks",
    "acquired_ebitda_ttm_musd": "acquired_ebitda",
    "eligible_synergies_ttm_musd": "synergy_addback",
    "interest_expense_ttm_musd": "interest_expense",
    "fixed_charge_numerator_ttm_musd": "fixed_charge_numerator",
    "fixed_charges_ttm_musd": "fixed_charges",
    "availability_pct": "revolver_availability_pct",
}
RULE_MAP = {
    "addback_cap_pct_of_base_ebitda": "addback_cap_fraction",
    "synergy_cap_pct_of_base_ebitda": "synergy_cap_fraction",
    "cash_netting_cap_musd": "cash_netting_cap",
    "springing_trigger_pct": "springing_trigger_pct",
}


def _csv(content: bytes) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError("Missing or duplicate CSV headers")
    rows = list(reader)
    if any(None in row or None in row.values() for row in rows):
        raise ValueError("Malformed CSV record")
    return rows


def _number(value: str) -> float | None:
    if value == "":
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Bundle numbers must be finite")
    return number


def _date(value: str) -> str:
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("Dates must use YYYY-MM-DD")
    return value


def _unique(rows, keys):
    indexed = {tuple(row[key] for key in keys): row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError(f"Duplicate bundle key: {keys}")
    return indexed


def _serialize(rows, fields=None) -> bytes:
    if fields is None:
        fields = list(dict.fromkeys(key for row in rows for key in row))
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


def _merge(path, additions, keys):
    existing = _csv(path.read_bytes())
    indexed = _unique(existing, keys)
    changed = False
    for row in additions:
        key = tuple(row[name] for name in keys)
        if key in indexed:
            previous = indexed[key]
            if any(
                previous.get(name, "") != row.get(name, "") for name in set(previous) | set(row)
            ):
                raise ValueError(f"Conflicting authored record in {path.name}: {key}")
        else:
            indexed[key] = row
            existing.append(row)
            changed = True
    return _serialize(existing) if changed else path.read_bytes()


def _validate(members):
    borrowers, financials, terms, gold, sources = (
        _csv(members[name])
        for name in (BORROWERS, FINANCIALS, "synthetic_covenants.csv", GOLD, SEC)
    )
    manifest = json.loads(members["synthetic_manifest.json"])
    for name, count, rows in (
        ("fictional_borrowers", 25, borrowers),
        ("quarterly_financial_records", 150, financials),
        ("covenants", 30, terms),
        ("gold_cases", 180, gold),
    ):
        if len(rows) != count or manifest[name] != count:
            raise ValueError(f"Invalid bundle count: {name}")
    if manifest["periods"] != list(PERIODS):
        raise ValueError("Unexpected bundle periods")
    identities = {f"SYN{i:03d}" for i in range(13, 38)}
    if set(_unique(borrowers, ("borrower_id",))) != {(b,) for b in identities}:
        raise ValueError("Unexpected borrower identifiers")
    if set(_unique(financials, ("borrower_id", "period_end"))) != {
        (b, p) for b in identities for p in PERIODS
    }:
        raise ValueError("Expected exactly six periods per new borrower")
    _unique(financials, ("financial_record_id",))
    covenant_by_id = {key[0]: row for key, row in _unique(terms, ("covenant_id",)).items()}
    for row in borrowers:
        bid = row["borrower_id"]
        expected = 2 if bid in {f"SYN{i:03d}" for i in range(18, 23)} else 1
        if (
            int(row["quarters"]) != 6
            or int(row["covenant_count"]) != expected
            or sum(c["borrower_id"] == bid for c in terms) != expected
            or row["borrower_type"] != "FICTIONAL"
        ):
            raise ValueError("Invalid borrower covenant count or origin")
    for row in financials:
        if row["financial_record_id"] != f"{row['borrower_id']}-{row['period_end']}":
            raise ValueError("Financial record ID does not match its key")
        if row["currency"] != "USD" or row["unit"] != "USD_millions":
            raise ValueError("Unexpected financial units")
        if row["debt_source_status"] not in ("CONFLICTING", "RECONCILED"):
            raise ValueError("Invalid debt-source status")
        for name in METRIC_MAP:
            value = _number(row[name])
            if name == "availability_pct" and value is not None and not 0 <= value <= 100:
                raise ValueError("Availability must be between 0 and 100")
    schedules = {}
    for row in terms:
        if (
            row["borrower_id"] not in identities
            or not row["covenant_id"].startswith(row["borrower_id"] + "-")
            or row["formula_id"] not in BUNDLE_FORMULAS
            or row["direction"] not in ("MIN", "MAX")
        ):
            raise ValueError("Invalid covenant identity or formula")
        if row["waiver_scope"] != "TEST_ONLY":
            raise ValueError("Unsupported waiver scope")
        schedule = json.loads(row["threshold_schedule"])
        schedules[row["covenant_id"]] = schedule
        ranges = []
        for entry in schedule:
            start, end = _date(entry["effective_from"]), _date(entry["effective_through"])
            if start > end or _number(str(entry["threshold"])) is None:
                raise ValueError("Invalid threshold range")
            ranges.append((start, end))
        ranges.sort()
        if any(a[1] >= b[0] for a, b in zip(ranges, ranges[1:])) or any(
            sum(start <= p <= end for start, end in ranges) != 1 for p in PERIODS
        ):
            raise ValueError("Overlapping or missing threshold schedule")
        waived = json.loads(row["waived_periods"])
        if (
            not isinstance(waived, list)
            or len(set(waived)) != len(waived)
            or set(waived) - set(PERIODS)
        ):
            raise ValueError("Invalid waiver dates")
        for name in RULE_MAP:
            value = _number(row[name])
            if value is not None and value < 0:
                raise ValueError("Caps and triggers must be nonnegative")
        if row["springing_trigger_pct"] and (
            row["springing_operator"] != "LT" or float(row["springing_trigger_pct"]) != 25
        ):
            raise ValueError("Unsupported springing trigger")
    expected = {
        (r["borrower_id"], r["period_end"], c["covenant_id"])
        for r in financials
        for c in terms
        if c["borrower_id"] == r["borrower_id"]
    }
    if set(_unique(gold, ("borrower_id", "period_end", "covenant_id"))) != expected:
        raise ValueError("Gold cases do not cover all borrower-period-covenants")
    _unique(gold, ("gold_case_id",))
    statuses = {"PASS", "BREACH", "INDETERMINATE", "UNKNOWN_TRIGGER", "NOT_TESTED", "WAIVED"}
    for row in gold:
        term = covenant_by_id[row["covenant_id"]]
        active = next(
            e
            for e in schedules[row["covenant_id"]]
            if e["effective_from"] <= row["period_end"] <= e["effective_through"]
        )
        if (
            row["expected_status"] not in statuses
            or row["formula_id"] != term["formula_id"]
            or (row["financial_record_id"] != f"{row['borrower_id']}-{row['period_end']}")
            or float(row["threshold"]) != float(active["threshold"])
        ):
            raise ValueError("Gold identity, status or threshold is inconsistent")
        for name in ("expected_ratio", "headroom_ratio_points"):
            _number(row[name])
    if dict(Counter(r["expected_status"] for r in gold)) != manifest["status_counts"]:
        raise ValueError("Gold status distribution differs from manifest")
    if len(sources) != 40 or json.loads(members["sec_filing_manifest_40.json"]) != sources:
        raise ValueError("SEC manifests differ or do not contain 40 records")
    _unique(sources, ("sec_source_id",))
    _unique(sources, ("primary_html_url",))
    issuers = {}
    for row in sources:
        validate_document_id(row["sec_source_id"])
        if not "2025-01-01" <= _date(row["period_end"]) <= "2026-06-30" or not (
            row["period_end"] <= _date(row["filing_date"]) <= "2026-10-29"
        ):
            raise ValueError("SEC source is outside the package cutoff")
        for name in ("primary_html_url", "filing_index_url"):
            parsed = urlparse(row[name])
            if (
                parsed.scheme != "https"
                or parsed.hostname != "www.sec.gov"
                or not (parsed.path.startswith(f"/Archives/edgar/data/{int(row['cik'])}/"))
            ):
                raise ValueError("Expected a direct SEC archive URL")
        issuers.setdefault(row["cik"], Counter())[row["form_type"]] += 1
    if len(issuers) != 10 or any(c != {"10-K": 1, "10-Q": 3} for c in issuers.values()):
        raise ValueError("Expected ten issuers with one 10-K and three 10-Qs")
    return borrowers, financials, terms, sources


def import_bundle(archive: Path, data_root: Path, *, apply: bool = False) -> dict:
    """Validate/stage the complete import; publish only when explicitly requested."""
    required = (
        BORROWERS,
        FINANCIALS,
        "synthetic_covenants.csv",
        GOLD,
        SEC,
        "synthetic_manifest.json",
        "sec_filing_manifest_40.json",
    )
    with zipfile.ZipFile(archive) as bundle:
        if any(bundle.namelist().count(name) != 1 for name in required):
            raise ValueError("Missing or duplicate package member")
        if any(bundle.getinfo(name).file_size > 10_000_000 for name in required):
            raise ValueError("Unexpected package member size")
        members = {name: bundle.read(name) for name in required}
    borrowers, financials, terms, sources = _validate(members)
    synthetic = data_root / "app" / "synthetic"
    normalized_borrowers = [
        {
            "borrower_id": r["borrower_id"],
            "borrower_name": r["borrower_name"],
            "scenario": r["scenario_family"].lower(),
            "industry": r["industry"],
            "description": r["scenario_description"],
        }
        for r in borrowers
    ]
    normalized_financials = [
        {
            "borrower_id": r["borrower_id"],
            "period_end": r["period_end"],
            **{
                metric: r.get(next((k for k, v in METRIC_MAP.items() if v == metric), ""), "")
                for metric in FINANCIAL_METRICS
            },
            "notes": r["input_note"],
            "currency": r["currency"],
            "scale": "millions",
            "debt_source_status": r["debt_source_status"],
        }
        for r in financials
    ]
    normalized_terms = []
    for row in terms:
        for entry in json.loads(row["threshold_schedule"]):
            normalized_terms.append(
                {
                    "borrower_id": row["borrower_id"],
                    "covenant_id": row["covenant_id"].removeprefix(row["borrower_id"] + "-"),
                    "covenant_name": row["covenant_name"],
                    "effective_start": entry["effective_from"],
                    "effective_end": entry["effective_through"],
                    "metric_formula": row["formula_id"],
                    "operator": "<=" if row["direction"] == "MAX" else ">=",
                    "threshold": str(entry["threshold"]),
                    "unit": "x",
                    "testing_condition": "quarterly",
                    "cash_netting_rule": "none",
                    "addback_rule": "none",
                    "waiver_or_special_rule": "none",
                    "calculation_contract": "bundle_v1",
                    "waived_periods": row["waived_periods"],
                    **{target: row[source] for source, target in RULE_MAP.items()},
                }
            )
    normalized_sources = [
        {
            "document_id": r["sec_source_id"],
            "company": r["issuer_name"],
            "ticker": r["reference_ticker"],
            "cik": r["cik"],
            "document_type": r["form_type"],
            "document_date": r["filing_date"],
            "period_end": r["period_end"],
            "role": "periodic_filing",
            "source_url": r["primary_html_url"],
            "notes": r["selection_note"],
            **{
                k: r[k]
                for k in (
                    "accession_number",
                    "filing_index_url",
                    "html_identified_via",
                    "link_verified_as_of",
                    "selection_note",
                    "reference_ticker",
                )
            },
        }
        for r in sources
    ]
    outputs = {}
    for path, rows, keys in (
        (synthetic / "synthetic_borrowers.csv", normalized_borrowers, ("borrower_id",)),
        (
            synthetic / "synthetic_quarterly_financials.csv",
            normalized_financials,
            ("borrower_id", "period_end"),
        ),
        (
            synthetic / "synthetic_covenant_terms.csv",
            normalized_terms,
            ("borrower_id", "covenant_id", "effective_start"),
        ),
        (data_root / "app/sec/public_sec_documents.csv", normalized_sources, ("document_id",)),
    ):
        outputs[path] = _merge(path, rows, keys)
    catalog_rows = _csv(outputs[data_root / "app/sec/public_sec_documents.csv"])
    _unique(catalog_rows, ("source_url",))
    gold_path = data_root / "evaluation/synthetic_bundle_gold_cases.csv"
    if gold_path.exists() and gold_path.read_bytes() != members[GOLD]:
        raise ValueError("Conflicting authored bundle gold cases")
    outputs[gold_path] = members[GOLD]
    provenance = {
        "version": "credit-monitoring-bundle-v1",
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "member_sha256": {k: hashlib.sha256(v).hexdigest() for k, v in members.items()},
        "counts": {
            "borrowers": 25,
            "financials": 150,
            "covenants": 30,
            "gold_cases": 180,
            "sec_sources": 40,
        },
    }
    outputs[synthetic / "dataset_bundle_manifest.json"] = (
        json.dumps(provenance, indent=2, sort_keys=True) + "\n"
    ).encode()
    changed = [
        path
        for path, content in outputs.items()
        if not path.exists() or path.read_bytes() != content
    ]
    # Staging is deliberately outside the checkout for validation-only runs.
    with TemporaryDirectory(prefix="credit-bundle-") as temporary:
        stage = Path(temporary)
        for path, content in outputs.items():
            target = stage / path.relative_to(data_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        staged_source = stage / "app/synthetic/synthetic_quarterly_financials.csv"
        database = stage / "financials.sqlite3"
        load_financials(staged_source, database)
        SyntheticCovenantReader(stage / "app/synthetic/synthetic_covenant_terms.csv")
        with sqlite3.connect(database) as connection:
            connection.execute(
                "UPDATE quarterly_financials SET source_file = ?",
                ("data/app/synthetic/synthetic_quarterly_financials.csv",),
            )
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Staged database failed integrity check")
        if apply and changed:
            for path in changed:
                path.parent.mkdir(parents=True, exist_ok=True)
                replacement = path.with_suffix(path.suffix + ".tmp")
                replacement.write_bytes(outputs[path])
                replacement.replace(path)
            target = synthetic / "financials.sqlite3"
            replacement = target.with_suffix(".tmp")
            replacement.write_bytes(database.read_bytes())
            replacement.replace(target)
    return {
        "applied": apply,
        "changed_files": [str(p.relative_to(data_root)) for p in changed],
        **provenance["counts"],
    }
