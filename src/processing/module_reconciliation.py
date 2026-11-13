"""Publish one module result from its saved extraction candidates."""

from __future__ import annotations

import asyncio
from typing import Mapping
from uuid import uuid4

from src.errors import error_codes as errors
from src.errors.processing_error import ProcessingError
from src.models.assessments.assessment import Assessment
from src.models.processing.extraction_result import ExtractionResult

PIPELINE = "document-queue-v1"
PUBLICATION_ATTEMPTS = 3


def _thaw(value):
    """Return plain dicts and lists for the frozen data a checkpoint holds."""
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


async def reconcile_module(data, logic, job, module, week_count: int, attempts: int = PUBLICATION_ATTEMPTS):
    """Merge a module's saved records, carry reviews forward and publish the result.

    ``data`` provides ``get_module_checkpoint`` and ``save_extraction_result``
    from the worker data contract, and ``logic`` is the ``LogicManager``.
    Nothing is published when the checkpoint is unchanged or has no records.

    A reviewer can save a correction while extraction is still running. The
    store then rejects publication with ``revision_conflict``; the checkpoint
    is read again and publication retried, up to ``attempts`` times.

    Returns:
        The published ``ExtractionResult``, or None when nothing changed.

    Raises:
        ProcessingError: When the records are invalid, a review cannot be
            carried forward, or every publication attempt conflicts.
    """
    if attempts < 1:
        raise ValueError("At least one publication attempt is required.")
    for attempt in range(1, attempts + 1):
        saved = await asyncio.to_thread(data.get_module_checkpoint, job.id, module.id)
        if saved.unchanged or not saved.records:
            return None
        merged = logic.merge_assessments(_thaw(saved.records), validate_relationships=False)
        transfers = logic.reconcile_reviews(
            merged, _thaw(saved.previous_assessments), saved.source_ids, week_count
        )
        result_id = str(uuid4())
        ids = {record["key"]: str(uuid4()) for record in merged}
        assessments = []
        for record in merged:
            logic.validate_source_references(record, saved.source_ids)
            facts = {key: value for key, value in record.items() if key != "evidence"}
            assessments.append(
                Assessment.create(
                    ids[record["key"]],
                    result_id,
                    module.id,
                    facts,
                    record["evidence"],
                    ids.get(record["parent_key"]),
                )
            )
        result = ExtractionResult(
            result_id,
            job.id,
            module.id,
            tuple(assessment.id for assessment in assessments),
            tuple(saved.uncertainties),
            {"pipeline": PIPELINE},
        )
        try:
            await asyncio.to_thread(
                data.save_extraction_result,
                job,
                result,
                assessments,
                saved.manifest,
                saved.previous_versions,
                transfers,
            )
            return result
        except ProcessingError as error:
            if error.code != errors.REVISION_CONFLICT or attempt == attempts:
                raise
