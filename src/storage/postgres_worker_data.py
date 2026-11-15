"""Combine the PostgreSQL adapters into the worker's persistence object."""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, ContextManager, Mapping, Sequence

from src.config.limits import LEASE_SECONDS
from src.contracts.postgres_pool import PostgresPool
from src.managers.data_manager import DataManager
from src.models.assessments.assessment import Assessment
from src.models.documents.document_reference import DocumentReference
from src.models.processing.checkpoint import DocumentCheckpoint, ModuleCheckpoint
from src.models.processing.document_task import DocumentOutcome, DocumentTask
from src.models.processing.extraction_result import ExtractionResult
from src.models.processing.processing_job import ProcessingJob
from src.models.processing.review_transfer import ReviewTransfer
from src.models.projects.module import Module
from src.models.projects.project import Project
from src.storage.postgres_document_checkpoints import PostgresDocumentCheckpoints
from src.storage.postgres_document_originals import PostgresDocumentOriginals
from src.storage.postgres_document_progress import PostgresDocumentProgress
from src.storage.postgres_document_task_outcomes import PostgresDocumentTaskOutcomes
from src.storage.postgres_extraction_results import PostgresExtractionResults
from src.storage.postgres_job_leases import PostgresJobLeases
from src.storage.postgres_job_recovery import PostgresJobRecovery
from src.storage.postgres_job_settlement import PostgresJobSettlement
from src.storage.postgres_module_issues import PostgresModuleIssues
from src.storage.postgres_provider_permits import PostgresProviderPermits


class PostgresWorkerData:
    """Implement ``WorkerData`` by delegating each operation to its adapter.

    Every adapter shares one connection pool. The class holds no SQL of its
    own, so each operation keeps the transaction and lease checks of the
    adapter that implements it.
    """

    def __init__(
        self,
        pool: PostgresPool,
        document_directory: Path,
        lease_seconds: int = LEASE_SECONDS,
    ):
        self.reads = DataManager(pool, document_directory=document_directory)
        self.leases = PostgresJobLeases(pool, lease_seconds)
        self.recovery = PostgresJobRecovery(pool)
        self.settlement = PostgresJobSettlement(pool)
        self.originals = PostgresDocumentOriginals(pool, document_directory)
        self.checkpoints = PostgresDocumentCheckpoints(pool)
        self.progress = PostgresDocumentProgress(pool, lease_seconds)
        self.outcomes = PostgresDocumentTaskOutcomes(pool)
        self.results = PostgresExtractionResults(pool)
        self.module_issues = PostgresModuleIssues(pool)
        self.permits = PostgresProviderPermits(pool)

    # Jobs
    def cleanup_interrupted_jobs(self) -> int:
        return self.recovery.cleanup_interrupted_jobs()

    def claim_next_job(self) -> ProcessingJob | None:
        return self.leases.claim_next_job()

    def save_job_heartbeat(self, job: ProcessingJob, stage: str | None = None) -> None:
        self.leases.save_job_heartbeat(job, stage)

    def complete_job(self, job: ProcessingJob):
        return self.settlement.complete_job(job)

    def fail_job(self, job: ProcessingJob, issues: list[dict], interrupted: bool = False):
        return self.settlement.fail_job(job, issues, interrupted)

    # Job inputs
    def get_project(self, project_id: str) -> Project:
        return self.reads.get_project(project_id)

    def get_job_modules(self, job_id: str) -> Sequence[Module]:
        return self.reads.get_job_modules(job_id)

    def get_processing_documents(self, job_id: str, module_id: str) -> Sequence[DocumentReference]:
        return self.reads.get_processing_documents(job_id, module_id)

    def open_document(self, document_id: str) -> ContextManager[BinaryIO]:
        return self.originals.open_document(document_id)

    # Document tasks
    def claim_document_task(self, job: ProcessingJob) -> DocumentTask | None:
        return self.reads.claim_document_task(job)

    def get_document_checkpoint(self, document_id: str) -> DocumentCheckpoint:
        return self.checkpoints.get_document_checkpoint(document_id)

    def save_document_progress(self, job: ProcessingJob, document_id: str, state: str) -> None:
        self.progress.save_document_progress(job, document_id, state)

    def save_document_checkpoint(
        self, job: ProcessingJob, document_id: str, checkpoint: DocumentCheckpoint
    ) -> None:
        self.checkpoints.save_document_checkpoint(job, document_id, checkpoint)

    def save_document_chunk(
        self,
        job: ProcessingJob,
        task: DocumentTask,
        index: int,
        parse_id: str,
        records: list[dict],
        uncertainties: list[str],
    ) -> None:
        self.reads.save_document_chunk(job, task, index, parse_id, records, uncertainties)

    def record_extraction_attempt(
        self,
        job: ProcessingJob,
        task: DocumentTask,
        stage: str,
        index: int | None,
        attempt: int,
        code: str,
        message: str,
        status: int | None = None,
        rejected: dict | None = None,
    ) -> None:
        self.reads.record_extraction_attempt(
            job, task, stage, index, attempt, code, message, status, rejected
        )

    def finish_document_task(
        self, job: ProcessingJob, task: DocumentTask, outcome: DocumentOutcome
    ):
        return self.outcomes.finish_document_task(job, task, outcome)

    # Modules
    def get_module_checkpoint(self, job_id: str, module_id: str) -> ModuleCheckpoint:
        return self.reads.get_module_checkpoint(job_id, module_id)

    def save_extraction_result(
        self,
        job: ProcessingJob,
        result: ExtractionResult,
        assessments: Sequence[Assessment],
        manifest: str = "legacy",
        previous_versions: Mapping[str, int] | None = None,
        review_transfers: tuple[ReviewTransfer, ...] = (),
    ):
        return self.results.save_extraction_result(
            job, result, assessments, manifest, previous_versions, review_transfers
        )

    def save_module_issue(self, job: ProcessingJob, issue: dict) -> None:
        self.module_issues.save_module_issue(job, issue)

    # Provider capacity
    def acquire_provider_permit(
        self, job: ProcessingJob, provider: str, capacity: int
    ) -> int | None:
        return self.permits.acquire_provider_permit(job, provider, capacity)

    def release_provider_permit(self, job: ProcessingJob, provider: str, slot: int) -> None:
        self.permits.release_provider_permit(job, provider, slot)
