# SEC extraction fixtures

`records.json` contains labeled synthetic excerpts, not claims about real SEC filings.
Workflow tests use controlled models/HTTP responses to check input preservation,
parsing, provenance, serialization, and failures. They do not measure live extraction
accuracy or prompt-injection resistance.

| Prompt snapshot | Version |
| --- | --- |
| `extraction_prompt_v2.txt` | Historical v2.0 |
| `extraction_prompt_v2_1.txt` | Historical v2.1 |
| `extraction_prompt_v2_2.txt` | Historical v2.2 |
| `extraction_prompt_v2_3.txt` | Active v2.3 |

Snapshots preserve exact prompt bytes and require deliberate versioned updates.
Version 2.2 separates actuals from limits and ties operators/quotes to their covenant.
Version 2.3 preserves source names and records contradictory headers; extraction
inputs exclude descriptive catalog notes.

`fmc_amendment_schedule.md` preserves all 19 leverage and 17 interest-coverage quarters
from `DOC_FMC_AMD3_2025`, including continuation rows. Mocked pipeline checks verify
complete input delivery. The optional local SEC regression skips if its ignored
Markdown source is absent. See [public benchmark findings](../../../v2-plan/archive/quality/public-sec-benchmark-triage.md).
