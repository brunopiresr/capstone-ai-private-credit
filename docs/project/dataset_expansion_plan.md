# Expand the borrower and SEC use-case collection

Status: Proposed; implementation has not started.

## Summary

Add **25 fictional borrowers and 40 authentic SEC documents**, bringing the checked-in
totals to **37 synthetic borrowers and 69 SEC sources**.

Each new borrower will have six quarterly financial records, covering March 2025 through
June 2026, covenant terms, and independently calculated expected results. Public-company
evidence will remain separate from fictional financial data.

## Synthetic borrowers and scenarios

Assign IDs `SYN013`–`SYN037` and add distinct fictional names and industries.

| Borrowers | Five scenarios |
| --- | --- |
| SYN013–017 | Recovery after breach; debt repayment improving headroom; seasonal deterioration and recovery; debt-funded expansion causing breach; tightening thresholds causing breach despite stable financials |
| SYN018–022 | Leverage passes while coverage fails; leverage fails while coverage passes; two breaches followed by recovery; total versus net leverage differences; leverage passes while FCCR inputs are incomplete |
| SYN023–027 | Addback cap becomes binding; capped addbacks prevent false compliance; cash exceeds the netting cap; acquired EBITDA restores headroom; synergy cap prevents false compliance |
| SYN028–032 | Springing test activates into breach; exact 25% availability boundary; inactive test with missing calculation inputs; waiver followed by breach and recovery; waiver followed by testing under a tighter threshold |
| SYN033–037 | Missing EBITDA later supplied; zero/negative EBITDA followed by recovery; missing interest later supplied; missing springing trigger later resolved; conflicting debt sources later reconciled |

- Append **150 financial records** to the existing CSV and rebuild the bundled SQLite
  database using the existing preparation script.
- Give SYN018–022 two covenants each; give the remaining additions one covenant each.
- Add **180 synthetic gold cases**, covering every new borrower, quarter, and covenant.
- Use existing formula strings, caps, testing conditions, and waiver rules. Encode
  threshold changes through effective date ranges.
- Retain existing scenario-family identifiers for compatibility with the training
  generator; describe each new variation in borrower descriptions.
- Preserve blanks as missing values and distinguish them from explicit zeros. Keep
  expected outcomes out of runtime financial inputs.

## SEC documents and evaluation evidence

- Add four distinct SEC HTML documents for each of ten additional issuers: Wolverine
  World Wide, Interface, Select Medical, Cracker Barrel, Designer Brands, Victoria’s
  Secret, Conduent, Pitney Bowes, Bristow, and Children’s Place.
- For each issuer, select its latest annual report and three latest quarterly reports
  with period ends between January 2025 and June 2026, published by October 29, 2026.
  Preserve actual fiscal dates.
- Record verified issuer names, tickers, CIKs, document dates, reporting periods, and
  SEC archive URLs. These sources include suitable starting points such as
  [Wolverine’s quarterly filing](https://www.sec.gov/Archives/edgar/data/110471/000011047125000125/www-20250628.htm)
  and [Interface’s annual filing](https://www.sec.gov/Archives/edgar/data/715787/000071578726000006/tile-20251228.htm).
- Download all 40 documents and convert them through the existing HTML/Markdown
  pipeline, using the configured SEC identity.
- Keep full downloads in the existing ignored cache. Check in concise supporting
  excerpts and provenance for portable regression tests.
- Add at least one evidence-supported public gold case per document. Populate actual
  ratios, compliance conclusions, and headroom only when the source supports them;
  retain explicit gaps otherwise.
- Extend the evaluation task collection alongside both gold datasets. Preserve
  historical extraction snapshots and reports.

## Integration and interface changes

- Keep existing CSV schemas and calculation APIs.
- Make synthetic regression tests select results by covenant ID instead of assuming
  the first result.
- Add covenant selection to the mock benchmark for borrowers with multiple covenants;
  ensure displayed terms and history belong to that selection.
- Update dataset-size assertions, documentation counts, and scenario descriptions.
- Preserve existing borrowers and cases, retained training/model artifacts, and
  unrelated application work. No new covenant formulas or model retraining are included.

## Validation and acceptance

- Verify 37 synthetic borrowers, 172 total financial records, 69 catalog documents,
  unique identifiers, and valid cross-references.
- Confirm every new borrower appears in the working portfolio and all six periods
  are assessable.
- Compare all new synthetic results against independent expectations, including
  headroom, mixed outcomes, threshold changes, missing inputs, and trigger boundaries.
- Verify the bundled database matches its authored CSV and legacy cases retain
  their results.
- Confirm future financial records and evaluation labels cannot enter earlier
  assessments.
- Verify all 40 SEC files download and convert successfully; test their retained
  excerpts offline without network or model credentials.
- Run `make lint`, `make test-all`, and `make test-ml`. ML checks may generate temporary
  test artifacts; bundled training data and model files remain unchanged.
- Report download/conversion coverage separately from extraction accuracy; controlled
  regression results do not establish live model quality.
