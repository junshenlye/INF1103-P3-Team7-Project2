"""Verify worker job coordination with injected data and processing steps."""

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from src.errors import error_codes as errors
from src.errors.processing_error import ProcessingError
from src.managers import AIManager, LogicManager
from src.models.processing import lifecycle
from src.models.processing.document_task import DocumentOutcome, DocumentTask, UNDERSTOOD, UNKNOWN

JOB = SimpleNamespace(id="job", project_id="project")
MODULE = SimpleNamespace(id="module")
TASKS = [
    DocumentTask(SimpleNamespace(id=document_id, module_id=MODULE.id), 1)
    for document_id in ("one", "two")
]
SETTINGS = SimpleNamespace(document_workers=2, lease_seconds=60)


class AIManagerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.data = Mock()
        self.data.claim_next_job.return_value = JOB
        self.data.get_project.return_value = SimpleNamespace(week_count=14)
        self.data.get_job_modules.return_value = [MODULE]
        pending = iter(TASKS)
        self.data.claim_document_task.side_effect = lambda job: next(pending, None)
        self.manager = AIManager(self.data, LogicManager(), None, None, SETTINGS)

        for name in ("process_document_task", "reconcile_module"):
            patcher = patch(f"src.managers.ai_manager.{name}", new_callable=AsyncMock)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    async def test_empty_queue_recovers_old_jobs_without_starting_new_work(self):
        self.data.claim_next_job.return_value = None

        self.assertFalse(await self.manager.process_next_job())

        self.assertEqual(
            [call[0] for call in self.data.mock_calls],
            ["cleanup_interrupted_jobs", "claim_next_job"],
        )
        self.process_document_task.assert_not_awaited()

    async def test_document_failure_preserves_other_work_and_final_module_issue(self):
        outcome = DocumentOutcome(UNDERSTOOD)
        parse_error = ProcessingError(errors.DOCUMENT_PARSE_FAILED, "Cannot parse.", "document")
        module_error = ProcessingError(errors.INVALID_EXTRACTION, "Missing parent.", "module")

        async def process(*, task, **kwargs):
            if task is TASKS[0]:
                raise parse_error
            return outcome

        self.process_document_task.side_effect = process
        self.reconcile_module.side_effect = [module_error, None, module_error]

        self.assertTrue(await self.manager.process_next_job())

        settled = {
            call.args[1].document.id: call.args[2]
            for call in self.data.finish_document_task.call_args_list
        }
        self.assertEqual(settled["one"].inference, UNKNOWN)
        self.assertEqual(settled["one"].issues[0]["code"], errors.DOCUMENT_PARSE_FAILED)
        self.assertEqual(settled["two"], outcome)
        self.assertEqual(self.reconcile_module.await_count, 3)
        self.data.save_module_issue.assert_called_once()
        self.assertEqual(self.data.save_module_issue.call_args.args[1]["module_id"], MODULE.id)
        self.data.save_job_heartbeat.assert_called_once_with(JOB, lifecycle.VALIDATING)
        self.data.complete_job.assert_called_once_with(JOB)
        self.data.fail_job.assert_not_called()

    async def test_job_failure_cancels_sibling_before_recording_safe_issue(self):
        started = asyncio.Event()
        stopped = asyncio.Event()

        async def process(*, task, **kwargs):
            if task is TASKS[0]:
                await started.wait()
                raise RuntimeError("private provider details")
            started.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()

        self.process_document_task.side_effect = process

        self.assertTrue(await asyncio.wait_for(self.manager.process_next_job(), 2))

        self.assertTrue(stopped.is_set())
        self.data.complete_job.assert_not_called()
        self.data.finish_document_task.assert_not_called()
        issue = self.data.fail_job.call_args.args[1][0]
        self.assertEqual(issue["code"], errors.PROVIDER_UNAVAILABLE)
        self.assertNotIn("private provider details", issue["message"])

    async def test_cancellation_records_interruption_and_propagates(self):
        started = asyncio.Event()

        async def process(**kwargs):
            started.set()
            await asyncio.Future()

        self.process_document_task.side_effect = process
        task = asyncio.create_task(self.manager.process_next_job())
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await task

        self.data.complete_job.assert_not_called()
        self.data.fail_job.assert_called_once()
        self.assertTrue(self.data.fail_job.call_args.kwargs["interrupted"])
        self.assertEqual(
            self.data.fail_job.call_args.args[1][0]["code"], errors.PROCESSING_INTERRUPTED
        )
