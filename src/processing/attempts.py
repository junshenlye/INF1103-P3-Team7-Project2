"""Run one parse or extraction step with bounded, recorded retries."""

from __future__ import annotations

import asyncio
import logging

from src.errors import error_codes as errors
from src.errors.processing_error import safe_processing_error
from src.processing.retry_policy import RetryPolicy

logger = logging.getLogger(__name__)


def _http_details(error):
    """Return the HTTP status and Retry-After header carried by a transport error."""
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if type(status) is not int:
        return None, None
    headers = getattr(response, "headers", None) or {}
    return status, headers.get("Retry-After")


async def run_with_retries(
    data,
    job,
    task,
    stage: str,
    index: int | None,
    operation,
    policy: RetryPolicy | None = None,
    sleep=asyncio.sleep,
):
    """Await ``operation(feedback)`` until it succeeds or the policy stops retrying.

    ``feedback`` is None on the first attempt and afterwards the safe message
    of the previous failure, so an extraction can be corrected. Every failure
    is recorded with ``data.record_extraction_attempt``. Unexpected exceptions
    are replaced with a safe ``ProcessingError`` before they are recorded or
    raised. Cancellation and ``processing_interrupted`` stop immediately
    without another attempt.

    Raises:
        ProcessingError: The last failure once the policy allows no retry.
    """
    policy = policy or RetryPolicy()
    feedback = None
    attempt = 0
    while True:
        attempt += 1
        try:
            return await operation(feedback)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            failure = safe_processing_error(error)
            if failure.code == errors.PROCESSING_INTERRUPTED:
                raise failure from error
            status, retry_after = _http_details(error)
            logger.warning(
                "Document %s generation %s stage %s attempt %s: %s (%s)",
                task.document.id,
                task.generation,
                stage,
                attempt,
                failure.message,
                status or failure.code,
            )
            await asyncio.to_thread(
                data.record_extraction_attempt,
                job,
                task,
                stage,
                index,
                attempt,
                failure.code,
                failure.message,
                status,
                getattr(failure, "rejected", None),
            )
            if not policy.allows(attempt, failure.code, status):
                raise failure from error
            feedback = failure.message
            await sleep(policy.delay(attempt, retry_after))
