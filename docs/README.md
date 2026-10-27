# Documentation

Use the root [README](../README.md) to install and run the POC. Current instructions
are grouped below; historical plans are preserved separately.

## Project context

- [POC definition](project/poc_definition.md): business scope and limits.
- [Architecture](project/architecture.md): implemented flows and remaining capabilities.
- [Data sources](project/data_sources.md) and [data layout](../data/README.md): source provenance and file ownership.
- [Credit review decisions](project/decisions/001-credit-review-agents.md) and [Logfire decisions](project/decisions/logfire_implementation_decisions.md).
- [Borrower comparison proposal](project/borrower_comparison_implementation_plan.md): unimplemented feature proposal.
- [Deferred simplification plan](project/deferred-simplification-plan.md): larger changes identified in the cleanup review.

## Usage guides

- [Document processing and agents](guides/document_processing.md).
- [Quarterly assessment and optional ML](guides/ml_early_warning.md).
- [Bullish, bearish, and recommendation reviews](guides/credit_review.md).
- [Optional Logfire setup and validation](guides/logfire_setup.md).

## Homework and evaluation

[Homework navigation](../homework/README.md) separates exercises from shared app code.
[Evaluation](homework/evaluation.md) explains offline, live, and public-source checks;
[LLM judges](homework/llm_judges.md) covers the optional separate environment.

## Reviews and historical records

- [Current POC complexity review](reviews/poc_simplification_review.md).
- [Previous cleanup review](reviews/capstone_cleanup_review.md) and [its F05–F12 results](reviews/capstone_cleanup_f05_f12_implementation_results.md): historical findings, with original evidence preserved.
- [Public SEC benchmark triage](reviews/public_sec_benchmark_triage.md): measured extraction limitations; a green offline suite does not close these findings.
- [Archive](archive/): original implementation plans, extraction references, and the early POC specification. Their literal paths, commands, and APIs reflect the period in which they were written.
