"""Tests for running a processing step with bounded, recorded retries."""

import asyncio
from types import SimpleNamespace
import unittest

from src.errors import error_codes as errors
from src.errors.processing_error import ProcessingError
from src.processing.attempts import run_with_retries
from src.processing.retry_policy import RetryPolicy

TASK = SimpleNamespace(document=SimpleNamespace(id="doc-1"), generation=2)


class AttemptLog:
    def __init__(self):
        self.attempts = []

    def record_extraction_attempt(
        self, job, task, stage, index, attempt, code, message, status=None, rejected=None
    ):
        self.attempts.append((stage, index, attempt, code, message, status))


class HTTPFailure(Exception):
    def __init__(self, status, retry_after=None):
        super().__init__(f"HTTP {status} from https://provider.internal/secret")
        headers = {"Retry-After": retry_after} if retry_after is not None else {}
        self.response = SimpleNamespace(status_code=status, headers=headers)


def scripted(*outcomes):
    """Return an operation that raises or returns each outcome in turn."""
    calls = []

    async def operation(feedback):
        calls.append(feedback)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return operation, calls


class RunWithRetriesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = AttemptLog()
        self.delays = []

    async def sleep(self, seconds):
        self.delays.append(seconds)

    async def attempt(self, operation, policy=None):
        return await run_with_retries(
            self.log, "job-1", TASK, "extracting", 0, operation, policy, sleep=self.sleep
        )

    async def test_success_on_first_attempt_records_nothing(self):
        operation, calls = scripted("result")
        self.assertEqual(await self.attempt(operation), "result")
        self.assertEqual(calls, [None])
        self.assertEqual(self.log.attempts, [])
        self.assertEqual(self.delays, [])

    async def test_invalid_extraction_is_retried_once_with_feedback(self):
        invalid = ProcessingError(errors.INVALID_EXTRACTION, "Week 20 is out of range.", "module")
        operation, calls = scripted(invalid, "fixed")
        with self.assertLogs("src.processing.attempts", "WARNING"):
            self.assertEqual(await self.attempt(operation), "fixed")
        self.assertEqual(calls, [None, "Week 20 is out of range."])
        self.assertEqual(
            self.log.attempts,
            [("extracting", 0, 1, errors.INVALID_EXTRACTION, "Week 20 is out of range.", None)],
        )
        self.assertEqual(self.delays, [0.25])

    async def test_stops_when_the_policy_allows_no_more_attempts(self):
        invalid = ProcessingError(errors.INVALID_EXTRACTION, "Still invalid.", "module")
        operation, calls = scripted(invalid, invalid, "never")
        with self.assertLogs("src.processing.attempts", "WARNING"):
            with self.assertRaises(ProcessingError) as raised:
                await self.attempt(operation)
        self.assertIs(raised.exception, invalid)
        self.assertEqual(len(calls), 2)
        self.assertEqual([a[2] for a in self.log.attempts], [1, 2])

    async def test_transient_http_failures_use_status_and_retry_after(self):
        operation, calls = scripted(HTTPFailure(503, "4"), HTTPFailure(429), "ok")
        with self.assertLogs("src.processing.attempts", "WARNING"):
            self.assertEqual(await self.attempt(operation), "ok")
        self.assertEqual([a[5] for a in self.log.attempts], [503, 429])
        self.assertEqual(self.delays, [4.0, 0.5])
        self.assertTrue(all(a[3] == errors.PROVIDER_UNAVAILABLE for a in self.log.attempts))

    async def test_non_retryable_status_fails_without_leaking_details(self):
        operation, calls = scripted(HTTPFailure(404), "never")
        with self.assertLogs("src.processing.attempts", "WARNING") as logs:
            with self.assertRaises(ProcessingError) as raised:
                await self.attempt(operation)
        self.assertEqual(raised.exception.code, errors.PROVIDER_UNAVAILABLE)
        self.assertEqual(len(calls), 1)
        exposed = raised.exception.message + self.log.attempts[0][4] + "".join(logs.output)
        self.assertNotIn("secret", exposed)

    async def test_interruption_stops_without_recording(self):
        interrupted = ProcessingError(
            errors.PROCESSING_INTERRUPTED, errors.INTERRUPTION_MESSAGE, "system"
        )
        operation, calls = scripted(interrupted, "never")
        with self.assertRaises(ProcessingError) as raised:
            await self.attempt(operation)
        self.assertIs(raised.exception, interrupted)
        self.assertEqual(self.log.attempts, [])

    async def test_cancellation_is_not_retried(self):
        operation, calls = scripted(asyncio.CancelledError(), "never")
        with self.assertRaises(asyncio.CancelledError):
            await self.attempt(operation)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.log.attempts, [])

    async def test_custom_policy_limits_attempts(self):
        operation, calls = scripted(HTTPFailure(500), HTTPFailure(500), "never")
        with self.assertLogs("src.processing.attempts", "WARNING"):
            with self.assertRaises(ProcessingError):
                await self.attempt(operation, RetryPolicy(transient_attempts=2))
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
