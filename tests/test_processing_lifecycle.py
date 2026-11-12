"""Tests for the project-processing lifecycle."""

import unittest

from src.models.processing.lifecycle import (
    CREATED,
    FAILED,
    INTERRUPTED,
    PROCESSING,
    READY,
    can_transition,
    transition_to,
)


class ProcessingLifecycleTests(unittest.TestCase):
    def test_created_project_can_start_processing(self):
        self.assertTrue(can_transition(CREATED, PROCESSING))
        self.assertEqual(transition_to(CREATED, PROCESSING), PROCESSING)

    def test_processing_can_reach_each_terminal_outcome(self):
        for status in (READY, FAILED, INTERRUPTED):
            with self.subTest(status=status):
                self.assertTrue(can_transition(PROCESSING, status))
                self.assertEqual(transition_to(PROCESSING, status), status)

    def test_rejects_skipped_and_terminal_transitions(self):
        for current, next_status in (
            (CREATED, READY),
            (READY, PROCESSING),
            (FAILED, PROCESSING),
            ("unknown", PROCESSING),
        ):
            with self.subTest(current=current, next_status=next_status):
                self.assertFalse(can_transition(current, next_status))
                with self.assertRaises(ValueError):
                    transition_to(current, next_status)


if __name__ == "__main__":
    unittest.main()
