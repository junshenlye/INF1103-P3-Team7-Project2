"""Tests for the worker persistence boundary."""

import unittest

from src.contracts import WorkerData


class CompleteWorkerDataDouble:
    def cleanup_interrupted_jobs(self): pass
    def claim_next_job(self): pass
    def claim_document_task(self, job): pass
    def get_project(self, project_id): pass
    def get_job_modules(self, job_id): pass
    def get_processing_documents(self, job_id, module_id): pass
    def open_document(self, document_id): pass
    def get_document_checkpoint(self, document_id): pass
    def get_module_checkpoint(self, job_id, module_id): pass
    def save_job_heartbeat(self, job, stage=None): pass
    def save_document_progress(self, job, document_id, state): pass
    def save_document_checkpoint(self, job, document_id, checkpoint): pass
    def save_document_chunk(self, job, task, index, parse_id, records, uncertainties): pass
    def record_extraction_attempt(self, job, task, stage, index, attempt, code, message, status=None, rejected=None): pass
    def finish_document_task(self, job, task, outcome): pass
    def save_extraction_result(self, job, result, assessments, manifest="legacy", previous_versions=None, review_transfers=()): pass
    def save_module_issue(self, job, issue): pass
    def acquire_provider_permit(self, job, provider, capacity): pass
    def release_provider_permit(self, job, provider, slot): pass
    def complete_job(self, job): pass
    def fail_job(self, job, issues, interrupted=False): pass


class IncompleteWorkerDataDouble:
    def claim_next_job(self): pass


DOCUMENT_QUEUE_METHODS = (
    "claim_document_task",
    "get_document_checkpoint",
    "get_module_checkpoint",
    "save_document_chunk",
    "record_extraction_attempt",
    "finish_document_task",
    "save_module_issue",
    "acquire_provider_permit",
    "release_provider_permit",
)


class WorkerDataContractTests(unittest.TestCase):
    def test_complete_adapter_satisfies_worker_contract(self):
        self.assertIsInstance(CompleteWorkerDataDouble(), WorkerData)

    def test_incomplete_adapter_does_not_satisfy_worker_contract(self):
        self.assertNotIsInstance(IncompleteWorkerDataDouble(), WorkerData)

    def test_document_queue_methods_are_required(self):
        for name in DOCUMENT_QUEUE_METHODS:
            with self.subTest(method=name):
                partial = type("Partial", (CompleteWorkerDataDouble,), {name: None})
                self.assertNotIsInstance(partial(), WorkerData)


if __name__ == "__main__":
    unittest.main()
