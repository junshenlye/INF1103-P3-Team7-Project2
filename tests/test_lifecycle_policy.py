"""Tests for settled outcome, retry and coverage rules."""

import unittest

from src.models.processing import (
    CREATED,
    FAILED,
    INTERRUPTED,
    PARTIAL,
    PROCESSING,
    READY,
    LifecyclePolicy,
)


def task(state="succeeded", inference="understood", issues=()):
    return {"state": state, "inference": inference, "issues": list(issues)}


def document(execution="succeeded", inference="understood", issues=()):
    return {"execution": execution, "inference": inference, "issues": list(issues)}


class SettledStatusTests(unittest.TestCase):
    def test_ready_when_every_module_is_available_and_resolved(self):
        self.assertEqual(LifecyclePolicy.settled_status(2, 2, [task(), task()]), READY)

    def test_partial_when_some_results_exist_but_work_is_unresolved(self):
        cases = {
            "missing module": (2, 1, [task()], {}),
            "failed task": (1, 1, [task(state="failed")], {}),
            "uncertain inference": (1, 1, [task(inference="unclear")], {}),
            "task issues": (1, 1, [task(issues=["x"])], {}),
            "job errors": (1, 1, [task()], {"has_errors": True}),
            "stale result": (1, 1, [task()], {"stale": True}),
        }
        for name, (modules, available, tasks, flags) in cases.items():
            with self.subTest(name):
                self.assertEqual(
                    LifecyclePolicy.settled_status(modules, available, tasks, **flags),
                    PARTIAL,
                )

    def test_failed_when_no_module_result_is_available(self):
        self.assertEqual(LifecyclePolicy.settled_status(2, 0, [task(state="failed")]), FAILED)
        self.assertEqual(LifecyclePolicy.settled_status(0, 0, []), FAILED)


class RetryTests(unittest.TestCase):
    def test_settled_jobs_allow_retrying_queued_or_failed_tasks(self):
        for status in (READY, PARTIAL, FAILED, INTERRUPTED):
            for state in ("queued", "failed"):
                with self.subTest(status=status, state=state):
                    self.assertTrue(LifecyclePolicy.can_retry(status, state, []))

    def test_succeeded_task_is_retryable_only_with_issues(self):
        self.assertTrue(LifecyclePolicy.can_retry(PARTIAL, "succeeded", ["x"]))
        self.assertFalse(LifecyclePolicy.can_retry(PARTIAL, "succeeded", []))

    def test_rejects_unsettled_jobs_running_tasks_and_replaced_documents(self):
        self.assertFalse(LifecyclePolicy.can_retry(CREATED, "failed", []))
        self.assertFalse(LifecyclePolicy.can_retry(PROCESSING, "failed", []))
        self.assertFalse(LifecyclePolicy.can_retry(PARTIAL, "running", []))
        self.assertFalse(LifecyclePolicy.can_retry(FAILED, "failed", [], replaced=True))


class CoverageTests(unittest.TestCase):
    def test_complete_only_for_fresh_ready_results_with_resolved_documents(self):
        self.assertEqual(LifecyclePolicy.coverage(READY, True, [document()]), "complete")
        self.assertEqual(
            LifecyclePolicy.coverage(READY, True, [document()], stale=True), "partial"
        )
        self.assertEqual(
            LifecyclePolicy.coverage(READY, True, [document(issues=["x"])]), "partial"
        )
        self.assertEqual(LifecyclePolicy.coverage(PARTIAL, True, [document()]), "partial")

    def test_none_without_assessments_unless_complete(self):
        self.assertEqual(
            LifecyclePolicy.coverage(FAILED, False, [document(execution="failed")]), "none"
        )
        self.assertEqual(LifecyclePolicy.coverage(READY, False, []), "complete")


if __name__ == "__main__":
    unittest.main()
