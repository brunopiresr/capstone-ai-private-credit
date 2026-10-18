"""Compare a named SEC cache or frozen observation snapshot, without changing inputs."""

import argparse
import json
import sqlite3
import subprocess
from pathlib import Path

from credit_monitoring.evaluation.sec_snapshot import (
    capture_snapshot,
    compare_snapshot,
    content_hash,
    encoded,
    read_csv,
    render_report,
)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--database", type=Path)
    source.add_argument("--snapshot", type=Path)
    parser.add_argument("--gold", type=Path, default=root / "data/public_sec_gold_cases.csv")
    parser.add_argument("--catalog", type=Path, default=root / "data/public_sec_documents.csv")
    parser.add_argument("--sources", type=Path, default=root / "data/sec_documents/markdown")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-complete-sources", action="store_true")
    args = parser.parse_args()
    try:
        inputs = {
            path.resolve()
            for path in (args.database, args.snapshot, args.gold, args.catalog)
            if path is not None
        }
        outputs = {
            args.output.resolve() / name
            for name in ("observations.json", "manifest.json", "report.json", "report.md")
        }
        if inputs & outputs:
            raise ValueError("Output files must not overwrite comparison inputs.")
        snapshot = (
            json.loads(args.snapshot.read_text())
            if args.snapshot
            else capture_snapshot(args.database, args.catalog, args.sources)
        )
        report = compare_snapshot(
            snapshot, read_csv(args.gold), strict=args.require_complete_sources
        )
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()
        manifest = {
            "manifest_version": 1,
            "repository_revision": revision,
            "snapshot_sha256": content_hash(encoded(snapshot).encode()),
            "gold_sha256": content_hash(args.gold.read_bytes()),
            "catalog_sha256": content_hash(args.catalog.read_bytes()),
            "source_directory": str(args.sources.resolve()),
            "comparison_code_sha256": {
                name: content_hash((root / name).read_bytes())
                for name in (
                    "scripts/compare_public_sec_gold.py",
                    "src/credit_monitoring/evaluation/sec_gold.py",
                    "src/credit_monitoring/evaluation/sec_snapshot.py",
                )
            },
        }
        args.output.mkdir(parents=True, exist_ok=True)
        for name, value in (("observations", snapshot), ("manifest", manifest), ("report", report)):
            (args.output / f"{name}.json").write_text(encoded(value), encoding="utf-8")
        (args.output / "report.md").write_text(render_report(report), encoding="utf-8")
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.error(str(error))
    print(
        f"{report['evaluable_case_count']}/{report['case_count']} evaluable cases; "
        f"{report['case_status_counts']}. Report: {args.output / 'report.md'}"
    )
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
