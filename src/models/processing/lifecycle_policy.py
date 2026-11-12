"""Outcome, retry and coverage rules shared by readers and write commands.

The policy only inspects plain values, so the HTTP layer, the worker and
persistence code can apply the same decisions without sharing state.
"""

from __future__ import annotations

from src.models.processing.lifecycle import FAILED, INTERRUPTED, PARTIAL, READY

RETRYABLE_JOB_STATES = frozenset({READY, PARTIAL, FAILED, INTERRUPTED})
RETRYABLE_TASK_STATES = frozenset({"queued", "failed"})
SUCCEEDED = "succeeded"
UNDERSTOOD = "understood"


def _resolved(execution, inference, issues):
    return execution == SUCCEEDED and inference == UNDERSTOOD and not issues


class LifecyclePolicy:
    """Pure decisions about settled project outcomes."""

    @staticmethod
    def can_retry(job_status, task_state, issues, replaced=False):
        """Return whether a document task may be retried.

        Only settled jobs allow retries. A task is retryable while it is queued
        or failed, or when it succeeded but still reported issues. A document
        that has been replaced is never retried.
        """
        return (
            not replaced
            and job_status in RETRYABLE_JOB_STATES
            and (
                task_state in RETRYABLE_TASK_STATES
                or (task_state == SUCCEEDED and bool(issues))
            )
        )

    @staticmethod
    def settled_status(module_count, available, tasks, has_errors=False, stale=False):
        """Return ``Ready``, ``Partial`` or ``Failed`` for a settled job.

        ``available`` is the number of modules with a published result. The
        job is Ready only when every module is available and nothing is
        unresolved; any published result otherwise makes it Partial.
        """
        unresolved = has_errors or stale or any(
            not _resolved(task["state"], task["inference"], task["issues"])
            for task in tasks
        )
        if module_count and available == module_count and not unresolved:
            return READY
        return PARTIAL if available else FAILED

    @staticmethod
    def coverage(status, has_assessments, documents, stale=False):
        """Return ``complete``, ``partial`` or ``none`` for a schedule."""
        complete = (
            status == READY
            and not stale
            and all(
                _resolved(d["execution"], d["inference"], d["issues"])
                for d in documents
            )
        )
        if complete:
            return "complete"
        return "partial" if has_assessments else "none"
