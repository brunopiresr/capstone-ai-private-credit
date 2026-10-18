# Public SEC benchmark triage — 18 October 2026

F07 reporting and reproducibility are implemented. **F07 extraction-quality acceptance remains open.** The unchanged pre-change observations produce **37 failing cases out of 42 evaluable cases**, with 215 matched, 39 mismatched and 115 missing supported fields. Five cases match supported facts; 117 populated assessment targets are outside the extraction contract. None of these five is a claim of full assessment accuracy. All 29 selected source Markdown files were present; presence does not prove that a catalog entry contains every necessary exhibit.

## Frozen evidence and replay

Full local artifacts: `data/processed/sec-evaluations/f05-f12-baseline/{observations,manifest,report}.json` and `report.md` (ignored). Replaying the named snapshot generated a byte-identical report and returned exit status 1. The original SQLite cache, source files, catalog and gold CSV were not rewritten. The portable two-document FMC fixture is tracked under `tests/fixtures/public_sec_snapshot/`.

Snapshot SHA-256: `650fb564d8a6e1b38e4396af564df00da4c5fb18b1d29b20602d8a118339a3bc`. Gold SHA-256: `b4ebb1a6575f942314550aa32ad0329a71981796dd932c01f3dbea079fba3718`. Catalog SHA-256: `8b342dc0e3a282b59dbe516b4f5fa3b3ea4dd71385f4f99b957786d2af8c5c2a`. Selection is newest `updated_at`, then `cache_key` descending, retaining failed states. The manifest identifies the repository revision and comparison-code hashes; each observation retains its model, prompt, conversion, segmentation, schema and payload hashes.

```bash
.venv/bin/python scripts/compare_public_sec_gold.py \
  --snapshot data/processed/sec-evaluations/f05-f12-baseline/observations.json \
  --output /tmp/public-sec-replay --require-complete-sources
```

## Corrections and remaining work

Extraction prompt v2.2 explicitly separates reported actuals from contractual limits, attaches comparison operators to their own metric, names schema categories and requires quotations from record text. These are source-supported instructions, **not a demonstrated accuracy fix**. Automatic post-extraction verification remains disabled. No cached output was edited; no gold value was supplied to extraction.

A live full-document refresh used original local HTML for three FMC filings in a separate cache, current cleaning, v2.2 and `openai-responses:gpt-4o-mini`. All three requests completed (1, 4 and 6 sections); all four supported FMC comparisons still failed. The amendment still borrowed the interest-coverage operator/quote for leverage; quarterly outputs introduced or confused limits and omitted dated actuals. This fresh result is distinct from the frozen 37-failure baseline. Artifacts: `data/processed/sec-evaluations/f05-f12-fmc-refresh/`. Further extraction design/model evaluation and explicit source/version decisions are required before claiming F07 complete.

## Follow-up experiments and deferred scope

The user deferred catalog/benchmark changes on 18 October 2026. Existing source
IDs, gold expectations, aliases and amendment-precedence rules remain unchanged.
F07 quality acceptance remains open for that later work.

Four isolated v2.2 probes retained exact inputs/results/model identities under
`data/processed/sec-evaluations/f05-f12-probes/`. Removing catalog notes alone did
not fix the small model's leverage operator. On the same complete amendment,
`openai-responses:gpt-4.1` separated both covenant families and used the correct
operators. The source's interest-coverage table repeats a leverage-column heading;
the tracked schedule fixture preserves this discrepancy.

Version 2.3 now excludes descriptive catalog notes from both single and batch
extraction inputs, preserving text, identity and offsets. This prevents those
notes from supplying apparent financial evidence. The prompt also preserves source
names and records contradictory headers without merging clauses. These changes
are tested without enabling automatic extraction verification.

A complete three-document v2.3 GPT-4.1 refresh finished all 11 sections in separate
storage. The existing comparator still fails all four FMC cases, but now finds no
mismatched fields. Actual ratios occur under expanded metric descriptions that
fail exact-name matching; agreement-wide compliance disclosures do not satisfy
individual covenant status expectations. No fuzzy matching or group-to-individual
projection was added. The application's default model is unchanged.

| FMC-only run | Matched fields | Mismatched | Missing under current projection | Passing cases |
| --- | --- | --- | --- | --- |
| Frozen pre-change observations | 32 | 8 | 4 | 0 / 4 |
| v2.2, default small model, complete documents | 31 | 10 | 3 | 0 / 4 |
| v2.3, GPT-4.1, complete documents | 32 | 0 | 12 | 0 / 4 |

The last experiment changes both model and input instructions; it is not a
controlled attribution of the full-run difference to either factor. Artifacts:
`data/processed/sec-evaluations/f05-f12-fmc-4-1/`, including replay inputs.

Two source gaps were independently resolved by inspecting the linked exhibits:

- Polaris Amendment No. 9, definitions and §6.25, contains the June 2025 limits
  (net leverage 4.00x and interest coverage 2.50x) absent from the cataloged summary.
  The contract names the metric Net Leverage Ratio. [SEC exhibit](https://www.sec.gov/Archives/edgar/data/931015/000162828025033840/amendmentno9to4tharcredita.htm).
- American Vanguard Amendment No. 12, §7, specifies September YTD EBITDA of
  $9.5 million and December YTD EBITDA of $35 million, resolving the malformed
  September number in the cataloged summary. [SEC exhibit](https://www.sec.gov/Archives/edgar/data/5981/000119312525183463/d21123dex101.htm).

These are source-backed candidates for the deferred catalog/benchmark work. No
new exhibit has been substituted into the frozen observations or gold cases.

## Selected cache states

| Document | Selected cache key |
| --- | --- |
| DOC_AVD_AMD11_2025 | `74d42980c9d232b09bb215054102a958f8c9ffbe37912fbd60f85b9a71a7402d` |
| DOC_AVD_AMD12_2025 | `25ea195396ff4fec5bf04852e0a7e53c582e332e14f9b996f65cb65451608e7f` |
| DOC_AVD_AMD8_2025 | `c26782af1e87396dcf49b60b6017a3e67832c2fd273c1e0f675464224f89f0ed` |
| DOC_AVD_Q1_2025 | `2d5f72d335945f520ea2f8a1e6e736416a34e1ad2a7b819f70617fc10cd9ae13` |
| DOC_AVITA_2024_10K | `f79ce7dc5de2f0c700ddb9b345a80ba2b7314315f1168c00f95d26640a90d26b` |
| DOC_AVITA_AMD5_2025 | `bba63bc53c305bc0e73377739405fcbbd70da649264e8e3d6c1582aecbc6913a` |
| DOC_AVITA_AMD6_2025 | `9d19fe4dda509effb37010e72c469023f33aadd942fd99dbfff8cfd0ec7165c2` |
| DOC_AVITA_Q2_2025 | `fc23bfd53c4a560b09cd99dff35dd934c187e8789a62d77c06c7c82c03eeeaa6` |
| DOC_AVITA_Q3_2025 | `a9b0303ea9ca93e8350430af75cc38012db6d6fe078decdde45f72eed45966b1` |
| DOC_FMC_AMD3_2025 | `48a4339f50a9e7ec2bc49e5f1c00ba9166db05f2f91cee977e91ace2ff3bc778` |
| DOC_FMC_Q1_2025 | `2a3314851ede8d55dab73eae624014ca960602025ff7c2664ed0ddad46df0507` |
| DOC_FMC_Q3_2025 | `9c10f44dc6f3eb1f895e962e623e38a6cd5f29d5f8e7654bcc71ee732adbb416` |
| DOC_FUNKO_2025_10K | `e1d084b9ead892fc57122b0d026a1c15302dfd188b36dd5f815a9aa83887fc7c` |
| DOC_FUNKO_Q2_2025 | `4661faacce4cc91f1d32eab374fa8f6d7c371361888b9ad08c62df01c3d715e5` |
| DOC_HAIN_10K_2025 | `44f86412fb639171d93693dd73a28f3abbddc5f2ebd52654e9d5c4dfb8fffb8f` |
| DOC_HAIN_AMD3_2025 | `6d4a7684280af26aa3dd565a372273c7a23e0766ec26bbed9202e2b349d82997` |
| DOC_HAIN_Q1_2025 | `5ac8aab08ad7d175787d7a1d63398f1a554c57f783120dd80a2f9bcd4a0065f0` |
| DOC_HAIN_Q3_2025 | `1581f12523c9ce8d8027dc2268c4dab03611596b4739ec78f9910c979377410c` |
| DOC_MCHP_2025_10K | `2b144b775a9a6c400e5fca28b14db0584988ab89594034c11b8bc81a6935e1f9` |
| DOC_MCHP_2026_10K | `f484f57463f18339e08931b475f83350a05778b1f48011bdfc4ac284c3536dc2` |
| DOC_POLARIS_2025_10K | `d370e239ba7ef5371abc61d52b0d26c7b1393cfb708aa5ee8f9958f0664d7b80` |
| DOC_POLARIS_AMD_2025 | `d76796c27ff28fb9e6b491efaf7f3602f819214b3afe50f94aaa083aebf51c52` |
| DOC_POLARIS_Q1_2026 | `96ec5393bc0df01cbbac48f3acf7b9e451ad31723399f5dac201fd5239fc5210` |
| DOC_SAGA_Q1_2026 | `750df686d2e92dce0bc7ce569506e735c4fa96d6c056ee06edadff9a8e7d042c` |
| DOC_STONE_AMD1_2025 | `271896ade37d217b3ee1fdd02478c1fa2fc6ce32ecb20f0356accab561e956b4` |
| DOC_STONE_Q1_2025 | `f25114317abf62d0288a1dece3f416fa7a44be0c1a40486f9e62fb5bacd2c2d9` |
| DOC_STONE_Q1_EARN_2025 | `e853476f7ade639c5482b32ffa305eb182d8b728d8b3bf73ac93fb3fe26c81a0` |
| DOC_STONE_Q3_EARN_2025 | `8b7b06ede8bd3c9883d4604f469c316d972e1985276e6aaf18e8b1def9c471da` |
| DOC_TILE_2025_10K | `10257ab3758c9ff7bfc35489c1de79c85e7dfade57d10b9e5615b1474f849686` |

## Source dispositions and every failing supported field

Each field row below uses the selected keys above and the case’s listed source IDs. `[]` means missing observed facts. Expected values are benchmark expectations, not injected observations. Group dispositions distinguish confirmed defects from unresolved source/precedence issues; they apply to every linked field row.

### FMC

Confirmed extraction defects: actuals used as thresholds, operators/quotes borrowed from another covenant, missing schedule dates and contradictory status. v2.2 adds explicit separation and provenance instructions. Captured FMC regression preserves the original failures; full-document live refresh still fails all four cases. Prompt-only correction is insufficient; source-grounded extraction accuracy remains open.

Inspected source evidence (line numbers refer to the frozen local Markdown):

- [DOC_FMC_AMD3_2025](https://www.sec.gov/Archives/edgar/data/37785/000003778525000013/amendmentno3tofifthamended.htm), local lines 37–54:

> Maximum Leverage Ratio. The U.S. Borrower shall maintain as of the last day of each Fiscal Quarter a Leverage Ratio of not more than 3.75:1.00; provided, however, that notwithstanding the foregoing, during the Covenant Relief Period, the U.S. Borrower shall maintain as of the last day of each Fiscal Quarter a Leverage Ratio of not more than the applicable level set forth below adjacent to such Fiscal Quarter:
>
> |  |  |  |  |  |  |
> | --- | --- | --- | --- | --- | --- |
> |  |  |  |  |  |  |
> | Fiscal Quarter | | | Maximum Leverage Ratio | | |
> | June 30, 2023 | | | 4.00 to 1.00 | | |
> | September 30, 2023 | | | 4.00 to 1.00 | | |
> | December 31, 2023 | | | 6.50 to 1.00 | | |
> | March 31, 2024 | | | 6.50 to 1.00 | | |
> | June 30, 2024 | | | 6.50 to 1.00 | | |
> | September 30, 2024 | | | 6.00 to 1.00 | | |
> | December 31, 2024 | | | 5.00 to 1.00 | | |
> | March 31, 2025 | | | 5.25 to 1.00 | | |
> | June 30, 2025 | | | 5.25 to 1.00 | | |
> | September 30, 2025 | | | 5.25 to 1.00 | | |
> | December 31, 2025 | | | 5.00 to 1.00 | | |
> | March 31, 2026 | | | 5.00 to 1.00 | | |

- [DOC_FMC_Q1_2025](https://www.sec.gov/Archives/edgar/data/37785/000003778525000065/fmc-20250331.htm), local lines 998–998:

> Our actual leverage for the four consecutive quarters ended March 31, 2025 was 4.77, which is below the maximum leverage of 5.25. Our actual interest coverage for the four consecutive quarters ended March 31, 2025 was 3.84, which is above the minimum interest coverage of 3.00. We were in compliance with all covenants at March 31, 2025.

- [DOC_FMC_Q3_2025](https://www.sec.gov/Archives/edgar/data/37785/000003778525000127/fmc-20250930.htm), local lines 1090–1090:

> Our actual leverage for the four consecutive quarters ended September 30, 2025 was 4.94, which is below the maximum leverage of 5.25. Our actual interest coverage for the four consecutive quarters ended September 30, 2025 was 3.93, which is above the minimum interest coverage of 3.00. We were in compliance with all covenants at September 30, 2025.

#### PUB_FMC_2025Q1_LEV

Sources: `DOC_FMC_AMD3_2025;DOC_FMC_Q1_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| gold_status | "compliant" | ["compliant", "non_compliant"] | mismatch |
| headroom | "0.48" | ["-0.48", "0.00", "0.48"] | mismatch |
| operator | "<=" | ["<", ">="] | mismatch |
| threshold_value | "5.25" | ["4.77", "5.25"] | mismatch |

#### PUB_FMC_2025Q1_ICR

Sources: `DOC_FMC_AMD3_2025;DOC_FMC_Q1_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| headroom | "0.84" | ["0.00"] | mismatch |
| threshold_value | "3.0" | ["3.84"] | mismatch |

#### PUB_FMC_2025Q3_LEV

Sources: `DOC_FMC_AMD3_2025;DOC_FMC_Q3_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| headroom | "0.31" | ["-0.31"] | mismatch |
| operator | "<=" | [">="] | mismatch |

#### PUB_FMC_2025Q3_ICR

Sources: `DOC_FMC_AMD3_2025;DOC_FMC_Q3_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| headroom | "0.93" | [] | missing |
| operator | ">=" | [] | missing |
| test_date | "2025-09-30" | [] | missing |
| threshold_value | "3.0" | [] | missing |


### HAIN

Confirmed metric/period mixing: the source distinguishes secured leverage, total leverage, interest coverage and new minimum EBITDA. The cache places unrelated limits in secured leverage and omits other terms/periods. v2.2 clarifies covenant families and own-metric evidence. Multiple amendment versions also overlap: retaining every version can disagree with a single governing-threshold expectation. No legal-precedence selection added. Fresh validation and version-aware benchmark disposition remain open.

Inspected source evidence (line numbers refer to the frozen local Markdown):

- [DOC_HAIN_Q1_2025](https://www.sec.gov/Archives/edgar/data/910406/000095017025065632/hain-20250331.htm), local lines 1779–1779:

> The Credit Agreement includes financial covenants that require compliance with a consolidated secured leverage ratio, a consolidated leverage ratio and a consolidated interest coverage ratio. On August 22, 2023, the Company entered into a Second Amendment (the “Second Amendment”) to the Credit Agreement. Pursuant to the Second Amendment, the Company’s maximum consolidated secured leverage ratio was amended to be 5.00:1.00 until September 30, 2023, 5.25:1.00 until December 31, 2023, 5.00:1.00 until December 31, 2024, and 4.25:1.00 thereafter. See below for a description of the Third Amendment (as defined below), which amended the Company’s maximum consolidated secured leverage ratio commencing with the quarter ending June 30, 2025. Pursuant to the Credit Agreement, the Company’s maximum consolidated leverage ratio is 6.00:1.00 and its minimum interest coverage ratio is 2.50:1.00. As of March 31, 2025, the Company’s consolidated secured leverage ratio, consolidated leverage ratio and consolidated interest coverage ratio were 4.23:1.00, 4.23:1.00 and 3.22:1.00, respectively, and the Company was in compliance with all associated covenants. The aforementioned financial covenants are being reported as calculated under the Credit Agreement and not pursuant to U.S. GAAP. Please refer to the Credit Agreement filed as an exhibit to our periodic reports for further information related to the calculation thereof. For risks related to our indebtedness and compliance with these covenants, please refer to the risk factor “Any default under our credit agreement could have significant consequences” set forth in Part I, Item 1A of our Annual Report on Form 10-K for the fiscal year ended June 30, 2024.

- [DOC_HAIN_Q3_2025](https://www.sec.gov/Archives/edgar/data/910406/000119312525272288/hain-20250930.htm), local lines 686–686:

> On September 11, 2025, the Company entered into a Fourth Amendment (the “Fourth Amendment”) to the Credit Agreement. Pursuant to the Fourth Amendment, (x) the Company’s maximum consolidated secured leverage ratio was amended to be 5.00:1.00 for the quarter ending June 30, 2025 and 5.50:1.00 for the quarter ending September 30, 2025 and thereafter, (y) the Company’s minimum consolidated interest coverage ratio was amended to be 2.00:1.00 for the quarter ending September 30, 2025 and thereafter and (z) a covenant was added requiring the Company to maintain a minimum Consolidated EBITDA (as such term is defined in the Credit Agreement as amended by the Fourth Amendment) of (i) $17,000 for the quarter ending September 30, 2025 and (ii) $52,000 for the cumulative two quarters ending September 30, 2025 and on December 31, 2025. The aforementioned financial covenants use financial measures that are defined under the Credit Agreement and not pursuant to U.S. GAAP.

- [DOC_HAIN_Q3_2025](https://www.sec.gov/Archives/edgar/data/910406/000119312525272288/hain-20250930.htm), local lines 1500–1500:

> As of September 30, 2025, the Company’s consolidated secured leverage ratio, consolidated leverage ratio and consolidated interest coverage ratio were 4.81:1.00, 4.81:1.00 and 2.92:1.00, respectively, and the Company was in compliance with all associated covenants. The aforementioned financial covenants are being reported as calculated under the Credit Agreement and not pursuant to generally accepted accounting principles in the U.S. (“GAAP”). Please refer to the Credit Agreement and amendments filed as exhibits to our periodic reports for further information related to the calculation thereof. For risks related to our indebtedness and compliance with these covenants, please refer to the risk factor “Any default under our credit agreement or inability to refinance our indebtedness could have significant consequences” set forth in Part I, Item 1A, “Risk Factors” of our Form 10-K for the fiscal year ended June 30, 2025.

#### PUB_HAIN_2025Q1_TOTLEV

Sources: `DOC_HAIN_Q1_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| headroom | "1.77" | [] | missing |
| operator | "<=" | [] | missing |
| test_date | "2025-03-31" | [] | missing |
| threshold_value | "6.0" | [] | missing |

#### PUB_HAIN_2025Q1_ICR

Sources: `DOC_HAIN_Q1_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| headroom | "0.72" | [] | missing |
| operator | ">=" | [] | missing |
| test_date | "2025-03-31" | [] | missing |
| threshold_value | "2.5" | [] | missing |

#### PUB_HAIN_2025Q3_SECLEV

Sources: `DOC_HAIN_AMD3_2025;DOC_HAIN_10K_2025;DOC_HAIN_Q3_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_type | "leverage" | ["leverage", "other"] | mismatch |
| headroom | "0.69" | ["-0.06", "-0.56", "-0.69", "-2.81", "0.06", "0.56", "0.69", "2.81"] | mismatch |
| operator | "<=" | ["<=", ">", ">="] | mismatch |
| threshold_value | "5.5" | ["17.00 million", "2", "4.25", "4.75", "5.5"] | mismatch |

#### PUB_HAIN_2025Q3_TOTLEV

Sources: `DOC_HAIN_Q3_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_name | "consolidated leverage ratio" | [] | missing |
| covenant_type | "leverage" | [] | missing |
| gold_status | "compliant" | [] | missing |
| headroom | "1.19" | [] | missing |
| operator | "<=" | [] | missing |
| test_date | "2025-09-30" | [] | missing |
| threshold_value | "6.0" | [] | missing |

#### PUB_HAIN_2025Q3_ICR

Sources: `DOC_HAIN_Q3_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_name | "consolidated interest coverage ratio" | [] | missing |
| covenant_type | "interest_coverage" | [] | missing |
| gold_status | "compliant" | [] | missing |
| headroom | "0.92" | [] | missing |
| operator | ">=" | [] | missing |
| test_date | "2025-09-30" | [] | missing |
| threshold_value | "2.0" | [] | missing |


### SRI

Source supports the reported compliance net-debt ratios, limits and dated waiver. Cache names/categories and dates do not consistently bind those facts. Existing explicit compliance/net leverage alias is retained; no fuzzy matching or new alias inferred solely to pass gold. v2.2 clarifies types; source-specific naming/period and waiver extraction remain open. Controlled name/event comparator tests remain active.

Inspected source evidence (line numbers refer to the frozen local Markdown):

- [DOC_STONE_Q1_2025](https://www.sec.gov/Archives/edgar/data/1043337/000104333725000092/sri-20250331.htm), local lines 774–776:

> •the maximum leverage ratio of 3.50 was increased to 6.00 for the quarter ended March 31, 2025, 5.50 for the quarter ended June 30, 2025, 4.50 for the quarter ended September 30, 2025 and 3.50 for the quarter ended December 31, 2025;
>
> •the minimum interest coverage ratio of 3.50 was waived for the quarter ended December 31, 2024 and was reduced to 2.00 for the quarters ended March 31 and June 30, 2025, and 2.50 and 3.50 for the quarter ended September 30, 2025 and December 31, 2025, respectively;

- [DOC_STONE_Q1_EARN_2025](https://www.sec.gov/Archives/edgar/data/1043337/000104333725000091/sri-20250430xexx992earni.htm), local lines 165–165:

> ing Letters of Credit $ 204.7Total Adjusted Debt (Compliance) $ 148.9Adjusted Net Debt (Compliance) 3.97xCompliance Leverage Ratio (Net Debt / TTM EBITDA) 6.00xCompliance Leverage Ratio Maximum Requirement

- [DOC_STONE_Q3_EARN_2025](https://www.sec.gov/Archives/edgar/data/1043337/000104333725000122/sri-20251105xexx992earni.htm), local lines 195–195:

> Total Adjusted Debt (Compliance) $ 135.0$ 129.5$ 149.0Adjusted Net Debt (Compliance) 3.67x3.60x3.39xCompliance Leverage Ratio (Net Debt / TTM EBITDA) 4.50x5.50x6.00xCompliance Leverage Ratio Maximum Requirement

- [DOC_STONE_AMD1_2025](https://www.sec.gov/Archives/edgar/data/1043337/000104333725000092/sri-20250331xexx102.htm), local lines 174–174:

> 3.1    Subject to the terms, conditions and limitations of this Amendment, including, without limitation, Section 5 below, the Administrative Agent and the Lenders hereby waive the Subject Default. The waiver provided for pursuant to the immediately preceding sentence (the “Subject Waiver”) shall not be construed to apply to the Loan Parties’ performance of (or failure to perform) the covenant set forth in Section 8.2.17 of the Credit Agreement for the fiscal quarter ending March 31, 2025 or beyond.

#### PUB_SRI_2024Q4_ICR_WAIVER

Sources: `DOC_STONE_AMD1_2025;DOC_STONE_Q1_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_type | "interest_coverage" | ["interest_coverage", "other"] | mismatch |
| gold_status | "waiver" | [] | missing |
| operator | "waiver" | [] | missing |

#### PUB_SRI_2025Q1_LEV

Sources: `DOC_STONE_AMD1_2025;DOC_STONE_Q1_EARN_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| actual_value | "3.97" | [] | missing |
| covenant_name | "net leverage ratio" | [] | missing |
| covenant_type | "leverage" | [] | missing |
| gold_status | "compliant" | [] | missing |
| headroom | "2.03" | [] | missing |
| operator | "<=" | [] | missing |
| source_document_ids | true | [] | missing |
| test_date | "2025-03-31" | [] | missing |
| threshold_value | "6.0" | [] | missing |

#### PUB_SRI_2025Q3_LEV

Sources: `DOC_STONE_AMD1_2025;DOC_STONE_Q3_EARN_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_type | "leverage" | ["other"] | mismatch |
| headroom | "1.11" | [] | missing |
| operator | "<=" | [] | missing |
| test_date | "2025-09-30" | [] | missing |
| threshold_value | "4.5" | [] | missing |


### PII

The amendment summary at line 70 says covenants changed but omits the numerical schedule; June-only cases list this summary alone. Later periodic debt notes explicitly state relief thresholds alongside baseline 3.00/3.50 limits. Cache omissions and baseline/relief confusion are confirmed, but the June cases need the underlying exhibit added to the catalog (confirmed above; deferred). v2.2 clarifies operators and limits; source selection and version applicability remain open. Gold unchanged.

Inspected source evidence (line numbers refer to the frozen local Markdown):

- [DOC_POLARIS_AMD_2025](https://www.sec.gov/Archives/edgar/data/931015/000162828025033840/pii-20250627.htm), local lines 70–70:

> On June 27, 2025, Polaris Inc. ("Polaris") entered into an amendment (the "Amendment") to its existing credit facility with U.S. Bank National Association, as administrative agent, and the lenders party thereto, dated as of July 2, 2018 (as amended from time to time prior to the date hereof, the "Existing Credit Agreement" and as amended by the Amendment, the "Amended Credit Agreement"). The Amendment amends the Existing Credit Agreement to, among other things: (i) extend the maturity date of the incremental term loan to June 26, 2026; (ii) modify the financial covenants in the Existing Credit Agreement for each quarter ending June 30, 2025 through and including June 30, 2026 (or such earlier date as designated by Polaris) (the "Covenant Relief Period"); (iii) limit Polaris during the Covenant Relief Period from repurchasing shares, paying dividends other than regular quarterly dividends (subject to a cap) and certain other exceptions and the amount of debt certain subsidiaries of Polaris may incur; and (iv) impose a requirement during the Covenant Relief Period that if Polaris fails to maintain an investment grade rating with at least two rating agencies, Polaris and certain of its domestic subsidiaries shall grant liens on substantially all of their domestic personal property (subject to customary exceptions).

- [DOC_POLARIS_2025_10K](https://www.sec.gov/Archives/edgar/data/931015/000162828026008033/R16.htm), local lines 7–7:

> maintain certain financial ratios, including minimum interest coverage and maximum leverage ratios. The agreements require the Company to maintain an interest coverage ratio of not less than 3.00 to 1.00 and a leverage ratio of not more than 3.50 to 1.00 on a rolling four quarter basis. The interest coverage ratio is calculated as Adjusted EBITDA to interest expense for the then most-recently ended four fiscal quarters. The leverage ratio is calculated as consolidated funded indebtedness less cash and cash equivalents, capped at $300 million, to Adjusted EBITDA for the then most-recently ended four fiscal quarters. The Credit Facility Amendment completed in June 2025 modified the requirements related to the interest coverage ratio and leverage ratio during the Covenant Relief Period. During the Covenant Relief Period, the interest coverage ratio is 2.50 to 1.00 for the quarters ending June 30, 2025, September 30, 2025 and December 31, 2025, and 2.00 to 1.00 for the quarters ending March 31, 2026 and June 30, 2026. During the Covenant Relief Period, the leverage ratio is 4.00 to 1.00 for the quarter ending June 30, 2025, 4.50 to 1.00 for the quarter ending September 30, 2025, and 5.50 to 1.00 for the quarters ending December 31, 2025, March 31, 2026 and June 30, 2026. The Company was in compliance with all such covenants as of December 31, 2025.  Senior notes. In November 2023, the Company issued $500 million aggregate principal amount of 6.95% Senior Notes due 2029 in an underwritten public offering. The Company received approximately $492 million in net proceeds from the o

- [DOC_POLARIS_Q1_2026](https://www.sec.gov/Archives/edgar/data/931015/000162828026027854/R14.htm), local lines 7–7:

> ements related to the interest coverage ratio and leverage ratio during the Covenant Relief Period. During the Covenant Relief Period, the interest coverage ratio is 2.50 to 1.00 for the quarters ending June 30, 2025, September 30, 2025 and December 31, 2025, and 2.00 to 1.00 for the quarters ending March 31, 2026 and June 30, 2026. During the Covenant Relief Period, the leverage ratio is 4.00 to 1.00 for the quarter ending June 30, 2025, 4.50 to 1.00 for the quarter ending September 30, 2025, and 5.50 to 1.00 for the quarters ending December 31, 2025, March 31, 2026 and June 30, 2026. The Company was in compliance with all such covenants as of March 31, 2026.  Senior notes. In November 2023, the Company issued $500 million aggregate principal amount of 6.95% Senior Notes due 2029 (the “6.95% Senior Notes”) in an underwritten public offering. The Company received approximately $492 million in net proceeds from the offering after deducting the underwriting discount and other fees and expenses. The 6.95% Senior Notes bear interest at a rate of 6.95% per year and mature in March 2029. In November 2025, the Company issued $500 million aggregate principal amount of 5.60% Senior Notes due 2031 (the “5.60% Senior Notes” and together with the 6.95% Senior Notes, the “senior notes”) in an underwritten public offering. The Company received approximately $497 million in net proceeds from the offering after deducting the underwriting discount and other fees and expenses. The 5.60% Senior Notes bear interest at a rate of 5.60% and mature in March 2031. All of the Company’s senior notes

#### PUB_PII_2025Q2_LEV

Sources: `DOC_POLARIS_AMD_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_name | "leverage ratio" | [] | missing |
| covenant_type | "leverage" | [] | missing |
| operator | "<=" | [] | missing |
| source_document_ids | true | [] | missing |
| test_date | "2025-06-30" | [] | missing |
| threshold_value | "4.0" | [] | missing |

#### PUB_PII_2025Q2_ICR

Sources: `DOC_POLARIS_AMD_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_name | "interest coverage ratio" | [] | missing |
| covenant_type | "interest_coverage" | [] | missing |
| operator | ">=" | [] | missing |
| source_document_ids | true | [] | missing |
| test_date | "2025-06-30" | [] | missing |
| threshold_value | "2.5" | [] | missing |

#### PUB_PII_2025Q4_LEV

Sources: `DOC_POLARIS_AMD_2025;DOC_POLARIS_2025_10K`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_name | "leverage ratio" | [] | missing |
| covenant_type | "leverage" | [] | missing |
| gold_status | "compliant" | [] | missing |
| operator | "<=" | [] | missing |
| source_document_ids | true | [] | missing |
| test_date | "2025-12-31" | [] | missing |
| threshold_value | "5.5" | [] | missing |

#### PUB_PII_2026Q1_LEV

Sources: `DOC_POLARIS_AMD_2025;DOC_POLARIS_Q1_2026`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| gold_status | "compliant" | [] | missing |
| operator | "<=" | [">="] | mismatch |
| threshold_value | "5.5" | ["3.5"] | mismatch |

#### PUB_PII_2026Q1_ICR

Sources: `DOC_POLARIS_AMD_2025;DOC_POLARIS_Q1_2026`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| threshold_value | "2.0" | ["3"] | mismatch |


### MCHP

The 2025 source preserves both an older 4.75 schedule and the new 6.25/5.75/4.75/4.00 schedule. Incorrect category/operator is an extraction defect; comparing both historical versions against one governing value is a separate benchmark/applicability limitation. v2.2 clarifies category/operator. Conflicting-version regression remains strict. Legal precedence is not inferred and this quality gate remains open.

Inspected source evidence (line numbers refer to the frozen local Markdown):

- [DOC_MCHP_2025_10K](https://www.sec.gov/Archives/edgar/data/827054/000082705425000077/mchp-20250331.htm), local lines 3882–3882:

> In November 2024, the amended and restated Credit Agreement, dated as of December 16, 2021 (as amended by the first incremental term loan amendment, dated as of August 31, 2023), was amended to amend the maximum total leverage ratio financial covenant for the quarterly periods ending on December 31, 2024 through December 31, 2025 to 4.75 to 1.00.

- [DOC_MCHP_2025_10K](https://www.sec.gov/Archives/edgar/data/827054/000082705425000077/mchp-20250331.htm), local lines 3886–3886:

> The Second Amended and Restated Credit Agreement amended the maximum total leverage ratio financial covenant to the following: 5.50 to 1.00 for period ending March 31, 2025, 5.50 to 1.00 for period ending June 30, 2025, 6.25 to 1.00 for period ending September 30, 2025, 5.75 to 1.00 for period ending December 31, 2025, 4.75 to 1.00 for period ending March 31, 2026, 4.00 to 1.00 for period ending June 30, 2026, 3.75 to 1.00 for period ending September 30, 2026, and 3.50 to 1.00 for any such period ended after the Restatement Effective Date that is not a period ending during the Covenant Relief Period. The Covenant Relief Period means the period following the Restatement Effective Date to (but excluding) the earlier of (a) December 31, 2026 and (b) the date in which the Total Leverage Ratio for the most recently ended fiscal quarter shall not exceed 3.50 to 1.00 and certain other conditions are satisfied.

- [DOC_MCHP_2026_10K](https://www.sec.gov/Archives/edgar/data/827054/000082705426000016/mchp-20260331.htm), local lines 3962–3962:

> The Second Amended and Restated Credit Agreement amended the maximum total leverage ratio financial covenant to the following: 5.50 to 1.00 for period ending March 31, 2025, 5.50 to 1.00 for period ending June 30, 2025, 6.25 to 1.00 for period ending September 30, 2025, 5.75 to 1.00 for period ending December 31, 2025, 4.75 to 1.00 for period ending March 31, 2026, 4.00 to 1.00 for period ending June 30, 2026, 3.75 to 1.00 for period ending September 30, 2026, and 3.50 to 1.00 for any such period ended after the Restatement Effective Date that is not a period ending during the Covenant Relief Period. The Covenant Relief Period means the period following the Restatement Effective Date to (but excluding) the earlier of (a) December 31, 2026 and (b) the date in which the Total Leverage Ratio for the most recently ended fiscal quarter shall not exceed 3.50 to 1.00 and certain other conditions are satisfied.

#### PUB_MCHP_2025Q3_LEV

Sources: `DOC_MCHP_2025_10K`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_type | "leverage" | ["leverage", "other"] | mismatch |
| operator | "<=" | [">="] | mismatch |

#### PUB_MCHP_2025Q4_LEV

Sources: `DOC_MCHP_2025_10K`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_type | "leverage" | ["leverage", "other"] | mismatch |
| operator | "<=" | [">="] | mismatch |
| threshold_value | "5.75" | ["4.75", "5.75"] | mismatch |

#### PUB_MCHP_2026Q1_LEV

Sources: `DOC_MCHP_2026_10K`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_type | "leverage" | ["leverage", "other"] | mismatch |
| operator | "<=" | [] | missing |

#### PUB_MCHP_2026Q2_LEV

Sources: `DOC_MCHP_2026_10K`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_type | "leverage" | ["leverage", "other"] | mismatch |
| operator | "<=" | [] | missing |


### AVD

Source explicitly discloses March defaults, June/September suspensions and distinct FCCR limits; cache categories and dated event associations omit/misclassify them. v2.2 clarifies named categories but waiver/suspension completeness needs fresh validation. The twelfth-amendment summary prints "$9,500,00" for September YTD EBITDA: the underlying exhibit confirms 9.5 million (see follow-up above); adding that source is deferred, and the summary text is not silently repaired. No gold correction or unsupported numeric inference made.

Inspected source evidence (line numbers refer to the frozen local Markdown):

- [DOC_AVD_AMD8_2025](https://www.sec.gov/Archives/edgar/data/5981/000119312525054368/d903583d8k.htm), local lines 77–77:

> The Amendment, among other things, modified the Maximum Total Leverage Ratio to 6.25 for the periods ending March 31, 2025 and June 30, 2025; 5.75 for the period ending September 30, 2025; and returning to 3.25 for the periods ending December 31, 2025, and thereafter. The Minimum Fixed Charge Coverage Ratio was modified to 1.15 for the period ending March 31, 2025, and returning to 1.25 for the period ending June 30, 2025 and thereafter. The amount of borrowing capacity under the revolving credit facility was reduced by $50,000,000 through June 30, 2025, $40,000,000 from July 1, 2025 through December 31, 2025, and $75,000,000 from January 1, 2026 through the Revolver Commitment Termination Date. In addition, the Company may not repurchase shares, pay cash dividends to shareholders, or make Permitted Acquisitions without the lenders’ consent.

- [DOC_AVD_AMD11_2025](https://www.sec.gov/Archives/edgar/data/5981/000095017025078615/avd-ex10_26.htm), local lines 13–15:

> WHEREAS, Events of Default has occurred under Section 10.3.1 and Section 10.3.2 of the Loan Agreement (the “Existing Events of Default”) as a result of the failure of Borrowers to be in compliance with the Total Leverage Ratio covenant and Fixed Charge Coverage Ratio covenant as of March 31, 2025.
>
> WHEREAS, Holdco and Borrowers have requested that the Required Lenders agree to (i) suspend testing of the Total Leverage Ratio covenant for the periods ending June 30, 2025, September 30, 2025 and December 31, 2025, and amend the Total Leverage Ratio covenant for the periods on and after March 31, 2026, (ii) suspend testing of the Fixed Charge Coverage Ratio covenant for the period ending June 30, 2025, and amend the Fixed Charge Coverage Ratio covenant for the periods ending on and after September 30, 2025, and (iii) waive the Existing Events of Default

- [DOC_AVD_AMD11_2025](https://www.sec.gov/Archives/edgar/data/5981/000095017025078615/avd-ex10_26.htm), local lines 119–131:

> . Commencing on the Fiscal Quarter ended September 30, 2025, maintain a Fixed Charge Coverage Ratio, measured on a Fiscal Quarter-end basis, of not less than the applicable ratio set forth in the following table for the applicable date set forth opposite thereto:
>
> ---
>
> |  |  |
> | --- | --- |
> |  |  |
> | Fiscal Quarter Ending | Minimum Fixed Charge Coverage Ratio |
> | September 30, 2025 | 1.00:1.00 |
> | December 31, 2025, and each Fiscal Quarter thereafter | 1.25:1.00 |
>
> 2.10.
>

- [DOC_AVD_AMD12_2025](https://www.sec.gov/Archives/edgar/data/5981/000119312525183463/d21123d8k.htm), local lines 79–79:

> The Amendment also included additional changes to the Loan Agreement, including: (i) amending the applicable margins for the applicable interest rates and unused line fee and letter of credit fee; (ii) adding a year-to-date Consolidated EBIDTA requirement of $4,500,000 as of June 30, 2025, $9,500,00 as of September 30, 2025 and $35,000,000 as of December 31, 2025 and a TTM Consolidated EBITDA requirement of not less than $37,500,000 as of March 31, 2026; (iii) requiring the Company to make prepayments on the loans once the Company’s cash balance exceeds a threshold; and (iv) suspending the Total Leverage Ratio covenant until June 30, 2026 and then applying a fiscal quarter end ratio of 4.00:1.00.

#### PUB_AVD_2025Q1_LEV_BREACH

Sources: `DOC_AVD_AMD8_2025;DOC_AVD_AMD11_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_type | "leverage" | ["leverage", "other"] | mismatch |
| gold_status | "non_compliant" | [] | missing |
| operator | "<=" | [">="] | mismatch |

#### PUB_AVD_2025Q1_FCCR_BREACH

Sources: `DOC_AVD_AMD8_2025;DOC_AVD_AMD11_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_type | "fixed_charge_coverage" | ["other"] | mismatch |
| gold_status | "non_compliant" | [] | missing |
| operator | ">=" | [] | missing |
| test_date | "2025-03-31" | [] | missing |
| threshold_value | "1.15" | [] | missing |

#### PUB_AVD_2025Q2_LEV_SUSPENDED

Sources: `DOC_AVD_AMD11_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_type | "leverage" | ["other"] | mismatch |
| gold_status | "suspension" | [] | missing |
| operator | "suspension" | [] | missing |

#### PUB_AVD_2025Q2_FCCR_SUSPENDED

Sources: `DOC_AVD_AMD11_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_type | "fixed_charge_coverage" | ["other"] | mismatch |
| gold_status | "suspension" | [] | missing |
| operator | "suspension" | [] | missing |

#### PUB_AVD_2025Q3_LEV_SUSPENDED

Sources: `DOC_AVD_AMD11_2025;DOC_AVD_AMD12_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_type | "leverage" | ["other"] | mismatch |
| gold_status | "suspension" | [] | missing |
| operator | "suspension" | [] | missing |

#### PUB_AVD_2025Q3_FCCR

Sources: `DOC_AVD_AMD11_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_type | "fixed_charge_coverage" | ["other"] | mismatch |

#### PUB_AVD_2025Q3_EBITDA

Sources: `DOC_AVD_AMD12_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_name | "year-to-date consolidated ebitda" | [] | missing |
| covenant_type | "minimum_ebitda" | [] | missing |
| operator | ">=" | [] | missing |
| source_document_ids | true | [] | missing |
| test_date | "2025-09-30" | [] | missing |
| threshold_value | "9.5" | [] | missing |

#### PUB_AVD_2025Q4_EBITDA

Sources: `DOC_AVD_AMD12_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_name | "year-to-date consolidated ebitda" | [] | missing |
| covenant_type | "minimum_ebitda" | [] | missing |
| operator | ">=" | [] | missing |
| source_document_ids | true | [] | missing |
| test_date | "2025-12-31" | [] | missing |
| threshold_value | "35.0" | [] | missing |


### RCEL

Source explicitly provides trailing-12-month net revenue requirements, quarter-specific waivers and later amendments. Exact-name matching cannot find the benchmark term in these observations. Missing facts therefore do not establish absence from source. Name/measure identity and dated waiver scope need source-grounded repair; preserve historical 73/78/84/92 limits and later amendments separately. No broad alias, legal precedence or gold repair introduced.

Inspected source evidence (line numbers refer to the frozen local Markdown):

- [DOC_AVITA_Q2_2025](https://www.sec.gov/Archives/edgar/data/1762303/000176230325000014/rcel-20250630.htm), local lines 482–482:

> In connection with the Long-term debt described in Note 6 to the Consolidated Financial Statements, the Company will need to be in compliance with a minimum trailing 12-month net revenue at the end of each quarter and maintain a minimum quarterly cash and cash equivalents balance. The Company was not in compliance with the trailing 12-month net revenue covenants for the first quarter of 2025 and the second quarter of 2025. On March 31, 2025, the Company received a waiver related to the trailing 12-month net revenue covenant for the first quarter of 2025, which was set at $73.0 million. On June 30, 2025, the Company received a waiver related to the trailing 12-month net revenue covenant for the second quarter of 2025, which was set at $78.0 million. On August 7, 2025, the Company amended the Credit Agreement (as defined in Note 6 to the Consolidated Financial Statements), to amend the trailing 12-month revenue covenant to $73.0 million for the quarter ending September 30, 2025, to $77.0 million for the quarter ending December 31, 2025, to $90.0 million for the quarter ending March 31, 2026, and to $103.0 million for the quarter ending June 30, 2026. The $115.0 million revenue covenant for all subsequent quarters through the date of debt maturity remains in effect. See Note 16 to the Consolidated Financial Statements for additional information regarding the amendment. As of June 30, 2025, the Company was in compliance with all other quantitative financial covenants in the Credit Agreement.

- [DOC_AVITA_AMD6_2025](https://www.sec.gov/Archives/edgar/data/1762303/000119312525269535/rcel-20251105.htm), local lines 74–74:

> The Sixth Amendment modifies the trailing 12-month revenue covenant to $70.0 million for the quarter ending December 31, 2025. The revenue covenants for all subsequent quarters through the Maturity Date (as defined in the Credit Agreement) remain in effect. The Sixth Amendment also waived a requirement that the Company’s Quarterly Report on Form 10-Q not contain any qualification or statement which is of a “going concern” or similar nature for the quarter ending September 30, 2025.

#### PUB_RCEL_2025Q1_REV_BREACH

Sources: `DOC_AVITA_2024_10K;DOC_AVITA_Q2_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_name | "trailing-12-month net revenue" | [] | missing |
| covenant_type | "other" | [] | missing |
| gold_status | "waived_default" | [] | missing |
| operator | ">=" | [] | missing |
| source_document_ids | true | [] | missing |
| test_date | "2025-03-31" | [] | missing |
| threshold_value | "73.0" | [] | missing |

#### PUB_RCEL_2025Q2_REV_BREACH

Sources: `DOC_AVITA_Q2_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_name | "trailing-12-month net revenue" | [] | missing |
| covenant_type | "other" | [] | missing |
| gold_status | "waived_default" | [] | missing |
| operator | ">=" | [] | missing |
| source_document_ids | true | [] | missing |
| test_date | "2025-06-30" | [] | missing |
| threshold_value | "78.0" | [] | missing |

#### PUB_RCEL_2025Q3_REV_BREACH

Sources: `DOC_AVITA_AMD5_2025;DOC_AVITA_Q3_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_name | "trailing-12-month net revenue" | [] | missing |
| covenant_type | "other" | [] | missing |
| gold_status | "waived_default" | [] | missing |
| operator | ">=" | [] | missing |
| source_document_ids | true | [] | missing |
| test_date | "2025-09-30" | [] | missing |
| threshold_value | "73.0" | [] | missing |

#### PUB_RCEL_2025Q4_REV

Sources: `DOC_AVITA_AMD5_2025;DOC_AVITA_AMD6_2025`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_name | "trailing-12-month net revenue" | [] | missing |
| covenant_type | "other" | [] | missing |
| operator | ">=" | [] | missing |
| source_document_ids | true | [] | missing |
| test_date | "2025-12-31" | [] | missing |
| threshold_value | "70.0" | [] | missing |


### SGA

Source states minimum FCCR 1.15, actual 0.92, March noncompliance and May waiver solely for March. Wrong category/operator and absence of the dated waived-default association are extraction defects; negative headroom is independently consistent with the source. v2.2 addresses category/operator; waiver linkage and a fresh supported-fact pass remain open.

Inspected source evidence (line numbers refer to the frozen local Markdown):

- [DOC_SAGA_Q1_2026](https://www.sec.gov/Archives/edgar/data/886136/000110465926057921/sga-20260331x10q.htm), local lines 1170–1172:

> As of March 31, 2026, the Company was not in compliance with the minimum fixed charge coverage ratio covenant under its Credit Agreement which requires the Company to maintain a minimum fixed charge coverage ratio of 1.15 to 1.00 at the end of each fiscal quarter. At March 31, 2026, the Company’s fixed charge coverage ratio was 0.92 to 1.00, constituting an event of default under the Credit Agreement.
>
> On May 7, 2026, the Company obtained a waiver from its lenders for this covenant violation (the “Waiver”). The Waiver applies solely to the noncompliance as of March 31, 2026 and does not modify the covenant requirements for future periods unless otherwise amended.

#### PUB_SGA_2026Q1_FCCR

Sources: `DOC_SAGA_Q1_2026`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_type | "fixed_charge_coverage" | ["other"] | mismatch |
| gold_status | "waived_default" | ["non_compliant"] | mismatch |
| headroom | "-0.23" | ["-0.23", "0.23"] | mismatch |
| operator | ">=" | ["<", ">="] | mismatch |


### TTSH

Source separately states FCCR minimum 1.20 and rent-adjusted leverage maximum 3.50, followed by agreement-wide noncompliance and January waiver. Cache mixes categories/limits/operators and lacks the borrower event. v2.2 clarifies own-metric evidence; event extraction remains open. Agreement-wide compliance is still not projected onto individual covenant results.

Inspected source evidence (line numbers refer to the frozen local Markdown):

- [DOC_TILE_2025_10K](https://www.sec.gov/Archives/edgar/data/1552800/000155280026000006/c800-20251231x10k.htm), local lines 1033–1033:

> The Credit Agreement is secured by virtually all of our assets, including but not limited to, inventory, accounts receivable, equipment and general intangibles. The Credit Agreement contains customary events of default, conditions to borrowing and restrictive covenants, including restrictions on our ability to dispose of assets, engage in acquisitions or mergers, make distributions on or repurchases of capital stock, incur additional debt, incur liens or make investments. The Credit Agreement also includes financial and other covenants, including covenants to maintain a Fixed Charge Coverage Ratio (as defined in the Credit Agreement) of no less than 1.20 to 1.00 and a Rent Adjusted Leverage Ratio (as defined in the Credit Agreement) of no greater than 3.50 to 1.00. The Company was not in compliance with the covenants as of December 31, 2025 but received a waiver by the lenders January 28, 2026, which put the Company in compliance with the covenants.

#### PUB_TTSH_2025Q4_FCCR

Sources: `DOC_TILE_2025_10K`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_type | "fixed_charge_coverage" | ["interest_coverage", "other"] | mismatch |
| threshold_value | "1.2" | ["1.20", "3.5"] | mismatch |

#### PUB_TTSH_2025Q4_RALR

Sources: `DOC_TILE_2025_10K`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| covenant_type | "leverage" | ["other"] | mismatch |
| operator | "<=" | ["<=", ">="] | mismatch |

#### PUB_TTSH_2025Q4_EVENT

Sources: `DOC_TILE_2025_10K`.

| Field | Expected | Observed | Status |
| --- | --- | --- | --- |
| gold_status | "waived_default" | [] | missing |
| source_document_ids | true | [] | missing |
