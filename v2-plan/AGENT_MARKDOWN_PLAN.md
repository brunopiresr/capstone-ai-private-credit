# Plan: render agent messages as Markdown

## Review verdict — 2026-11-12

The original approach is still valid, but needs the additions below. Keep structured
model output and assemble the display message in the Python backend. Clients should
render the supplied `answer` string using their normal Markdown component, without
parsing model JSON, detecting sections, unescaping text, or rebuilding tables.
Normal Markdown rendering is still required; this plan does not return HTML.

Scope: `CreditAssessmentAgent` chat answers in Notebook 03 and the web assistants.
Credit-review reports and generated follow-up suggestions have separate schemas and
presentation paths; changing those is separate work.

Implementation scope agreed after review: preserve narrative Markdown and keep
confidence presentation and schema versions unchanged. This is the smaller formatting
change discussed with the user. The steps below reflect that implemented scope.
The rationale for retaining the backend formatter is recorded in
[Decision 002](../docs/project/decisions/002-agent-markdown-rendering.md).

## Review baseline before implementation

- `domain/agent.py`: `AnswerDraft.summary` explicitly says “without Markdown”, and
  `AnswerFinding.text` requires plain text. The original plan attributed that exact
  prohibition to the prompt; it actually lives in the schema description.
- `agents/prompts/credit_assessment.py`: the current prompt is
  `credit-assessment-agent-v20-loaded-filing-tables`. It asks for plain structured
  data and says the application handles headings and Markdown escaping.
- `agents/answer_contract.py`: `render_content()` escapes all narrative text with
  `markdown_literal()`, but adds Markdown headings, lists, tables and source labels
  itself. This explains why some parts already render as Markdown and others do not.
- `agents/run_state.py`: previews and final answers already share `render_content()`.
  Both first materialize selected source tables from loaded filing extractions.
- `web/assessment.py`: `render_answer()` already calls `st.markdown(answer.answer)`.
  The original web app, borrower assistant, V2 and V3 reuse that function.
- Notebook 03 already uses `Markdown(outcome.answer)` and renders streaming
  `event.output.answer` snapshots. The web chat paths inspected consume completed
  answers; this change does not require adding web streaming.
- Confidence is currently outside `answer`: Streamlit builds a caption from its
  fields, while the notebook prints the level and separately renders the explanation.
  This presentation remains unchanged under the agreed implementation scope.

## 1. Define the display contract

Keep `AnswerContent.answer` / `AgentAnswer.answer` as the backend-assembled Markdown
message body. Structured fields remain available for programmatic use and diagnostics.
Confidence, completion/error indicators and optional source/tool expanders keep their
existing presentation.

Retain `agent-answer-v3` and continue accepting historical v2, v3 and unversioned
answers without changing their stored strings. Do not unescape old messages or add
client-side version branches. The JSON shape is unchanged.

## 2. Align instructions and schema descriptions

Update `agents/prompts/credit_assessment.py` and increment the prompt version. Allow
Markdown in narrative fields: concise summary, finding text, gaps and diligence questions.
Confidence explanations remain plain text. Explain that the application assembles sections
and source labels, while the model can use emphasis, paragraphs, lists, links and fenced
code inside narratives. Plain paragraphs are valid Markdown and need no decorative formatting.

Update the corresponding descriptions in `domain/agent.py`, especially the explicit
“without Markdown” restriction. Keep document IDs, exact citation text, table titles,
column names and table cells literal. Keep tables and citations in their structured
fields, rather than duplicating them in narrative Markdown.

Preserve the current `SourceTableDraft` / `source_tables` instructions: complete filing
schedules and reported-value tables are copied from loaded extractions by the backend.
Do not ask the model to retype those tables or replace the structured output with a
free-form response.

## 3. Render Markdown in the backend

In `agents/answer_contract.py`, give narrative fields a Markdown-preserving rendering
path instead of passing them through `markdown_literal()`. Retain literal escaping for
table data, titles, IDs and citations, including pipes, line breaks and currency values.
Do not remove `markdown_literal()` globally.

Handle these boundaries explicitly:

- Separate narrative blocks and appended source lines with blank lines so a finding's
  list or code block does not absorb its citation. Citations remain literal and exact.
- Indent multiline gaps and questions by the actual enclosing list-marker width,
  including question 10 and above; preserve nested lists, paragraphs and fenced blocks.
- Keep raw HTML non-executable in notebook and web output. Do not enable
  `unsafe_allow_html` for model messages. Verify HTML handling also preserves code
  examples, comparison signs and link destinations containing `&`.
- Preserve dollar amounts such as `$10 and $20` without triggering math rendering.
  Do not escape Markdown emphasis or double-escape already escaped currency/code.
- Preserve the original structured fields and the separately displayed confidence.
- Keep error/exception text literal: `AgentRunState.answer()` currently passes failure
  strings through `AnswerDraft(summary=...)`. A Markdown-enabled narrative renderer
  must not inadvertently interpret those diagnostics as model-authored Markdown.

Keep the existing shared rendering path in `agents/run_state.py` and
`agents/streaming.py`. Preview updates are full provisional snapshots, not deltas:
consumers replace the displayed body and use `run_end.answer.answer` as authoritative.
Incomplete Markdown can temporarily reflow during streaming; clients need no repair
parser. Partial source selections remain provisional until final validation.

## 4. Keep notebook and web display thin

Continue rendering `answer` directly in `web/assessment.py` and Notebook 03, keeping
the separately displayed confidence. No web-renderer changes or custom client parsers
are needed.

Update the notebook explanation to describe backend-assembled Markdown. Preserve
existing notebook outputs and unrelated edits when making source-cell changes.
Verify the shared web renderer also covers `web_v3/assistant.py` and
`web_v2/components/chat.py`; neither needs its own message parser.

## 5. Validate behavior and compatibility

Update narrative-literal expectations, particularly
`test_plain_source_markdown_stays_literal`, while retaining table/citation-literal
assertions. Check rendered output as well as serialized strings:

- Headings, emphasis, links, nested lists and fenced code in narrative fields.
- Multiline findings followed by citations, and multiline diligence items numbered 10+.
- Literal table values/citations with pipes, brackets, underscores, dollars and HTML.
- Currency, comparison signs, HTML in prose/code, and URLs with query parameters.
- Confidence stays separately displayed; old answers still display correctly.
- Partial Markdown previews, final rendering, selected source tables, and failure text.
- Historical v2, v3 and unversioned payloads load without altering stored messages.

Focused test files:

- `tests/unit/covenants/test_answer_contract.py`
- `tests/unit/covenants/test_agent_streaming.py`
- `tests/unit/covenants/test_source_tables.py`
- `tests/integration/workflows/test_streamlit_app.py`
- `tests/integration/workflows/test_streamlit_v3.py` when changing V3 wiring
- `homework/notebooks/tests/test_notebooks.py`

Inspect actual notebook and Streamlit rendering for currency and multiline blocks;
the existing MarkdownIt assertions and Streamlit element tests do not establish that
both frontend renderers handle every Markdown extension identically.

## Review validation

The existing answer-contract, agent-streaming, notebook and Streamlit-app test files
passed: **65 tests**. A local renderer probe also confirmed that `**Leverage**`, a
model-authored heading and a list are escaped, while application-generated gap headings
render as Markdown, and confidence explanations are absent from `answer`.
These checks validate the current diagnosis; they do not validate the proposed change.

## Implementation

Implemented the smaller scope above: Markdown-aware narrative rendering, aligned schema
descriptions and prompt v21, literal diagnostics, multiline list indentation, and an
updated notebook explanation. The Markdown parser already present through transitive
dependencies is now declared directly and identifies code blocks before prose escaping.
Table rendering, confidence display, schema versions and frontend rendering calls
retain their existing contracts. Focused tests cover narrative rendering, source/table
literals, partial streams, nested code, currency and historical answers.

Implementation validation: **371 tests passed** across `tests/unit/covenants`, the
Streamlit-app and Streamlit-V3 integration tests, and `homework/notebooks/tests`.
Repository Ruff checks and the changed Python files' formatting checks also pass.
