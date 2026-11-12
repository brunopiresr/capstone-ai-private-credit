# Decision 002: keep structured agent output and backend Markdown rendering

Date: 12 November 2026. Status: accepted and implemented.

## Context

Assistant messages should display as Markdown in Streamlit and notebooks without
custom client parsing of model JSON, sections, tables or citations. The model returns
structured answer fields. Previously, the backend escaped narrative Markdown while
adding its own Markdown headings and tables, producing inconsistent formatting.

## Decision

Retain structured model output and keep
[`agents/answer_contract.py`](../../../src/credit_monitoring/agents/answer_contract.py)
as the shared backend formatter. Allow Markdown in summaries, finding text, gaps and
diligence questions. The backend assembles these fields into `AnswerContent.answer`;
clients pass that string directly to their normal Markdown component.

The formatter owns section layout, table rendering, citation labels, literal escaping
of table/citation data, and narrative handling for HTML, currency and code blocks.
Selected filing tables are materialized upstream from loaded extractions before
formatting. Preview snapshots and final answers use the same rendering function.

Confidence remains separately displayed, the answer schema stays at `agent-answer-v3`,
and historical stored messages load without being regenerated or unescaped. Failure
messages remain literal. Credit-review reports use a separate presentation path.

## Why keep the formatter?

With structured model output, something must assemble the fields into a display
message. Keeping that work in one backend module gives notebook and web clients the
same output and keeps table and citation formatting under application control.
The formatter does not verify factual accuracy, citation support or financial results;
formatting is distinct from validation.

The separate filename is an organizational choice. Moving these functions into another
module would retain the same responsibilities and complexity.

## Alternatives and tradeoffs

- **Have the LLM return complete Markdown directly.** This could remove most assembly
  code, but the model would control table structure and citation formatting. Keeping
  additional structured fields would also require managing consistency between those
  fields and the generated message. We retain backend assembly for the current design.
- **Assemble messages in each client.** This would duplicate formatting logic and
  require client parsing or reconstruction, conflicting with the display goal.
- **Merge the formatter into the agent or UI.** This would reduce the file count while
  leaving the formatting work in place and coupling it to execution or a specific UI.

This decision improves formatting consistency and preserves a simple client contract.
It does not promise a reduction in total backend code: Markdown handling still needs
to preserve literal data, code and currency. Revisit direct model-authored Markdown if
the application no longer needs structured answer fields and backend-controlled tables.

## Validation

Implementation verification on 12 November 2026: 371 tests passed across agent/covenant
unit tests, Streamlit-app and Streamlit-V3 integration tests, and notebook tests.
Ruff and changed-file formatting checks passed. Coverage includes narrative Markdown,
literal tables/citations, streaming, nested code, currency, failures and historical
answers. These checks establish rendering behavior, not generated-answer accuracy.

Implementation details are recorded in the
[Markdown plan](../../../v2-plan/AGENT_MARKDOWN_PLAN.md).
