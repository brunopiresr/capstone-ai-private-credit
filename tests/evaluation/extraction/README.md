# Public SEC gold-case comparison

Run the offline evaluation against the existing document extraction cache:

```bash
uv run pytest tests/evaluation/extraction/test_public_sec_gold_cases.py -v
```

Use `SEC_GOLD_DATABASE=/path/to/covenants.sqlite3` to select another cache. The
test opens SQLite in read-only mode and never processes documents or calls a model.
Each CSV case is a separate test. Cases with no completed source extraction skip.
Available cases fail on differing observed facts or missing core covenant facts.
When all listed sources are present, missing supported facts also fail. Partial
source coverage checks the available facts and records the missing fields; a
passing partial comparison does **not** establish full gold-case accuracy.

`validate_gold_case(gold_row, extractions_by_document_id)` accepts existing
`CovenantExtraction` objects. For an `ExtractionResult`, pass its `.extraction`;
for a processed document, pass `.result.extraction`. It returns a
`GoldCaseComparison` with per-field expected values, observed values, and `match`,
`mismatch`, or `missing` status, plus `missing_source_documents` and `unsupported`.
The test records this report as the `gold_comparison` JUnit property:

```bash
uv run pytest tests/evaluation/extraction/test_public_sec_gold_cases.py \
  --junitxml=/tmp/public-sec-gold.xml -o junit_family=legacy
```

All mappings live in the test file; extraction objects and application code are
unchanged. Controlled comparator tests use independent fixture observations and
deliberately incorrect facts; they do not measure live extraction accuracy.

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
