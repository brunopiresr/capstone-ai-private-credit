# Logfire structure improvement plan

Implemented on 2026-11-13. This document records the agreed scope and acceptance criteria.

Keep one shared identifier for each web session, and give each independent interaction or workflow its own trace. Reuse the existing operation spans and Logfire instrumentation.

| Identifier | Purpose |
| --- | --- |
| `session.id` | Shared across all exported application logs and spans attributable to the same web session |
| `gen_ai.conversation.id` | Existing agent conversation identity |
| `trace_id` | One interaction or independent workflow |

1. Remove the shared session root.

   In `observability/session.py`, remove creation of `agent.session` and reattachment of its saved trace carrier. Keep session identity, scoped baggage, and context cleanup. Migrate existing carrier references and tests without unnecessarily changing the public conversation API.

   Keep existing `agent.turn`, `credit.assessment`, `credit.review`, document-processing, and native agent/model/tool spans. With no session anchor, independent calls naturally start separate traces. Nested service calls stay in their initiating operation's trace; a review's assessment and review agents remain together. Do not introduce a generic tracing framework.

2. Share one web-session UUID.

   Add one small web helper that creates a UUID in `st.session_state` and binds it as `session.id` through Logfire baggage. Retain it across reruns, navigation, borrower changes, and chat clears. A new Streamlit session gets a new UUID. Keep it out of cached services and process-global state.

   Wire V2 first, then reuse the helper in the other web entrypoints. Cover callbacks and independently rerun fragments as well as the main page. Binding the identifier creates no parent span. Existing conversation IDs, history behavior, and cost APIs continue to work.

   The installed Logfire scrubber can redact keys containing `session`. Preserve only the exact `session.id` attribute with a validated UUID through a narrow scrub callback. Keep ordinary scrubbing enabled. Verify the identifier survives in actual exported Python logging records, direct Logfire logs, and native/model/tool spans.

3. Verify the structure and document the filter.

   Use an in-memory exporter with export disabled to check:

   - Two questions in one web session produce different trace IDs and the same `session.id`.
   - A separate assessment shares that web-session ID but has its own trace; nested work keeps its correct parents.
   - Reruns and callbacks retain the ID; two browser sessions remain isolated, including worker-thread execution.
   - Logs and spans carry the exported ID, and context is restored after errors or cancellation.

   Update existing tests that require one session anchor or one trace for all turns. Repair the outdated synthetic answer in `scripts/validate_logfire.py` while updating its hierarchy assertions. Run the affected observability, conversation, web, and telemetry checks.

   Add this Logfire query to the setup guide, using the relevant service, environment, and time range:

   ```sql
   SELECT start_timestamp, kind, span_name, trace_id, span_id, attributes
   FROM records
   WHERE attributes->>'session.id' = '<web-session-uuid>'
   ORDER BY start_timestamp;
   ```

The change is complete when filtering one web-session UUID retrieves its application logs and spans across several independent traces, and each trace retains the existing nested execution detail.

New context classes, session-cost APIs, dashboards, changes to chat memory, and persistent browser identity are outside this change.

Reference: [Logfire baggage](https://pydantic.dev/docs/logfire/reference/baggage/) supports propagating shared attributes; [OpenTelemetry sessions](https://opentelemetry.io/docs/specs/semconv/general/session/) defines `session.id` for session correlation (currently Development status).
