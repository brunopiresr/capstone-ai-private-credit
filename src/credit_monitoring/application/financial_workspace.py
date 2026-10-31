"""Additive, backed-up upgrades from the bundled financial snapshot."""

import hashlib
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from threading import Lock

from credit_monitoring.persistence.database import open_database
from credit_monitoring.persistence.schema import initialize_financial_schema

_INITIALIZATION_LOCK = Lock()


def initialize_working_financials(source: Path, destination: Path) -> Path:
    """Copy a fresh snapshot or add missing rows, preserving all working values."""
    source, destination = Path(source), Path(destination)
    version = hashlib.sha256(
        (source.parent / "synthetic_quarterly_financials.csv").read_bytes()
    ).hexdigest()
    with _INITIALIZATION_LOCK:
        destination.parent.mkdir(parents=True, exist_ok=True)
        fresh = not destination.exists()
        if fresh:
            temporary = destination.with_suffix(".initializing")
            try:
                shutil.copyfile(source, temporary)
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
        with open_database(destination) as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'bundled_dataset_versions'"
            ).fetchone()
            if (
                exists
                and connection.execute(
                    "SELECT 1 FROM bundled_dataset_versions WHERE version = ?", (version,)
                ).fetchone()
            ):
                return destination
        if not fresh:
            backup = destination.parent / "backups" / f"financials-before-{version[:12]}.sqlite3"
            backup.parent.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                temporary = backup.with_suffix(".tmp")
                with (
                    closing(sqlite3.connect(destination)) as original,
                    closing(sqlite3.connect(temporary)) as retained,
                ):
                    original.backup(retained)
                temporary.replace(backup)
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as bundled:
            bundled.row_factory = sqlite3.Row
            rows = [dict(row) for row in bundled.execute("SELECT * FROM quarterly_financials")]
        with open_database(destination) as connection:
            connection.execute("BEGIN IMMEDIATE")
            initialize_financial_schema(connection)
            columns = [
                row[1] for row in connection.execute("PRAGMA table_info(quarterly_financials)")
            ]
            connection.executemany(
                f"INSERT OR IGNORE INTO quarterly_financials ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                [[row.get(column) for column in columns] for row in rows],
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS bundled_dataset_versions (version TEXT PRIMARY KEY)"
            )
            connection.execute("INSERT INTO bundled_dataset_versions VALUES (?)", (version,))
    return destination
