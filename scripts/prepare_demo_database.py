"""Refresh the bundled financial database after intentionally changing the demo CSV."""

import argparse
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from credit_monitoring.ingestion.loaders.financials import load_financials
from credit_monitoring.paths import APP_SYNTHETIC_DIR, BUNDLED_FINANCIAL_DB, ROOT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=BUNDLED_FINANCIAL_DB)
    arguments = parser.parse_args()
    source = APP_SYNTHETIC_DIR / "synthetic_quarterly_financials.csv"
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=arguments.output.parent) as temporary:
        database = Path(temporary) / "financials.sqlite3"
        load_financials(source, database)
        # Retain provenance without embedding the maintainer's checkout location.
        with sqlite3.connect(database) as connection:
            connection.execute(
                "UPDATE quarterly_financials SET source_file = ?",
                (source.relative_to(ROOT).as_posix(),),
            )
        database.replace(arguments.output)


if __name__ == "__main__":
    main()
