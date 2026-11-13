# POC documentation

Start with the [project README](../README.md). The documented application is **Web V2**.

## Understand the problem

- [POC overview](poc-overview.md): users, terminology, scope, data, and the wider vision.
- [Worked example](worked-example.md): follow one fictional borrower from calculation to review.
- [Architecture](architecture.md): services, evidence flow, storage, and design choices.

## Reproduce the demonstration

- [Setup](guides/setup.md): notebooks, Web V2, Docker, and optional services.
- [Web V2 workflow](guides/web-v2-workflow.md): analyst work, manager review, and board reports.
- [Screenshots and capture details](assets/README.md): inspect the demonstration without API calls.

## Inspect how it works

- [Document processing](guides/document-processing.md): HTML extraction, local search, and reuse.
- [Covenant assessment and ML](guides/covenant-assessment.md): formulas, interpretation, and synthetic forecasts.
- [Agents and credit reviews](guides/agents.md): responsibilities, orchestration, and Python examples.
- [Agent tools](reference/agent-tools.md): arguments, results, scope, and saved-data effects.
- [Data layout](../data/README.md): runtime inputs, evaluation evidence, and training assets.
- [Prompts](../src/credit_monitoring/agents/prompts/README.md): generation instructions and their owners.

## Assess the evidence

- [Evaluation](evaluation/README.md): what each check measures and how to repeat it.
- [Results](evaluation/results.md): dated measurements, known failures, and saved answers.
- [LLM judges](evaluation/llm-judges.md): snapshot capture, scoring, and judge limitations.
- [Monitoring](guides/monitoring.md): trace inspection and V2 answer feedback.

Past implementation records and future proposals live in [v2-plan](../v2-plan/README.md).
They are not instructions for running the current POC.
