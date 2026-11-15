"""Verify that the worker's persistence object reaches every PostgreSQL adapter."""

import inspect
from pathlib import Path
import unittest
from unittest.mock import Mock

from src.contracts.worker_data import WorkerData
from src.storage.postgres_worker_data import PostgresWorkerData

DIRECTORY = Path("/data/documents")

# Each WorkerData operation, the adapter that implements it, and sample arguments.
DELEGATION = {
    "cleanup_interrupted_jobs": ("recovery", ()),
    "claim_next_job": ("leases", ()),
    "save_job_heartbeat": ("leases", ("job", "extracting")),
    "complete_job": ("settlement", ("job",)),
    "fail_job": ("settlement", ("job", ["issue"], True)),
    "get_project": ("reads", ("project",)),
    "get_job_modules": ("reads", ("job-id",)),
    "get_processing_documents": ("reads", ("job-id", "module")),
    "open_document": ("originals", ("document",)),
    "claim_document_task": ("reads", ("job",)),
    "get_document_checkpoint": ("checkpoints", ("document",)),
    "save_document_progress": ("progress", ("job", "document", "parsing")),
    "save_document_checkpoint": ("checkpoints", ("job", "document", "checkpoint")),
    "save_document_chunk": ("reads", ("job", "task", 0, "parse", ["record"], ["note"])),
    "record_extraction_attempt": (
        "reads",
        ("job", "task", "extract", 0, 1, "provider_failed", "Failed.", 503, {"x": 1}),
    ),
    "finish_document_task": ("outcomes", ("job", "task", "outcome")),
    "get_module_checkpoint": ("reads", ("job-id", "module")),
    "save_extraction_result": (
        "results",
        ("job", "result", ["assessment"], "manifest", {"a": 1}, ("transfer",)),
    ),
    "save_module_issue": ("module_issues", ("job", {"code": "x"})),
    "acquire_provider_permit": ("permits", ("job", "gpt", 2)),
    "release_provider_permit": ("permits", ("job", "gpt", 1)),
}


def contract_operations():
    return {
        name
        for name, value in vars(WorkerData).items()
        if inspect.isfunction(value) and not name.startswith("_")
    }


class PostgresWorkerDataTests(unittest.TestCase):
    def setUp(self):
        self.pool = Mock()
        self.data = PostgresWorkerData(self.pool, DIRECTORY, lease_seconds=45)

    def test_satisfies_the_worker_contract(self):
        self.assertIsInstance(self.data, WorkerData)

    def test_every_contract_operation_is_delegated(self):
        self.assertEqual(set(DELEGATION), contract_operations())
        for name in contract_operations():
            with self.subTest(name):
                self.assertIn(name, vars(PostgresWorkerData))

    def test_operations_forward_arguments_and_results_to_their_adapter(self):
        for name, (adapter, arguments) in DELEGATION.items():
            with self.subTest(name):
                target = Mock()
                getattr(target, name).return_value = f"{name}-result"
                setattr(self.data, adapter, target)

                returned = getattr(self.data, name)(*arguments)

                getattr(target, name).assert_called_once_with(*arguments)
                if name in {
                    "save_job_heartbeat",
                    "save_document_progress",
                    "save_document_checkpoint",
                    "save_document_chunk",
                    "record_extraction_attempt",
                    "save_module_issue",
                    "release_provider_permit",
                }:
                    self.assertIsNone(returned)
                else:
                    self.assertEqual(returned, f"{name}-result")

    def test_optional_arguments_keep_the_contract_defaults(self):
        self.data.leases = Mock()
        self.data.settlement = Mock()
        self.data.results = Mock()
        self.data.reads = Mock()

        self.data.save_job_heartbeat("job")
        self.data.fail_job("job", [])
        self.data.save_extraction_result("job", "result", [])
        self.data.record_extraction_attempt("job", "task", "parse", None, 1, "code", "Failed.")

        self.data.leases.save_job_heartbeat.assert_called_once_with("job", None)
        self.data.settlement.fail_job.assert_called_once_with("job", [], False)
        self.data.results.save_extraction_result.assert_called_once_with(
            "job", "result", [], "legacy", None, ()
        )
        self.data.reads.record_extraction_attempt.assert_called_once_with(
            "job", "task", "parse", None, 1, "code", "Failed.", None, None
        )

    def test_adapters_share_the_pool_and_settings(self):
        adapters = [
            self.data.reads, self.data.leases, self.data.recovery, self.data.settlement,
            self.data.originals, self.data.checkpoints, self.data.progress,
            self.data.outcomes, self.data.results, self.data.module_issues, self.data.permits,
        ]
        for adapter in adapters:
            with self.subTest(type(adapter).__name__):
                self.assertIs(adapter.pool, self.pool)
        self.assertEqual(self.data.originals.document_directory, DIRECTORY)
        self.assertEqual(self.data.reads.document_originals.document_directory, DIRECTORY)
        self.assertEqual(self.data.leases.lease_seconds, 45)
        self.assertEqual(self.data.progress.lease_seconds, 45)

    def test_constructing_does_not_open_a_connection(self):
        self.pool.connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
