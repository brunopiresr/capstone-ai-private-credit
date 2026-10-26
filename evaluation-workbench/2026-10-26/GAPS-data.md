# Data gaps

1. **Two full exhibits are not acquired.** `SEC_USER_AGENT` is absent from the environment
   and local `.env`. No identifying name/email was invented. Both official URLs were
   inspected through web research; local HTML/Markdown files remain absent. Cases needing
   these IDs must report blocked, not silently use the cataloged summaries:
   - `EVAL_DOC_POLARIS_AMD9_FULL_2025` — [Polaris Amendment 9, full Exhibit 10.1](https://www.sec.gov/Archives/edgar/data/931015/000162828025033840/amendmentno9to4tharcredita.htm).
     Definitions and §6.25 distinguish net leverage from interest coverage and contain
     June 2025 limits absent from the existing summary.
   - `EVAL_DOC_AVD_AMD12_FULL_2025` — [American Vanguard Amendment 12, full Exhibit 10.1](https://www.sec.gov/Archives/edgar/data/5981/000119312525183463/d21123dex101.htm).
     Section 7 supplies the unambiguous September YTD EBITDA requirement; the existing
     summary contains a malformed number. Existing Amendment 11 also corroborates the
     amount but is deliberately excluded from summary-only cases.

2. **Real borrower financial analysis inputs are not added.** Existing loaded financial
   records and the eight added rows are synthetic. Public contract limits and disclosed
   ratios do not establish independently reconstructible covenant EBITDA. Do not map
   synthetic financials to public issuers.

3. **Publication availability remains unknown where absent.** Reporting period,
   amendment date and database load time are not filing availability. Public questions
   are retrospective unless independently verified availability supports a stricter
   cutoff. No unsupported `available_at` CSV column is introduced.

4. **Existing source/gold issues remain open.** All 29 source copies are present, but
   the historical 37/42 failed comparison baseline is not cleared by data preparation.
   Business references must be grounded in source text. Current public grade B/C data
   cannot establish independent bespoke EBITDA calculations.

5. **Raw source length exceeds judge limits for some cases.** Preserve complete inputs
   and traces, then build task-specific anchored judge evidence. Do not truncate silently
   or claim the judge checked whole-document extraction completeness.
