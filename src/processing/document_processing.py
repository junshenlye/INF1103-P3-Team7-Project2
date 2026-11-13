"""Parse one document and extract assessment facts from each of its chunks."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from typing import Mapping
from uuid import uuid4

from src.errors import error_codes as errors
from src.errors.issues import issue_from_error, make_issue
from src.errors.processing_error import ProcessingError
from src.models.processing import lifecycle
from src.models.processing.checkpoint import DocumentCheckpoint
from src.models.processing.document_task import DocumentOutcome
from src.processing.assessment_extraction import extract_assessment_chunk
from src.processing.attempts import run_with_retries
from src.processing.document_conversion import convert_document
from src.processing.provider_permit import provider_permit
from src.processing.source_reader import SourceReader

NO_ASSESSMENTS_MESSAGE = (
    "No assessment information could be inferred. Inspect the original document."
)


def _thaw(value):
    """Return plain dicts and lists for the frozen data a checkpoint holds."""
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


async def process_document_task(
    *,
    data,
    logic,
    docling,
    gpt,
    settings,
    job,
    task,
    module,
    week_count: int,
    policy=None,
    sleep=asyncio.sleep,
) -> DocumentOutcome:
    """Parse ``task``'s document, extract every chunk and return the outcome.

    A saved parse is reused instead of calling the parser again, and chunks
    already accepted for that parse are not extracted again, so a retried
    document only repeats unfinished work. Each provider call holds a
    provider permit, is bounded by ``settings.provider_timeout`` and runs
    under the retry policy. A chunk that still fails is reported as an
    issue while the remaining chunks continue. A parse failure, or an
    interruption, is raised for the caller to settle the task.
    """
    document = task.document
    saved = await asyncio.to_thread(data.get_document_checkpoint, document.id)
    await asyncio.to_thread(data.save_document_progress, job, document.id, lifecycle.PARSING)

    if saved.parse_id:
        parse_id = saved.parse_id
        elements = [replace(e, regions=_thaw(e.regions)) for e in saved.elements]
        reader = SourceReader(
            SimpleNamespace(
                chunk_bytes=saved.chunk_bytes,
                max_chunks=max(settings.max_chunks, saved.chunk_count),
            )
        )
        chunks = reader.make_chunks(elements)
    else:

        async def parse(_feedback):
            async with provider_permit(data, job, "docling", 1):
                with data.open_document(document.id) as stream:
                    return await asyncio.wait_for(
                        convert_document(docling, stream, document), settings.provider_timeout
                    )

        parsed = await run_with_retries(data, job, task, "parsing", None, parse, policy, sleep)
        parse_id = str(uuid4())
        reader = SourceReader(settings)
        elements = reader.read_elements(parsed, document.id, parse_id)
        chunks = reader.make_chunks(elements)
        await asyncio.to_thread(
            data.save_document_checkpoint,
            job,
            document.id,
            DocumentCheckpoint(parse_id, elements, {}, settings.chunk_bytes, len(chunks)),
        )

    done = {int(index): _thaw(chunk) for index, chunk in saved.chunks.items()} if saved.parse_id else {}
    accepted = [done[index] for index in sorted(done)]
    issues = []
    for index, chunk in enumerate(chunks):
        if index in done:
            continue
        await asyncio.to_thread(
            data.save_document_progress, job, document.id, lifecycle.EXTRACTING
        )
        source_ids = {element.id for element in chunk}

        async def extract(feedback, chunk=chunk, source_ids=source_ids):
            async with provider_permit(data, job, "gpt", settings.gpt_concurrency):
                raw = await asyncio.wait_for(
                    extract_assessment_chunk(
                        gpt,
                        model=settings.gpt_model,
                        api_key=settings.gpt_api_key,
                        module_title=module.module_title,
                        chunk=chunk,
                        feedback=feedback,
                    ),
                    settings.provider_timeout,
                )
            try:
                return logic.validate_extraction(raw, module, source_ids, week_count)
            except ProcessingError as error:
                error.rejected = raw
                raise

        try:
            records, uncertainties = await run_with_retries(
                data, job, task, "extracting", index, extract, policy, sleep
            )
        except ProcessingError as error:
            if error.code == errors.PROCESSING_INTERRUPTED:
                raise
            issues.append(issue_from_error(error, module_id=module.id, document_id=document.id))
            continue
        await asyncio.to_thread(
            data.save_document_chunk, job, task, index, parse_id, records, uncertainties
        )
        accepted.append({"records": records, "uncertainties": uncertainties})

    outcome = DocumentOutcome.from_chunks(accepted, issues)
    if not outcome.records and not issues:
        issue = make_issue(
            errors.NO_ASSESSMENTS,
            NO_ASSESSMENTS_MESSAGE,
            "document",
            module_id=module.id,
            document_id=document.id,
        )
        outcome = DocumentOutcome(outcome.inference, issues=(issue,))
    return outcome
