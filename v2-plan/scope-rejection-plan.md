# Plan: explicit document scope rejection

Date: 2026-11-12
Status: proposed; implementation requires user approval.

## Problem and intended behavior

A document-agent call configured with `ticker="FMC"` rejects requests for HAIN,
including requests using a HAIN document ID directly. That boundary works, but
the failure is currently classified as `invalid_arguments`. The agent can keep
attempting the blocked issuer, spending tool rounds needed for permitted work.

The intended behavior is to preserve application-owned issuer scope, report a
clear policy rejection, continue permitted FMC research, and explain what is
needed for a separate authorized comparison. Authorization written in a question
must not reconfigure the tools.

This plan authorizes no implementation changes. Only this planning document is
being added; application code, tests, and notebooks remain unchanged by this task.

## Existing behavior

- `src/credit_monitoring/agents/tools/documents.py`: `_resolve_ticker` checks
  explicit issuer requests; `_check_document_scope` checks document ownership
  before extraction or processing. `_reject_scope` raises `InvalidToolArguments`.
- `src/credit_monitoring/agents/tools/common.py`: `service_errors` converts that
  exception to `ToolFailure(code="invalid_arguments", ...)` and logs a warning.
- `src/credit_monitoring/domain/tool_results.py`: `ToolFailure` already supports
  `policy_rejection` and defaults `terminal` to `False`.
- `src/credit_monitoring/agents/events.py`: the console callback displays the
  failure code but does not display its explanation.
- `src/credit_monitoring/agents/streaming.py`: failures are recorded as tool
  outcomes and returned to the model. The inspected execution path does not use
  `terminal` to enforce stopping or retry suppression.
- Notebook section 11.3 in `homework/notebooks/03-agents.ipynb` deliberately tests
  this boundary and allows rejected attempts to remain visible in the trace.

## Proposed implementation

### 1. Represent scope violations explicitly

Add a dedicated `ScopeRejected` exception in `agents/tools/common.py`, alongside
the existing argument-validation exception. Use it only for configured issuer
scope violations; malformed inputs must retain their existing classification.

Change `DocumentTools._reject_scope` to raise that exception. Include the
configured issuer and actionable recovery instructions, without revealing
out-of-scope document content. Both ticker checks and direct document-ID checks
must use this same path.

Preserve existing validation and operation ordering. A catalog metadata lookup
needed to check document ownership remains permitted; rejected requests must not
reach evidence search, extraction reads, or document processing for the other
issuer.

### 2. Convert the exception to a recoverable policy result

Catch `ScopeRejected` separately in `service_errors`, before generic error
conversion. Return the existing `ToolFailure` representation:

```python
ToolFailure(
    code="policy_rejection",
    message=(
        "This run is restricted to FMC. Chat instructions cannot change issuer "
        "scope. Continue with FMC; HAIN requires a separate application-scoped call."
    ),
    terminal=False,
)
```

The actual message must use the configured scope rather than hard-coded issuer
names. For a rejected document ID, the message can identify the permitted scope
without disclosing the document's issuer.

Keep the rejection observable as an expected policy event, with a clear log
message and structured tool/error metadata. Preserve existing behavior for
`invalid_arguments` and `service_error`.

Reuse `policy_rejection` for the initial implementation. Adding a separate
`scope_rejection` result code would require changing the domain schema and its
consumers and is outside the proposed minimal scope.

### 3. Explain the boundary and recovery to the model

Update `src/credit_monitoring/agents/prompts/credit_assessment.py` and advance its
prompt version. Instructions should make these rules explicit:

- The application-selected issuer is fixed for the run or scoped conversation.
- Chat authorization cannot change that issuer, including through a direct
  document ID or a different document tool.
- A scope rejection is not a transient service error. Do not retry the blocked
  issuer through another tool or identifier.
- Continue the permitted portions of the request, retaining citations and
  reporting the blocked portion as a specific gap.
- Explain the new application scope or separate scoped calls needed for the
  remaining document research.
- A relief schedule alone does not establish actual headroom. A financial
  comparison also needs an authorized calculation workflow, applicable covenant
  definitions and thresholds, comparable reporting periods, an information
  cutoff, and the financial inputs required by those definitions.

Keep these instructions general rather than specific to the notebook wording.

### 4. Preserve event and answer behavior

The existing callback will display `error: policy_rejection` automatically.
Retain the full explanation in the structured result and tool trace.

Do not terminate the entire turn on a scope rejection: an FMC-only answer may
still satisfy part of the request. Do not interpret `terminal=False` as a retry
control; it is descriptive in the current execution path.

Displaying the rejection explanation in console output is an optional follow-up.
If included in an approved implementation, show only the controlled policy
message and add focused callback coverage.

## Validation

Update affected scope assertions in
`tests/unit/covenants/test_credit_assessment_agent.py` and add focused coverage
in the existing tool-input or agent test modules:

1. With FMC configured, `list_documents(ticker="HAIN")` and
   `search_evidence(..., ticker="HAIN")` return `policy_rejection`; the underlying
   listing or search operation is not called.
2. HAIN document IDs passed to `get_document_extraction` and `process_document`
   return the same rejection. Only ownership metadata may be consulted; the
   extraction or processing operation is not called.
3. Requests for FMC and requests using `ticker=None` retain their scoped behavior.
   Unscoped calls retain their existing behavior.
4. Malformed arguments remain `invalid_arguments`, and expected service failures
   remain `service_error`.
5. A scripted agent exchange rejects HAIN, then completes permitted FMC research
   with its citations and an explicit comparison gap. The rejection remains in
   the trace and contributes no protected evidence.
6. A conversation follow-up cannot change its configured issuer. Update its
   existing regression assertion to expect `policy_rejection`.

Run the focused document-agent, tool-input, and context tests, followed by lint
for the changed Python files. Broaden checks only if failures or affected
consumers justify it.

A scripted model verifies plumbing and continuation, not whether a live model
obeys recovery instructions. After implementation approval, separately authorize
any live model run before incurring API usage. Use notebook section 11.3 as the
manual scenario: inspect the trace, cited FMC result, blocked HAIN comparison,
and missing financial inputs.

## Acceptance criteria

- Both issuer-argument and direct-document scope violations are visibly
  classified as `policy_rejection`.
- No rejected request retrieves or processes protected issuer content.
- Feedback explains the fixed scope and how to proceed through a separately
  configured call.
- Permitted work can complete after rejection, with its evidence intact.
- Argument-validation and service-error behavior remain unchanged.
- The plan and implementation report distinguish tested runtime guarantees from
  model behavior influenced by instructions.

## Optional stronger retry controls

A new failure code and recovery instructions do not guarantee that the model
stops issuing blocked calls. Existing checks guarantee denial of protected
operations, not elimination of repeated attempts.

If strict retry suppression is required, approve a separate design for per-run
tracking and tool preparation or dispatch controls. It must address both ticker
arguments and direct document IDs, retain allowed issuer operations, keep
rejections visible, and define how repeated attempts affect the remaining tool
budget. Do not add a generic retry framework or stop the whole run as part of
the minimal change.

## Approval boundary

Before implementation, obtain approval for the minimal change above. Optional
console explanations and strict retry controls should be explicitly included or
deferred. Do not modify existing user work, broaden issuer scope automatically,
or remove the scope checks.
