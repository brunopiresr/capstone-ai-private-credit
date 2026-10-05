# Evaluation

Offline extraction gold comparisons and controlled regression tests are available under
`tests/evaluation/extraction/`. They compare stored observations and do not call a model.

Three offline LLM judges now evaluate extraction, retrieval, and answer snapshots using
Evidently. See [LLM judges](llm_judges.md) for their rubrics, data contracts, isolated
environment, capture adapters, run commands, report artifacts, and limitations.
Deterministic calculation and structured verification checks remain separate.
