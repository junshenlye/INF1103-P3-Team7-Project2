"""Persistence boundary consumed by the background processing worker."""

from __future__ import annotations

from typing import BinaryIO, ContextManager, Protocol, Sequence, runtime_checkable

from src.models.assessments.assessment import Assessment
from src.models.documents.document_reference import DocumentReference
from src.models.processing.checkpoint import DocumentCheckpoint
from src.models.processing.extraction_result import ExtractionResult
from src.models.processing.processing_job import ProcessingJob
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

    def get_project(self, project_id: str) -> Project: ...

    def get_job_modules(self, job_id: str) -> Sequence[Module]: ...

    def get_processing_documents(
        self, job_id: str, module_id: str
    ) -> Sequence[DocumentReference]: ...

    def open_document(self, document_id: str) -> ContextManager[BinaryIO]: ...

    def save_job_heartbeat(
        self, job: ProcessingJob, stage: str | None = None
    ) -> None: ...

    def save_document_progress(
        self, job: ProcessingJob, document_id: str, state: str
    ) -> None: ...

    def save_document_checkpoint(
        self, job: ProcessingJob, document_id: str, checkpoint: DocumentCheckpoint
    ) -> None: ...

    def save_extraction_result(
        self,
        job: ProcessingJob,
        result: ExtractionResult,
        assessments: Sequence[Assessment],
    ) -> None: ...

    def complete_job(self, job: ProcessingJob) -> None: ...

    def fail_job(
        self, job: ProcessingJob, issues: list[dict], interrupted: bool = False
    ) -> None: ...
