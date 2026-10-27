#!/usr/bin/env python3
"""Populate the same HTML cache used by document processing; no work on import."""

import argparse
import os
import sys
from pathlib import Path

import requests

from credit_monitoring.ingestion.loaders.sec import load_catalog, load_sec_html
from credit_monitoring.paths import SEC_CACHE_DIR, SEC_CATALOG


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-file", type=Path, default=SEC_CATALOG)
    parser.add_argument("--html-dir", type=Path, default=SEC_CACHE_DIR / "html")
    parser.add_argument("--document-id", action="append", help="Select an ID; repeat for more IDs.")
    args = parser.parse_args(argv)
    try:
        rows = load_catalog(args.source_file)
        ids = [row["document_id"] for row in rows]
        if len(ids) != len(set(ids)):
            raise ValueError("Catalog document IDs must be unique.")
        requested = set(args.document_id or ids)
        if unknown := requested - set(ids):
            raise ValueError(f"Unknown document IDs: {', '.join(sorted(unknown))}")
    except (OSError, KeyError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    failed = False
    for row in rows:
        if row["document_id"] not in requested:
            continue
        try:
            path = load_sec_html(
                row, html_dir=args.html_dir, user_agent=os.environ.get("SEC_USER_AGENT", "")
            )
            print(f"ready {path}")
        except (OSError, KeyError, ValueError, requests.RequestException) as error:
            failed = True
            print(f"ERROR {row['document_id']}: {error}", file=sys.stderr)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
