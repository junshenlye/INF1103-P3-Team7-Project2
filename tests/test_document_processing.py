"""Tests for parsing one document and extracting assessments from its chunks."""

from contextlib import contextmanager
import io
from types import SimpleNamespace
import unittest
from unittest import mock

from src.errors import error_codes as errors
from src.errors.processing_error import ProcessingError
from src.managers import LogicManager
from src.models.documents.document_reference import DocumentReference
from src.models.processing.checkpoint import DocumentCheckpoint
from src.models.processing.document_task import (
    NO_ASSESSMENT_CONTENT,
    PARTIALLY_UNDERSTOOD,
    UNDERSTOOD,
    UNKNOWN,
    DocumentTask,
)
from src.models.projects.module import Module
from src.processing import document_processing
from src.processing.document_processing import process_document_task
from src.processing.retry_policy import RetryPolicy

MODULE = Module("module-1", "project-1", "job-1", "Intro Computing", "intro computing", 6, 0)
DOCUMENT = DocumentReference("doc-1", "module-1", "outline.pdf", "application/pdf", 10, "abc")
TASK = DocumentTask(DOCUMENT, 1)
JOB = SimpleNamespace(id="job-1")
SETTINGS = SimpleNamespace(
    chunk_bytes=2048,
    max_chunks=10,
    provider_timeout=5,
    gpt_concurrency=2,
    gpt_model="model",
    gpt_api_key="key",
)
PARSED = {"texts": [{"text": "Quiz in week 3, worth 20 percent.", "prov": []}]}
EMPTY_CHECKPOINT = DocumentCheckpoint(None, (), {}, 0, 0)


class DocumentStore:
    """In-memory stand-in for the worker data operations used per document."""

    def __init__(self, checkpoint=EMPTY_CHECKPOINT):
        self.checkpoint = checkpoint
        self.progress = []
        self.saved_checkpoints = []
        self.saved_chunks = []
        self.attempts = []
        self.permits = []

    def get_document_checkpoint(self, document_id):
        return self.checkpoint

    def save_document_progress(self, job, document_id, state):
        self.progress.append(state)

    @contextmanager
    def open_document(self, document_id):
        yield io.BytesIO(b"%PDF-")

    def save_document_checkpoint(self, job, document_id, checkpoint):
        self.saved_checkpoints.append(checkpoint)

    def save_document_chunk(self, job, task, index, parse_id, records, uncertainties):
        self.saved_chunks.append((index, parse_id, records, uncertainties))

    def record_extraction_attempt(self, job, task, stage, index, attempt, code, message, status=None, rejected=None):
        self.attempts.append((stage, index, code, rejected))

    def acquire_provider_permit(self, job, provider, capacity):
        self.permits.append((provider, capacity))
        return 0

    def release_provider_permit(self, job, provider, slot):
        pass


def extraction(source_ids, week=3, title="Intro Computing", key="quiz"):
    source = sorted(source_ids)[0]
    return {
        "module_title": title,
        "assessments": [
            {
                "key": key,
                "name": key.title(),
                "kind": "assessment",
                "weight_percent": 20,
                "weight_scope": "module",
                "week": week,
                "end_week": None,
                "parent_key": None,
                "evidence": {
                    "name": [source],
                    "kind": [source],
                    "weight_percent": [source],
                    "weight_scope": [source],
                    "week": [source],
                },
            }
        ],
        "uncertainties": [],
    }


class ProcessDocumentTaskTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logic = LogicManager()
        self.delays = []
        self.convert = mock.AsyncMock(return_value=PARSED)
        self.extract = mock.AsyncMock(side_effect=self.extract_from_chunk)
        for name, replacement in (
            ("convert_document", self.convert),
            ("extract_assessment_chunk", self.extract),
        ):
            patcher = mock.patch.object(document_processing, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def extract_from_chunk(self, client, *, chunk, **kwargs):
        return extraction({element.id for element in chunk})

    async def sleep(self, seconds):
        self.delays.append(seconds)

    async def process(self, store):
        return await process_document_task(
            data=store,
            logic=self.logic,
            docling="docling-client",
            gpt="gpt-client",
            settings=SETTINGS,
            job=JOB,
            task=TASK,
            module=MODULE,
            week_count=14,
            policy=RetryPolicy(),
            sleep=self.sleep,
        )

    async def test_parses_extracts_and_saves_progress(self):
        store = DocumentStore()
        outcome = await self.process(store)

        self.assertEqual(outcome.inference, UNDERSTOOD)
        self.assertEqual([r["key"] for r in outcome.records], ["quiz"])
        self.assertEqual(store.progress, ["parsing", "extracting"])
        self.assertEqual(self.convert.await_args.args[0], "docling-client")
        (saved,) = store.saved_checkpoints
        self.assertEqual((saved.chunk_bytes, saved.chunk_count), (2048, 1))
        self.assertEqual(store.saved_chunks[0][:2], (0, saved.parse_id))
        self.assertEqual(store.permits, [("docling", 1), ("gpt", 2)])
        kwargs = self.extract.await_args.kwargs
        self.assertEqual((kwargs["model"], kwargs["module_title"]), ("model", "Intro Computing"))

    async def test_saved_parse_and_chunks_are_reused(self):
        store = DocumentStore()
        await self.process(store)
        parse = store.saved_checkpoints[0]
        records, uncertainties = store.saved_chunks[0][2:]
        resumed = DocumentStore(
            DocumentCheckpoint(
                parse.parse_id,
                parse.elements,
                {"0": {"records": records, "uncertainties": uncertainties}},
                parse.chunk_bytes,
                parse.chunk_count,
            )
        )
        self.convert.reset_mock()
        self.extract.reset_mock()

        outcome = await self.process(resumed)

        self.convert.assert_not_awaited()
        self.extract.assert_not_awaited()
        self.assertEqual(resumed.saved_checkpoints, [])
        self.assertEqual(resumed.saved_chunks, [])
        self.assertEqual(resumed.progress, ["parsing"])
        self.assertEqual([r["key"] for r in outcome.records], ["quiz"])

    async def test_invalid_extraction_is_retried_with_feedback(self):
        responses = []

        async def extract(client, *, chunk, feedback=None, **kwargs):
            responses.append(feedback)
            ids = {element.id for element in chunk}
            return extraction(ids, week=99 if feedback is None else 4)

        self.extract.side_effect = extract
        store = DocumentStore()
        outcome = await self.process(store)

        self.assertEqual(outcome.records[0]["week"], 4)
        self.assertIsNone(responses[0])
        self.assertIn("week", responses[1])
        ((stage, index, code, rejected),) = store.attempts
        self.assertEqual((stage, index, code), ("extracting", 0, errors.INVALID_EXTRACTION))
        self.assertEqual(rejected["assessments"][0]["week"], 99)

    async def test_failed_chunk_becomes_an_issue(self):
        self.extract.side_effect = lambda client, *, chunk, **kw: extraction(
            {e.id for e in chunk}, title="Another Module"
        )
        store = DocumentStore()
        outcome = await self.process(store)

        self.assertEqual(outcome.inference, UNKNOWN)
        (issue,) = outcome.issues
        self.assertEqual(issue["code"], errors.INVALID_EXTRACTION)
        self.assertEqual((issue["module_id"], issue["document_id"]), ("module-1", "doc-1"))
        self.assertEqual(store.saved_chunks, [])

    async def test_partial_success_keeps_accepted_chunks(self):
        parsed = {"texts": [{"text": f"Item {i} " + "x" * 300, "prov": []} for i in range(8)]}
        self.convert.return_value = parsed
        calls = 0

        async def extract(client, *, chunk, **kwargs):
            nonlocal calls
            calls += 1
            ids = {e.id for e in chunk}
            return extraction(ids, key=f"task{calls}") if calls == 1 else extraction(ids, title="Other")

        self.extract.side_effect = extract
        store = DocumentStore()
        outcome = await self.process(store)

        self.assertEqual(outcome.inference, PARTIALLY_UNDERSTOOD)
        self.assertEqual([r["key"] for r in outcome.records], ["task1"])
        self.assertTrue(outcome.issues)
        self.assertEqual([chunk[0] for chunk in store.saved_chunks], [0])

    async def test_document_without_assessments_reports_an_issue(self):
        self.extract.side_effect = lambda client, **kw: {
            "module_title": "Intro Computing",
            "assessments": [],
            "uncertainties": [],
        }
        outcome = await self.process(DocumentStore())
        self.assertEqual(outcome.inference, NO_ASSESSMENT_CONTENT)
        self.assertEqual(outcome.issues[0]["code"], errors.NO_ASSESSMENTS)

    async def test_parse_failures_and_interruptions_are_raised(self):
        self.convert.side_effect = ProcessingError(
            errors.DOCUMENT_PARSE_FAILED, "Could not parse.", "document", document_id="doc-1"
        )
        with self.assertRaises(ProcessingError) as raised:
            await self.process(DocumentStore())
        self.assertEqual(raised.exception.code, errors.DOCUMENT_PARSE_FAILED)

        self.convert.side_effect = None
        self.extract.side_effect = ProcessingError(
            errors.PROCESSING_INTERRUPTED, errors.INTERRUPTION_MESSAGE, "system"
        )
        with self.assertRaises(ProcessingError) as raised:
            await self.process(DocumentStore())
        self.assertEqual(raised.exception.code, errors.PROCESSING_INTERRUPTED)


if __name__ == "__main__":
    unittest.main()
