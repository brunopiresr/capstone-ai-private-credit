# Let the agent discover what each request needs

## Summary

Keep one agent. Replace scenario-specific instructions with a general decision process: understand the requested outcome, choose the necessary action, inspect its required inputs, discover missing information, and ask only for what remains unavailable.

For latest/current analysis, use today as the information cutoff when no cutoff is supplied by the user, UI, or saved context. State that assumption.

## Implementation changes

- Replace the separate assessment/research instruction variants with one concise shared prompt. Remove named scenarios, canned clarification templates, and prescribed tool sequences.
- Describe each tool’s purpose, inputs, outputs, and limitations in its docstring. Make clear that assessment and prediction tools already retrieve their financial inputs; a separate `get_financials` call is optional.
- Add a read-only `list_financial_periods()` tool for the selected borrower. Reuse `FinancialRepository.get_period_history(as_of=None)` and return a typed envelope containing borrower ID, reporting periods, and known availability dates. Preserve unknown availability as null.
- Register discovery alongside borrower-bound financial tools. Include its result type in tool traces; introduce no database changes.
- Supply registered capabilities, selected scope, selected dates, saved context, and `current_date` as turn context. Calculate today using Europe/Lisbon for this workspace.
- Let the agent resolve “latest” from discovered periods within the applicable cutoff. Explicit or contextual cutoffs take precedence over today; disclose unknown source availability.
- Allow an assessment-only agent without a selected borrower to explain or request selection. Keep borrower-bound tools unavailable until the application supplies that selection.
- Preserve input validation, execution budgets, structured answers, and rendering. Add no Python intent rules, evidence checks, or routing agent.

## Validation

- Check that financial discovery returns ordered periods and availability metadata without calculations, writes, or benchmark labels.
- Verify document research proceeds without borrower or calculation dates.
- Verify a calculation without borrower scope requests selection and does not substitute an issuer from the document catalog.
- Verify latest/current analysis discovers the period, uses today when appropriate, states the assumption, and respects explicit cutoffs.
- Verify explanations and waiver questions use relevant context or request source material without imposing calculation prerequisites.
- Test empty financial history, unknown availability, supplied dates, saved assessments, and follow-up topic changes.
- Update active evaluations to accept valid tool choices and optional discovery/read calls rather than exact sequences. Revise expectations affected by the new “today” default; preserve historical captures.
- Run relevant offline suites and a small live smoke including paraphrases beyond the reported examples.

## Defaults

- Borrower selection remains application-owned; this change does not introduce scope switching through chat.
- Today is a default for latest/current analysis, not a universal default for historical or ambiguous requests.
- Financial calculation and verification services remain unchanged.
- Update notebook examples and restart guidance. Introduce no new framework or production-hardening work.
