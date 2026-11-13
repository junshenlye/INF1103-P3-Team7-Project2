"""Apply Stackplan's versioned PostgreSQL schema migrations."""

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path

from src.contracts.postgres_pool import PostgresPool

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"


def apply_migrations(pool: PostgresPool, directory: Path = MIGRATIONS) -> None:
    """Apply pending migrations in filename order under one transaction lock.

    The ledger records each script's checksum in the same transaction as
    its schema changes. A changed applied script aborts the transaction.
    """
    scripts = sorted(directory.glob("*.sql"))
    if not scripts:
        raise ValueError(f"No SQL migrations found in {directory}.")

    with pool.connection() as connection, connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(719231)")
        connection.execute("CREATE SCHEMA IF NOT EXISTS stackplan")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS stackplan.schema_migrations "
            "(version text PRIMARY KEY, checksum text NOT NULL)"
        )
        for script in scripts:
            contents = script.read_text(encoding="utf-8")
            checksum = sha256(contents.encode("utf-8")).hexdigest()
            applied = connection.execute(
                "SELECT checksum FROM stackplan.schema_migrations WHERE version = %s",
                (script.name,),
            ).fetchone()
            if applied is not None:
                applied_checksum = applied["checksum"] if isinstance(applied, Mapping) else applied[0]
                if applied_checksum != checksum:
                    raise ValueError(f"Applied migration {script.name} has changed.")
                continue

            connection.execute("SET LOCAL search_path TO stackplan")
            connection.execute(contents)
            connection.execute(
                "INSERT INTO stackplan.schema_migrations (version, checksum) VALUES (%s, %s)",
                (script.name, checksum),
            )
