# Public SEC gold-case comparison

Portable tests use controlled observations plus a small captured FMC regression,
without a local public cache or model calls:

```bash
uv run pytest tests/evaluation/extraction tests/unit/evaluation/test_sec_snapshot.py -q
```

Run the separate quality measurement with an explicit existing database:

```bash
uv run python scripts/compare_public_sec_gold.py \
  --database /absolute/path/to/covenants.sqlite3 \
  --output /tmp/public-sec-comparison --require-complete-sources
```

The runner opens SQLite read-only, selects each document's newest state by
`updated_at DESC, cache_key DESC` (including failures), and never creates a missing
database. `observations.json` freezes payloads and hashes, statuses, cache keys,
configuration versions and source hashes/URLs. `manifest.json` records revision,
gold/catalog/snapshot hashes. `report.json` contains per-field values and coverage;
`report.md` is the short case summary. `--catalog`, `--gold`, and `--sources`
select other inputs. No extraction or model request is made.

Replay without SQLite or the original source files:

```bash
uv run python scripts/compare_public_sec_gold.py \
  --snapshot /tmp/public-sec-comparison/observations.json \
  --output /tmp/public-sec-replay --require-complete-sources
```

Identical snapshots and gold inputs produce identical reports. A supported
mismatch, missing core fact, or wholly unevaluable comparison exits nonzero.
Without the strict flag, missing sources yield a partial comparison if available
core facts match; strict mode also fails incomplete source coverage. Unsupported
assessment targets are always reported separately, and never count as extracted
facts or make `is_complete` true. The historical 37 failures remain visible in the
[failure register](../../../docs/reviews/public_sec_benchmark_triage.md); green portable
tests do not mean public extraction quality passed.

`validate_gold_case(gold_row, extractions_by_document_id)` lives in
`credit_monitoring.evaluation.sec_gold` and returns per-field expected/observed
values, match/mismatch/missing status, missing sources, and unsupported targets.
It accepts existing `CovenantExtraction` objects. Controlled tests deliberately
supply incorrect observations; the captured fixture retains actual cached errors.

| CSV field | Test-side projection |
| --- | --- |
| `borrower` | V2 `issuer`, because this CSV identifies the catalog registrant; it does not establish the identity of a borrowing subsidiary. |
| `ticker` | V2 `ticker`; no inference from a document ID. |
| `covenant_name` | Case/whitespace normalization and removal of Maximum/Minimum prefixes; explicit Stoneridge compliance/net leverage alias. No fuzzy name matching. |
| `covenant_type` | Secured/total/net/rent-adjusted leverage maps to `leverage`; minimum revenue maps to `other`. The covenant name must also match. |
| `test_date` | Explicit schedule dates or inclusive ranges. Named dates take priority over redundant ranges; an undated schedule cannot establish applicability. |
| `threshold_value`, `unit` | Applicable `threshold_schedule[].threshold`, normalized with `Decimal`: ratio notation to `x`, USD amounts to millions. Ambiguous or incompatible units fail comparison. |
| `operator` | Explicit operator, or `maximum` → `<=` / `minimum` → `>=` when absent. `WAIVED` / `NOT_TESTED` map to dated waiver/suspension events instead. |
| `actual_value` | Named, period-matched `reported_financial_values` or covenant-specific `compliance_disclosures.reported_result`. Never populated from gold values. |
| `headroom` | Calculated in the test from observed thresholds, operators, and actuals. Actuals/headroom allow 0.005 rounding tolerance; thresholds compare exactly. |
| `gold_status` | Explicit dated disclosures: COMPLIANT/COMPLIANT_DISCLOSED → `compliant`, BREACH_DISCLOSED → `non_compliant`, BREACH_WAIVED → `waived_default`. WAIVED/NOT_TESTED use dated events. Other labels are unsupported assessments. |
| `source_document_ids` | Used fact evidence must belong to the listed sources; absent cache entries are reported separately. |

Agreement-wide compliance is considered only for `borrower_event` rows. It never
supplies individual covenant results. Applicable conflicting versions are all
compared, so a matching version cannot hide a stale threshold. Selecting legal
amendment precedence is beyond the current V2 extraction schema.

`amendment_applied`, free-text `waiver_status`, early-warning expectations, and
future-event assessments are explicitly unsupported. `case_id`, `cik`,
`evidence_grade`, `evaluation_mode`, `gold_rationale`, and `notes` are benchmark
metadata rather than extraction outputs. `is_complete` remains false while any
fact, source, or populated assessment field is missing or unsupported.
