"""Tests for the worker persistence boundary."""

import unittest

from src.contracts import WorkerData


class CompleteWorkerDataDouble:
    def cleanup_interrupted_jobs(self): pass
    def claim_next_job(self): pass
    def get_project(self, project_id): pass
    def get_job_modules(self, job_id): pass
    def get_processing_documents(self, job_id, module_id): pass
    def open_document(self, document_id): pass
    def save_job_heartbeat(self, job, stage=None): pass
    def save_document_progress(self, job, document_id, state): pass
    def save_document_checkpoint(self, job, document_id, checkpoint): pass
    def save_extraction_result(self, job, result, assessments): pass
    def complete_job(self, job): pass
    def fail_job(self, job, issues, interrupted=False): pass


class IncompleteWorkerDataDouble:
    def claim_next_job(self): pass


class WorkerDataContractTests(unittest.TestCase):
    def test_complete_adapter_satisfies_worker_contract(self):
        self.assertIsInstance(CompleteWorkerDataDouble(), WorkerData)

    def test_incomplete_adapter_does_not_satisfy_worker_contract(self):
        self.assertNotIsInstance(IncompleteWorkerDataDouble(), WorkerData)


if __name__ == "__main__":
    unittest.main()
