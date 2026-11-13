"""Apply pending database migrations: ``python -m src.migrate``.

Settings come from the environment (see ``.env.example``), so the same
command works locally, in CI and before the application starts in a
container. Applied migrations are skipped, which makes it safe to run on
every deployment.
"""

from __future__ import annotations

import sys

from src.config.settings import load_settings
from src.storage.postgres_migrations import MIGRATIONS, apply_migrations
from src.storage.postgres_pool import open_postgres_pool


def main(environ=None, *, open_pool=open_postgres_pool, migrate=apply_migrations, directory=MIGRATIONS) -> int:
    """Open a pool from the environment, apply pending migrations and close it.

    Returns 0 on success. Invalid settings or a failed migration are reported
    on stderr with exit status 1, without printing the database URL.
    """
    try:
        settings = load_settings(environ)
    except KeyError as missing:
        print(f"Missing required setting {missing.args[0]}.", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"Invalid settings: {error}", file=sys.stderr)
        return 1
    try:
        with open_pool(settings) as pool:
            migrate(pool, directory)
    except Exception as error:
        print(f"Migration failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print("Database schema is up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
