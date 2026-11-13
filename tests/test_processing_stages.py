"""Tests for the processing job status and stage vocabulary."""

import unittest

from src.models.processing import lifecycle


class ProcessingStageTests(unittest.TestCase):
    def test_stage_values_match_stored_vocabulary(self):
        self.assertEqual(
            (
                lifecycle.QUEUED,
                lifecycle.RUNNING,
                lifecycle.PARSING,
                lifecycle.EXTRACTING,
                lifecycle.VALIDATING,
                lifecycle.EXTRACTED,
            ),
            ("queued", "running", "parsing", "extracting", "validating", "extracted"),
        )

    def test_every_terminal_status_has_a_stage(self):
        self.assertEqual(set(lifecycle.TERMINAL_STAGES), set(lifecycle.TERMINAL_STATES))
        self.assertEqual(lifecycle.terminal_stage(lifecycle.READY), "complete")
        self.assertEqual(lifecycle.terminal_stage(lifecycle.PARTIAL), "complete")
        self.assertEqual(lifecycle.terminal_stage(lifecycle.FAILED), "failed")
        self.assertEqual(lifecycle.terminal_stage(lifecycle.INTERRUPTED), "interrupted")

    def test_non_terminal_statuses_have_no_terminal_stage(self):
        for status in (lifecycle.CREATED, lifecycle.PROCESSING, lifecycle.QUEUED, lifecycle.RUNNING, "unknown"):
            with self.subTest(status=status):
                with self.assertRaises(ValueError):
                    lifecycle.terminal_stage(status)

    def test_job_stages_cover_active_and_terminal_stages(self):
        self.assertEqual(
            lifecycle.JOB_STAGES,
            {"queued", "parsing", "extracting", "validating", "complete", "failed", "interrupted"},
        )

    def test_terminal_stage_mapping_is_read_only(self):
        with self.assertRaises(TypeError):
            lifecycle.TERMINAL_STAGES[lifecycle.READY] = "failed"


if __name__ == "__main__":
    unittest.main()
