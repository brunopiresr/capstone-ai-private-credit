# Streamlit POC: portfolio and workflow preview

Run `make preview`, then open the Streamlit URL printed in the terminal. If another
app already uses the default port, run:

```bash
uv run --locked streamlit run src/credit_monitoring/web/preview.py --server.port 8502
```

**Portfolio** is connected to the existing calculation and credit review services.
The other pages remain a disconnected UX prototype. Their sample results, flags,
chat and reports are independent of the connected portfolio. The original
single-borrower app remains available through `make run`.

## Connected portfolio

1. Choose a reporting period and information cutoff. **Latest available per borrower**
   uses each borrower's latest source period at or before the cutoff. The bundled
   financials cover 2025; the table shows each actual period, including mixed periods.
2. Choose a borrower and **Run selected assessment**, or **Assess all borrowers**.
   The all-borrower action includes every registered borrower regardless of search
   filters. Missing period inputs stay missing; another quarter is never substituted.
   Enable **Include agent reviews** before requesting the assessment to run the
   bullish, bearish and recommendation agents for each new assessment. It is off
   by default and requires `OPENAI_API_KEY`. Expand **Agent review settings** to
   provide the question, criteria and constraints shared by the requested borrowers.
3. Search/filter the table or click a cell to inspect saved calculations, source
   references, headroom, trends and verification. Reading the page does not run work.
4. In **Agent analysis**, supply a question, criteria and any decision constraints,
   then **Run agent review**. Set `OPENAI_API_KEY` in the environment or root `.env`;
   `LLM_MODEL` overrides the existing default model. This explicitly invokes the real
   bullish, bearish and recommendation agents and incurs provider usage.
5. Review the main arguments, synthesis, full rationales and evidence limitations.
   Reviews use the exact saved assessment without recalculation. A new assessment
   requires a new review; earlier records remain stored.

The input data is synthetic; calculations are real service outputs. Forecasting is
off in this first connected step. News remains explicitly unavailable through the
current provider. Source availability warnings and incomplete/waived/inactive states
are preserved. A failed calculation skips its review. A failed review preserves its
assessment and does not stop the remaining borrowers. The run outcomes show assessment
and agent-review results separately; saved reviews stay linked to their exact run.

Working financial inputs, analytics and complete assessment/review snapshots are
stored under ignored `data/runtime/portfolio/`. The seed database is copied only if
the working database does not exist. Reloading the browser or restarting the app
retains saved results. No document downloads or extraction are triggered by this page.

## Remaining preview screens

1. Open **Borrower analysis** in the sidebar and choose a borrower such as
   **Northstar Packaging**. This page still uses illustrative 2026 data for UX testing;
   it does not display the connected portfolio's saved runs.
2. Inspect Overview, Calculations and Credit analysis. The snapshot lists the main
   bullish, bearish and recommendation arguments in separate sample cards. Try the
   assistant on the right, including Expand and Hide; replies remain scripted.
3. In **Analyst handoff**, record validation checks, add a flag and observations,
   then Send to risk manager. Recalculate creates a sample version with unchanged
   figures that needs fresh validation.
4. In **Documents & data**, register an example HTTP/HTTPS URL, select it, Fetch and
   Process. Try rebuild controls and inspect operation history. These operations
   remain simulations; no real files or databases are changed.
5. Open **Risk review**. Use the top borrower selector or click any cell in the flagged
   queue to update the analysis below. Inspect the sample arguments and handoff, add
   a comment/recommendation, or request more analysis with a question and context.
6. Return to **Borrower analysis**, create a sample review with that context, and
   submit a response in Analyst handoff. Complete the review in **Risk review**.
7. In **Board report**, edit the summary and recommendations, then finalize. The
   report covers active sample flags and untriaged sample breaches. Its snapshot
   belongs to this preview session and is independent of the connected portfolio.

Sample changes survive navigation in the same browser session. Reloading or
**Reset sample screens** clears them while retaining saved portfolio results.
Different browser sessions share saved portfolio runs, but not sample-screen edits.

## Feedback to collect

- Can an analyst find a borrower and inspect the reasons for its current status?
- Are real results, missing inputs and saved review versions clear in Portfolio?
- Do the sample validation and submission controls communicate the intended handoff?
- Does the chat leave enough room for analysis, and can the manager find a response?
- Does the board report contain the explanation, risk analysis and recommendation needed?
