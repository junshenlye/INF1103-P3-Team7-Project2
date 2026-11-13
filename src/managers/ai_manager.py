"""Run a claimed processing job through the document queue."""

from __future__ import annotations

import asyncio

from src.contracts.provider_client import ProviderClient
from src.contracts.worker_data import WorkerData
from src.errors import error_codes as errors
from src.errors.issues import issue_from_error, make_issue
from src.errors.processing_error import ProcessingError, safe_processing_error
from src.managers.logic_manager import LogicManager
from src.models.processing import lifecycle
from src.models.processing.document_task import UNKNOWN, DocumentOutcome
from src.processing.document_processing import process_document_task
from src.processing.job_heartbeat import job_heartbeat
from src.processing.module_reconciliation import reconcile_module


class AIManager:
    """Coordinate provider-backed processing through the worker data contract."""

    def __init__(
        self,
        data_manager: WorkerData,
        logic_manager: LogicManager,
        docling_client: ProviderClient,
        gpt_client: ProviderClient,
        settings,
    ):
        self.data = data_manager
        self.logic = logic_manager
        self.docling = docling_client
        self.gpt = gpt_client
        self.settings = settings

    async def process_next_job(self) -> bool:
        """Recover abandoned work, then claim and settle one job if available."""
        await asyncio.to_thread(self.data.cleanup_interrupted_jobs)
        job = await asyncio.to_thread(self.data.claim_next_job)
        if job is None:
            return False

        try:
            async with job_heartbeat(self.data, job, self.settings.lease_seconds):
                await self._process_job(job)
                await asyncio.to_thread(self.data.save_job_heartbeat, job, lifecycle.VALIDATING)
            await asyncio.to_thread(self.data.complete_job, job)
        except asyncio.CancelledError:
            issue = make_issue(errors.PROCESSING_INTERRUPTED, errors.INTERRUPTION_MESSAGE)
            await asyncio.to_thread(self.data.fail_job, job, [issue], interrupted=True)
            raise
        except Exception as error:
            failure = safe_processing_error(error)
            await asyncio.to_thread(
                self.data.fail_job,
                job,
                [issue_from_error(failure)],
                interrupted=failure.code == errors.PROCESSING_INTERRUPTED,
            )
        return True

    async def _process_job(self, job):
        project = await asyncio.to_thread(self.data.get_project, job.project_id)
        modules = await asyncio.to_thread(self.data.get_job_modules, job.id)
        by_id = {module.id: module for module in modules}
        reconciliation = asyncio.Lock()

        async def consume():
            while True:
                task = await asyncio.to_thread(self.data.claim_document_task, job)
                if task is None:
                    return
                module = by_id[task.document.module_id]
                await self._settle_document(job, task, module, project.week_count)
                async with reconciliation:
                    # A pending document may supply facts needed to validate this module.
                    try:
                        await reconcile_module(self.data, self.logic, job, module, project.week_count)
                    except ProcessingError as error:
                        if error.code == errors.PROCESSING_INTERRUPTED:
                            raise

        consumers = [
            asyncio.create_task(consume()) for _ in range(self.settings.document_workers)
        ]
        try:
            await asyncio.gather(*consumers)
        finally:
            for consumer in consumers:
                if not consumer.done():
                    consumer.cancel()
            await asyncio.gather(*consumers, return_exceptions=True)

        for module in modules:
            try:
                await reconcile_module(self.data, self.logic, job, module, project.week_count)
            except ProcessingError as error:
                if error.code == errors.PROCESSING_INTERRUPTED:
                    raise
                issue = issue_from_error(error, module_id=module.id)
                await asyncio.to_thread(self.data.save_module_issue, job, issue)

    async def _settle_document(self, job, task, module, week_count):
        try:
            outcome = await process_document_task(
                data=self.data,
                logic=self.logic,
                docling=self.docling,
                gpt=self.gpt,
                settings=self.settings,
                job=job,
                task=task,
                module=module,
                week_count=week_count,
            )
        except ProcessingError as error:
            if error.code == errors.PROCESSING_INTERRUPTED:
                raise
            issue = issue_from_error(error, module_id=module.id, document_id=task.document.id)
            outcome = DocumentOutcome(UNKNOWN, issues=(issue,))
        await asyncio.to_thread(self.data.finish_document_task, job, task, outcome)
