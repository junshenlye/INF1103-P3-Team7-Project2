"""Tests for the PostgreSQL connection-pool contract."""

from contextlib import contextmanager
import unittest

from src.contracts import PostgresPool


class FakePool:
    def __init__(self):
        self.checked_out = 0

    @contextmanager
    def connection(self):
        self.checked_out += 1
        try:
            yield object()
        finally:
            self.checked_out -= 1


class PostgresPoolContractTests(unittest.TestCase):
    def test_connection_factory_satisfies_the_contract(self):
        pool = FakePool()
        self.assertIsInstance(pool, PostgresPool)

    def test_connection_context_manages_checkout_lifecycle(self):
        pool = FakePool()
        with pool.connection() as connection:
            self.assertIsNotNone(connection)
            self.assertEqual(pool.checked_out, 1)
        self.assertEqual(pool.checked_out, 0)

    def test_object_without_connection_method_does_not_satisfy_contract(self):
        self.assertNotIsInstance(object(), PostgresPool)


if __name__ == "__main__":
    unittest.main()
