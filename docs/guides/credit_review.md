# Credit reviews

Bullish and bearish agents independently interpret one borrower's saved assessment.
A recommendation agent receives both full analyses and the original evidence, then
explains its advisory action. The analyst makes the decision.

In the app, use **Borrower analysis → Run agent review** or enable **Include agent
reviews** in Portfolio. See the [walkthrough](ui_preview.md).

## Review an existing assessment

With a completed `RiskAssessment` and provider credentials configured:

```python
from credit_monitoring.application.bootstrap import create_credit_review_service
from credit_monitoring.domain.credit_review import ExposureDecisionContext

reviews = create_credit_review_service()
decision = ExposureDecisionContext(
    question="Should the existing exposure be maintained?",
    credit_criteria=("Review compliance, comparable headroom trends, and data gaps.",),
    constraints=("No numerical exposure sizing.",),
)
result = await reviews.review_assessment_async(assessment, decision_context=decision)
print(result.model_dump_json(indent=2))
```

Use `review_assessment(...)` in synchronous code. In notebooks or an active event loop,
use `await`. To assess and review in one call, provide an `assessment_service` to the
factory and call `review(...)` or `review_async(...)` with borrower, period, and cutoff.
This creates one assessment before reviewing it.

Construction makes no model requests. Execution needs provider credentials; the default
model is `openai-responses:gpt-4o-mini`. Factory `model` and per-role model overrides
configure service calls; the app also reads `LLM_MODEL`.

## Results and boundaries

Each perspective retains arguments, evidence IDs, rationales, assumptions, counterevidence,
gaps, and confidence. Synthesis judges every supplied argument and explains its action:

| Action | Meaning |
| --- | --- |
| `maintain` | Retain current exposure |
| `increase` / `reduce` | Advise a direction without sizing |
| `review` | Request analyst reassessment |
| `defer` | Evidence, criteria, or completed reviews are insufficient |

All agents use the same frozen evidence. Generated narratives, benchmark labels, and
catalog/financial notes are excluded. Agents have no calculation tools and do not
change compliance. Confidence describes evidence support, not a risk probability.
The default news provider reports unavailable and performs no search.

| Condition | Behavior |
| --- | --- |
| Invalid verification or identity | Block agents; defer |
| Missing criteria or supported evidence | Defer; retain available analysis |
| Reviewer failure | Incomplete; defer and retain successful work |
| Recommendation failure | Incomplete; defer and retain both reviews |
| Missing news or ML | Disclose the gap and preserve deterministic evidence |

`complete` means the workflow finished; it can still recommend `defer`. Display
`result.issues`, evidence limits, both analyses, and the recommendation together.
Reference validation checks identifiers and coverage, not the truth of every sentence.

## Configuration

`create_credit_review_service(...)` accepts shared/per-role models, `CreditReviewSettings`,
an optional news provider, and an async progress callback. Defaults are 60 seconds per
role and one output-validation retry. Bullish and bearish runs are concurrent;
recommendation follows. Cancellation propagates; successful persisted assessments remain.

An injected news provider must supply explicit borrower mapping and publication provenance.
Unknown publication times and records after the cutoff are excluded; a date cutoff
includes the complete UTC day. See the [decision record](../project/decisions/001-credit-review-agents.md).

## Validation and model evaluation

```bash
uv run --locked pytest tests/integration/workflows/test_credit_review.py
```

Offline tests check scope, evidence flow, references, failures, and serialization.
For live evaluation, review improving, deteriorating, breached-with-mitigants, and
missing-input cases. Save the full result and model/prompt metadata; check argument
support, counterevidence, and whether the action follows from the supplied criteria.

To evaluate generated follow-up questions on saved app reviews:

```bash
uv run --locked python scripts/evaluate_follow_up_questions.py --live \
  --run-id YOUR_SAVED_ASSESSMENT_ID --output /tmp/follow-up-quality.json
```

This makes model requests and exports questions plus a human scoring rubric. Successful
generation alone does not establish quality. Repeat `--run-id` for varied borrowers.
