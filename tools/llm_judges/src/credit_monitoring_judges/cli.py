"""Evaluate existing snapshots using Evidently; no generation or cloud upload."""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from credit_monitoring_judges.models import load_cases


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Must be greater than zero.")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Captured judge cases in JSONL.")
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/judges"))
    parser.add_argument("--judge", choices=["extraction", "retrieval", "answer"])
    parser.add_argument(
        "--model", default=None, help="Defaults to EVIDENTLY_JUDGE_MODEL/gpt-4o-mini."
    )
    parser.add_argument("--limit", type=positive_int)
    parser.add_argument("--max-input-chars", type=positive_int, default=100_000)
    parser.add_argument(
        "--env-file", type=Path, help="Explicit dotenv file; shell values take priority."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate/select inputs without LLM calls."
    )
    parser.add_argument(
        "--fail-on-quality",
        action="store_true",
        help="Exit 1 if any case fails, abstains or is skipped; evaluation errors exit 2.",
    )
    args = parser.parse_args(argv)
    if args.env_file:
        load_dotenv(args.env_file, override=False)
    model = args.model or os.environ.get("EVIDENTLY_JUDGE_MODEL") or "gpt-4o-mini"
    try:
        cases = load_cases(args.input)
        if args.judge:
            cases = [case for case in cases if case.judge == args.judge]
        if args.limit:
            cases = cases[: args.limit]
        if not cases:
            raise ValueError("No cases match the selected judge.")
        # Prevent an output artifact from overwriting its own input snapshots.
        artifact_names = (
            "inputs.jsonl",
            "results.jsonl",
            "summary.json",
            "manifest.json",
            "report.html",
            "report.json",
        )
        if args.input.resolve() in {(args.output_dir / name).resolve() for name in artifact_names}:
            raise ValueError("Input file must be outside the output artifact paths.")
    except (OSError, ValueError) as error:
        print(f"Invalid evaluation inputs: {error}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "model": model,
                    "selected_cases": len(cases),
                    "judges": sorted({case.judge for case in cases}),
                },
                indent=2,
            )
        )
        return 0
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        print("Set OPENAI_API_KEY or supply --env-file before running LLM judges.", file=sys.stderr)
        return 2
    from credit_monitoring_judges.evaluator import evaluate_case, summarize, write_artifacts

    results = []
    for index, case in enumerate(cases, 1):
        result = evaluate_case(case, model=model, max_input_chars=args.max_input_chars)
        results.append(result)
        print(
            f"[{index}/{len(cases)}] {case.case_id}/{case.judge}: {result.label or result.status}"
        )
    try:
        write_artifacts(
            args.output_dir,
            cases,
            results,
            model=model,
            input_path=args.input,
            max_input_chars=args.max_input_chars,
        )
    except Exception as error:
        print(f"Could not finish report artifacts ({type(error).__name__}).", file=sys.stderr)
        return 2
    print(json.dumps(summarize(results), indent=2))
    print(f"Artifacts: {args.output_dir.resolve()}")
    if any(result.status == "error" for result in results):
        return 2
    if args.fail_on_quality and any(result.label != "pass" for result in results):
        return 1
    return 0
