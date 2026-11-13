"""Persistence boundary consumed by the background processing worker."""

from __future__ import annotations

from typing import BinaryIO, ContextManager, Mapping, Protocol, Sequence, runtime_checkable

from src.models.assessments.assessment import Assessment
from src.models.documents.document_reference import DocumentReference
from src.models.processing.checkpoint import DocumentCheckpoint, ModuleCheckpoint
from src.models.processing.document_task import DocumentOutcome, DocumentTask
from src.models.processing.extraction_result import ExtractionResult
from src.models.processing.processing_job import ProcessingJob
from src.models.processing.review_transfer import ReviewTransfer
from src.models.projects.module import Module
from src.models.projects.project import Project


@runtime_checkable
class WorkerData(Protocol):
    """The worker's persistence use cases, without SQL or filesystem details.

    Data adapters implement this contract while processing orchestration stays
    independent of a particular database, storage system, or queue library.
    """

    def cleanup_interrupted_jobs(self) -> int: ...

    def claim_next_job(self) -> ProcessingJob | None: ...

    def claim_document_task(self, job: ProcessingJob) -> DocumentTask | None:
        """Lease the next queued document of ``job``, or return None when none remain."""

    def get_project(self, project_id: str) -> Project: ...

    def get_job_modules(self, job_id: str) -> Sequence[Module]: ...

    def get_processing_documents(
        self, job_id: str, module_id: str
    ) -> Sequence[DocumentReference]: ...

    def open_document(self, document_id: str) -> ContextManager[BinaryIO]: ...

    def get_document_checkpoint(self, document_id: str) -> DocumentCheckpoint:
        """Return the saved parse and accepted chunks that a retry can reuse."""

    def get_module_checkpoint(self, job_id: str, module_id: str) -> ModuleCheckpoint:
        """Return the accepted records and review state needed to reconcile a module."""

    def save_job_heartbeat(
        self, job: ProcessingJob, stage: str | None = None
    ) -> None: ...

    def save_document_progress(
        self, job: ProcessingJob, document_id: str, state: str
    ) -> None: ...

    def save_document_checkpoint(
        self, job: ProcessingJob, document_id: str, checkpoint: DocumentCheckpoint
    ) -> None: ...

    def save_document_chunk(
        self,
        job: ProcessingJob,
        task: DocumentTask,
        index: int,
        parse_id: str,
        records: list[dict],
        uncertainties: list[str],
    ) -> None:
        """Store one accepted extraction chunk so it is not requested again."""

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
        """Record a failed parse or extraction attempt for later diagnosis."""

    def finish_document_task(
        self, job: ProcessingJob, task: DocumentTask, outcome: DocumentOutcome
    ) -> None:
        """Settle a leased document task with what was understood from it."""

    def save_extraction_result(
        self,
        job: ProcessingJob,
        result: ExtractionResult,
        assessments: Sequence[Assessment],
        manifest: str = "legacy",
        previous_versions: Mapping[str, int] | None = None,
        review_transfers: tuple[ReviewTransfer, ...] = (),
    ) -> None:
        """Publish a module result, rejecting it if a review changed meanwhile."""

    def save_module_issue(self, job: ProcessingJob, issue: dict) -> None:
        """Record an issue that applies to a whole module rather than one document."""

    def acquire_provider_permit(
        self, job: ProcessingJob, provider: str, capacity: int
    ) -> int | None:
        """Reserve one of ``capacity`` provider slots, or return None when all are busy."""

    def release_provider_permit(self, job: ProcessingJob, provider: str, slot: int) -> None:
        """Free a provider slot returned by ``acquire_provider_permit``."""

    def complete_job(self, job: ProcessingJob) -> None: ...

    def fail_job(
        self, job: ProcessingJob, issues: list[dict], interrupted: bool = False
    ) -> None: ...
