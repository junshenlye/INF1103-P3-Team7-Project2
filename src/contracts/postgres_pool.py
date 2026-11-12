"""Structural contract for a PostgreSQL connection pool or factory."""

from typing import Any, ContextManager, Protocol, runtime_checkable


@runtime_checkable
class PostgresPool(Protocol):
    """Lend a connection whose context manager owns its checkout lifecycle.

    Keeping the connection type generic avoids coupling domain contracts to a
    particular psycopg version or pool implementation. Adapters can provide a
    psycopg pool, a test double, or another compatible connection factory.
    """

    def connection(self) -> ContextManager[Any]: ...
