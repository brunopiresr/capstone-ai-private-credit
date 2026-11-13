# Prompt resources

| Module | Purpose |
| --- | --- |
| `extraction.py` | Versioned extraction instructions; current version v2.3 |
| `batch.py` | All-company grouping instructions, v2.1 |
| `narrative.py` | Source-stated monitoring notes |
| `assembly.py` | Shared JSON evidence envelopes |
| `credit_assessment.py` | Shared task reasoning, contextual defaults, structured output and citations |
| `credit_review.py` | Bullish, bearish, and recommendation roles with cited arguments |

Tool docstrings define tool/argument guidance. Assessment results carry model and
availability caveats in `issues`. Extraction prompt changes require a deliberate
version update and matching fixtures. See [document processing](../../../../docs/guides/document-processing.md).
