"""Create the PostgreSQL connection pool used by storage adapters."""

from contextlib import contextmanager
from typing import Iterator

from src.config.settings import Settings
from src.contracts.postgres_pool import PostgresPool


@contextmanager
def open_postgres_pool(settings: Settings) -> Iterator[PostgresPool]:
    """Wait for the first connection and close the pool when the caller exits."""
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    with ConnectionPool(
        conninfo=settings.database_url,
        open=False,
        min_size=1,
        max_size=settings.pool_size,
        timeout=5,
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
            "connect_timeout": 5,
            "options": (
                "-c search_path=stackplan,public "
                "-c statement_timeout=5000 -c lock_timeout=2000"
            ),
        },
    ) as pool:
        pool.wait(timeout=10)
        yield pool
