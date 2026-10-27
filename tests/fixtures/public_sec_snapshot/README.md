# Captured public SEC observations

`fmc_observations.json` preserves two complete, unmodified result payloads from the
18 October 2026 pre-change SQLite snapshot. These are captured cached observations,
not hand-authored model outputs. Other documents were omitted to keep the fixture
small. Payload hashes and original cache configuration are retained; absolute
source paths are historical metadata and are never opened by the portable test.

`fmc_source_excerpts.json` contains exact local Markdown slices, original line and
character locations, full-source hashes, and SEC URLs. Source excerpts establish
that 4.77 and 3.84 are actuals, while 5.25 and 3.00 are contractual limits. The
amendment cache incorrectly borrows an interest-coverage operator/quotation for
leverage. Tests retain these failures rather than substituting expected outputs.

See [triage](../../../docs/reviews/public_sec_benchmark_triage.md) for the full baseline,
the extraction prompt correction, and the separate live refresh results. These
fixtures prove detection and replay, not that the revised prompt always succeeds.
