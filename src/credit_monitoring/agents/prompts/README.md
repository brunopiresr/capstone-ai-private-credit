# Prompt resources

- `extraction.py`: exact agreed `EXTRACTION_INSTRUCTIONS` and its version.
- `batch.py`: separate grouping directive for one-call all-company extraction.
- `narrative.py`: source-stated monitoring notes without covenant calculations.
- `assembly.py`: JSON envelopes shared by both workflows.
- `credit_assessment.py`: the analyst agent's tool selection, evidence, and answer rules.

The extraction prompt changes only through a separately reviewed version update.
The extraction/batch prompts are versioned `v2.1`; full-document extraction must
include every fiscal-quarter schedule row and preserve exact ratio wording.
See [current service and agent usage](../../../../docs/document_processing.md).
