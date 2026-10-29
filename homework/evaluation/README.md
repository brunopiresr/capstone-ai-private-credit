# Human evaluation app

From the repository root:

```bash
uv run --locked streamlit run homework/evaluation/app.py
```

The app uses the project's Python environment and Streamlit. Set `OPENAI_API_KEY` in
the repository `.env`; `LLM_MODEL` optionally overrides the shared model default,
`openai-responses:gpt-4o-mini`.

Click **Start evaluation** to preview the first question. Click **Run question** to generate
an answer, then choose a response category, optionally enter a comment, and click
**Submit and next**. The next question is shown without calling the model; every answer
requires an explicit run. **Skip** moves to the next question without submitting feedback
or generating an answer. It also works after an answer or error, discarding unsent feedback.
Skipped questions appear as **Skipped** in the summary and are excluded from the evaluated
count. The app presents all 27 questions from
`2026-10-26/cases.jsonl` in their existing order, including development and holdout cases.
Each question gets a fresh agent with the evaluation's scoped tools and prepared inputs.
Reference answers and prior labels are not sent to the agent or displayed to the reviewer.

Response categories are **Correct**, **Incorrect**, **Incomplete**, **Unsupported claims**,
**Irrelevant**, **Unclear**, and **Unable to evaluate**. Choose one category before submitting;
there is no default selection. These describe response quality; the dataset's question
categories remain separate.

The orange **Cancel / restart** button sits beside **Submit and next** at the bottom.
It opens a summary table with **Question ID**, **Rate**, and **Comments**. Submitted
evaluations are listed in question order; the
current answer's unsent classification and comment are shown as not submitted. Choose
**Continue evaluating** to return to the same answer, or **Proceed to restart** to clear
progress and preview question 1. Classifying or skipping the final question opens this
summary and waits for **Proceed to restart** before beginning a new round.
Each round has a separate ID, and answers are retained across Streamlit rerenders. Incomplete or
failed responses offer **Retry answer** or **Skip**. Question previews and skipping remain
available without an API key; **Run question** requires one. Restart is available between
requests. Closing or refreshing the browser can
lose in-memory progress; local submissions remain saved.

Each generated answer, public tool events and submitted feedback are saved under the
ignored `2026-10-26/runs/human-<round-id>/<case-id>/<attempt-id>/` directory. The
`feedback.json` file contains the case ID, round/chat ID, interaction ID, model, category,
comment, timestamp and the SHA-256 of `answer.json`. Restarting keeps these submitted
records; unsent feedback is discarded. Historical baseline results are preserved.
Skipped questions are saved separately as `<case-id>/skip.json` and emit
`evaluation.question_skipped` in Logfire; they do not create a `user.feedback` event.

The app initializes the existing Logfire configuration from `.env` and correlates model
activity and feedback using `chat_id`, `case_id` and `interaction_id`. Filter Logfire on
`event_name = 'user.feedback'`; lifecycle events use `evaluation.round_started`,
`evaluation.question_started`, `evaluation.answer_presented` and `evaluation.round_ended`.
Request spans are named, for example, `evaluation.request E01 · search`; feedback appears
directly beneath its own request as `user.feedback E01 · Correct`. Feedback reattaches
the completed request's trace context when submitted on a later rerender. Request duration
measures generation time; feedback can arrive after the request span ends. Filter across
requests with `event_name = 'evaluation.request'`, or use `case_id = 'E01'` to find a case.
This hierarchy applies to answers generated after this update; earlier request names and
feedback records remain unchanged. An answer already open during reload keeps its content
and can still be evaluated, using the round as parent if its request context was not retained.
New submissions record `category` using an ID such as `correct` or `unsupported_claims`.
Earlier binary feedback remains saved with its original `rating` field.
Question and comment text follow `LOGFIRE_CAPTURE_CONTENT`; set it to `true` to retain
comments in Logfire. Native model content capture follows the same setting. Local feedback
always includes the submitted comment. Logfire export uses the existing token/settings;
without credentials, the app continues to save locally.

Both previously missing full SEC exhibits were prepared on 2026-10-29, so all 27
questions pass source preflight. SEC downloading is a preparation step; ordinary app
rounds use the prepared files. See the [dated exercise](2026-10-26/README.md) for the
CLI runner, reference data and remaining data limitations.

Offline checks:

```bash
uv run --locked pytest homework/evaluation/tests homework/evaluation/2026-10-26/test_workbench.py
```
