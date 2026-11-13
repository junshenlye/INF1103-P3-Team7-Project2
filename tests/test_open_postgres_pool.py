"""Verify PostgreSQL pool configuration and ownership."""

from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import MagicMock, Mock, sentinel, patch

from src.config.settings import Settings
from src.storage.postgres_pool import open_postgres_pool


class OpenPostgresPoolTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(
            database_url="postgresql://localhost/project",
            document_directory=Path.cwd(),
            pool_size=3,
        )
        self.pool = MagicMock()
        self.pool.__enter__.return_value = self.pool
        self.factory = Mock(return_value=self.pool)
        driver = ModuleType("psycopg")
        rows = ModuleType("psycopg.rows")
        rows.dict_row = sentinel.dict_row
        pool_module = ModuleType("psycopg_pool")
        pool_module.ConnectionPool = self.factory
        modules = {"psycopg": driver, "psycopg.rows": rows, "psycopg_pool": pool_module}
        patcher = patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_configures_pool_and_waits_before_yielding(self):
        with open_postgres_pool(self.settings) as pool:
            self.assertIs(pool, self.pool)
            pool.wait.assert_called_once_with(timeout=10)
            pool.__exit__.assert_not_called()

        self.factory.assert_called_once_with(
            conninfo=self.settings.database_url,
            open=False,
            min_size=1,
            max_size=3,
            timeout=5,
            kwargs={
                "autocommit": True,
                "row_factory": sentinel.dict_row,
                "connect_timeout": 5,
                "options": (
                    "-c search_path=stackplan,public "
                    "-c statement_timeout=5000 -c lock_timeout=2000"
                ),
            },
        )
        self.pool.__exit__.assert_called_once_with(None, None, None)

    def test_closes_the_pool_if_startup_wait_fails(self):
        failure = TimeoutError("Database unavailable")
        self.pool.wait.side_effect = failure

        with self.assertRaises(TimeoutError):
            with open_postgres_pool(self.settings):
                self.fail("Pool was yielded before becoming ready")

        self.pool.__exit__.assert_called_once()
        self.assertIs(self.pool.__exit__.call_args.args[1], failure)
