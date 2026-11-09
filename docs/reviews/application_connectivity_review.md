# Application connectivity and workflow review

The main workspace (`make preview`) connects Streamlit to Python application services,
SQLite repositories, the bundled risk model, configured AI models, SEC downloads, and
optional Logfire telemetry. Analyst and risk manager actions share saved records.

## Issues corrected

- Opening a borrower from Portfolio now carries the selected period, cutoff, and saved
  assessment version, including when the analyst previously visited that borrower.
- Risk review displays credit reviews eligible at the selected information cutoff.
  Manager comments identify the visible review; completing review is blocked when a
  newer review requires a later cutoff. Review history follows the same cutoff.
- The main workspace loads its environment and initializes telemetry at startup.
- Credit review prompts distinguish registered evidence IDs from data field names.
  A rejected citation receives the actual allowed IDs during its bounded repair attempt.
- Follow-up generation constrains reference paths to existing findings in the selected
  saved analysis. Missing findings are excluded. The schema retains up to 128 paths,
  visiting parent findings before detailed nested inputs. Invalid paths remain rejected;
  generated outputs use the same public models as reloaded saved questions.

## Connection checks

Live checks used fictional borrower evidence and temporary storage. The separate
follow-up check read an existing fictional review through a read-only database connection
and saved its generated questions in temporary storage.

| Connection or workflow | Observed result |
| --- | --- |
| Portfolio calculations and persistence | All 37 borrowers assessed and saved; no failed assessments |
| Bundled Logistic Regression | 34 complete forecasts; SYN007, SYN010, and SYN030 explicitly unavailable because no covenant has usable current numeric inputs |
| Configured AI credentials | Authenticated provider request accepted |
| Credit review | Bullish, bearish, and recommendation stages completed after evidence-reference repairs |
| Follow-up questions | Three questions generated in one request after constraining paths; saved assessment and review IDs matched |
| Credit assistant | Completed a response using saved evidence without recalculation |
| Analyst handoff and manager decision | Submission restored through fresh service handles and marked reviewed |
| Board reporting | Report draft saved and finalized |
| Document processing | Synthetic HTML converted and extracted successfully |
| SEC download | Catalog filing downloaded successfully through the application's loader |
| Logfire | Live validation accepted seven batches of synthetic telemetry |

## Verification and limits

Regression coverage checks navigation, date and version scope, manager sign-off,
telemetry initialization, citation repairs, and constrained follow-up references.
Final `make test-all` results: 940 application tests passed; 93 homework tests passed
and six optional live scenarios skipped. `make lint` passed. These checks include the
new regression coverage and the existing calculation, storage, document, and UI suites.

This remains a local POC without authentication or role-based access enforcement.
Analyst and manager workflows are separate screens in the same trusted workspace.
Live news, notifications, and PDF export remain unavailable. The risk model uses
synthetic training data, and public SEC extraction retains its
[recorded quality limits](public_sec_benchmark_triage.md). Connection smoke checks
and valid reference paths do not establish the factual quality of every AI answer.
