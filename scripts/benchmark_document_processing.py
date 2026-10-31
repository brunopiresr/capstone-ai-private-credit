"""Measure document threading with real extraction/storage and simulated model I/O."""

import argparse
import asyncio
import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from time import perf_counter

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from credit_monitoring.application.bootstrap import create_document_service
from credit_monitoring.domain import CovenantExtraction
from credit_monitoring.ingestion.converters.sec_markdown import CONVERSION_VERSION


def benchmark(documents: int = 8, delay: float = 0.15) -> dict:
    if documents < 1 or delay < 0:
        raise ValueError("Use a positive document count and a nonnegative delay.")
    results = []
    with TemporaryDirectory(prefix="document-benchmark-") as temporary:
        for workers in (1, 2, 4):
            root = Path(temporary) / str(workers)
            markdown = root / "markdown"
            markdown.mkdir(parents=True)
            records = [
                {
                    "document_id": f"DOC{i}",
                    "company": "Benchmark issuer",
                    "ticker": "TEST",
                    "document_type": "10-Q",
                    "source_url": f"https://example.invalid/{i}.html",
                }
                for i in range(documents)
            ]
            source = root / "catalog.csv"
            with source.open("w", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=list(records[0]))
                writer.writeheader()
                writer.writerows(records)
            for record in records:
                did = record["document_id"]
                (markdown / f"{did}.md").write_text("Maximum leverage ratio is 4.0x.")
                (markdown / f".{did}.conversion-version").write_text(CONVERSION_VERSION)
            calls = 0
            guard = Lock()

            async def respond(messages, info):
                nonlocal calls
                with guard:
                    calls += 1
                await asyncio.sleep(delay)
                return ModelResponse(
                    [ToolCallPart("final_result", CovenantExtraction().model_dump())],
                    finish_reason="stop",
                )

            def model_factory():
                return FunctionModel(function=respond, model_name="document-benchmark")

            service = create_document_service(
                source_file=source,
                html_dir=root / "html",
                markdown_dir=markdown,
                database_path=root / "extractions.sqlite3",
                model=model_factory(),
                model_factory=model_factory,
            )
            started = perf_counter()
            outcomes = service.process_all_documents(max_workers=workers)
            elapsed = perf_counter() - started
            if any(outcome.status != "complete" for outcome in outcomes) or calls != documents:
                raise RuntimeError("Benchmark did not complete exactly one model call per document")
            results.append(
                {
                    "workers": workers,
                    "documents": documents,
                    "model_calls": calls,
                    "elapsed_seconds": round(elapsed, 6),
                }
            )
    for result in results:
        result["speedup"] = round(results[0]["elapsed_seconds"] / result["elapsed_seconds"], 3)
    return {
        "workload": "Uncached extraction; local Markdown; simulated model I/O",
        "delay_seconds": delay,
        "live_provider_tested": False,
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=int, default=8)
    parser.add_argument("--delay", type=float, default=0.15)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = json.dumps(benchmark(arguments.documents, arguments.delay), indent=2) + "\n"
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(report)
    print(report, end="")


if __name__ == "__main__":
    main()
