"""Verify PostgreSQL module checkpoints use one consistent review-aware snapshot."""

from contextlib import nullcontext
import hashlib
import unittest
from unittest.mock import Mock

from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.managers.data_manager import DataManager
from src.models.processing.checkpoint import ModuleCheckpoint


def cursor(*, one=None, many=None):
    result = Mock()
    result.fetchone.return_value = one
    result.fetchall.return_value = many or []
    return result


class PostgresModuleCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.connection.transaction.return_value = nullcontext()
        pool = Mock()
        pool.connection.return_value = nullcontext(self.connection)
        self.manager = DataManager(pool)

    def test_loads_current_chunks_and_reviewed_assessments_from_one_snapshot(self):
        chunks = [
            {
                "records": [
                    {"key": "quiz", "name": "Quiz", "evidence": {"week": ["source-new"]}}
                ],
                "uncertainties": ["Weight is unknown."],
            },
            {
                "records": [
                    {"key": "exam", "name": "Exam", "evidence": {"week": ["source-exam"]}}
                ],
                "uncertainties": ["Week is unknown.", "Weight is unknown."],
            },
        ]
        manifest = hashlib.sha256(repr(chunks).encode("utf-8")).hexdigest()
        original_facts = {"key": "quiz", "week": 12, "weight_percent": 60}
        reviewed_facts = {"key": "quiz", "week": 10, "weight_percent": 60}
        assessment = {
            "id": "assessment-1",
            "result_id": "result-1",
            "module_id": "module-1",
            "parent_assessment_id": None,
            "original_facts": original_facts,
            "facts": reviewed_facts,
            "revision": 2,
            "review_revision_id": "review-1",
        }
        original_evidence = {
            "assessment_id": "assessment-1",
            "field": "week",
            "source_element_id": "source-original",
        }
        reviewed_evidence = {
            "review_id": "review-1",
            "field": "week",
            "source_element_id": "source-reviewed",
        }

        def execute(sql, params=()):
            if "SET TRANSACTION" in sql:
                return cursor()
            if "SELECT id FROM stackplan.modules" in sql:
                self.assertEqual(params, ("module-1", "job-1"))
                return cursor(one={"id": "module-1"})
            if "DISTINCT ON (chunk.document_id, chunk.chunk_index)" in sql:
                self.assertIn("chunk.generation >= task.minimum_generation", sql)
                self.assertIn("replacement.old_document_id = document.id", sql)
                self.assertIn("ORDER BY chunk.document_id, chunk.chunk_index, chunk.generation DESC", sql)
                return cursor(many=chunks)
            if "SELECT source.id::text AS id" in sql:
                self.assertIn("replacement.old_document_id = document.id", sql)
                return cursor(many=[
                    {"id": "source-new"},
                    {"id": "source-exam"},
                    {"id": "source-original"},
                    {"id": "source-reviewed"},
                ])
            if "FROM stackplan.module_result_heads" in sql:
                return cursor(one={"result_id": "result-1", "manifest": manifest})
            if "LEFT JOIN LATERAL" in sql:
                self.assertIn("ORDER BY revision DESC", sql)
                return cursor(many=[assessment])
            if "FROM stackplan.assessment_evidence" in sql:
                self.assertIn("assessment_id = ANY(%s::uuid[])", sql)
                return cursor(many=[original_evidence])
            if "FROM stackplan.review_evidence" in sql:
                self.assertIn("review_id = ANY(%s::uuid[])", sql)
                return cursor(many=[reviewed_evidence])
            self.fail(f"Unexpected SQL: {sql}")

        self.connection.execute.side_effect = execute
        saved = self.manager.get_module_checkpoint("job-1", "module-1")

        self.assertIsInstance(saved, ModuleCheckpoint)
        self.assertEqual(
            tuple(record["key"] for record in saved.records), ("quiz", "exam")
        )
        self.assertEqual(
            saved.uncertainties, ("Week is unknown.", "Weight is unknown.")
        )
        self.assertEqual(
            saved.source_ids,
            frozenset({"source-new", "source-exam", "source-original", "source-reviewed"}),
        )
        self.assertEqual(saved.manifest, manifest)
        self.assertTrue(saved.unchanged)
        self.assertEqual(saved.previous_assessments[0]["facts"], reviewed_facts)
        self.assertEqual(saved.previous_assessments[0]["original_facts"], original_facts)
        self.assertEqual(
            saved.previous_assessments[0]["evidence"]["week"],
            ("source-reviewed",),
        )
        self.assertEqual(
            saved.previous_assessments[0]["original_evidence"]["week"],
            ("source-original",),
        )
        self.assertEqual(dict(saved.previous_versions), {"assessment-1": 2})
        self.connection.transaction.assert_called_once_with()
        self.assertIn(
            "REPEATABLE READ READ ONLY",
            self.connection.execute.call_args_list[0].args[0],
        )

    def test_unreviewed_assessments_keep_original_evidence_and_zero_revision(self):
        original = {
            "id": "assessment-2",
            "result_id": "result-2",
            "module_id": "module-1",
            "parent_assessment_id": None,
            "original_facts": {"key": "exam"},
            "facts": {"key": "exam"},
            "revision": 0,
            "review_revision_id": None,
        }
        calls = 0

        def execute(sql, params=()):
            nonlocal calls
            calls += 1
            if calls == 1:
                return cursor()
            if calls == 2:
                return cursor(one={"id": "module-1"})
            if calls == 3:
                return cursor(many=[])
            if calls == 4:
                return cursor(many=[{"id": "source-1"}])
            if calls == 5:
                return cursor(one={"result_id": "result-2", "manifest": "old"})
            if calls == 6:
                return cursor(many=[original])
            if calls == 7:
                return cursor(many=[
                    {"assessment_id": "assessment-2", "field": "name", "source_element_id": "source-1"}
                ])
            self.fail(f"Unexpected SQL call {calls}: {sql}")

        self.connection.execute.side_effect = execute
        saved = self.manager.get_module_checkpoint("job-1", "module-1")

        self.assertFalse(saved.unchanged)
        self.assertEqual(saved.records, ())
        self.assertEqual(saved.previous_versions["assessment-2"], 0)
        self.assertEqual(
            saved.previous_assessments[0]["evidence"]["name"],
            ("source-1",),
        )
        self.assertEqual(
            saved.previous_assessments[0]["original_evidence"]["name"],
            ("source-1",),
        )

    def test_rejects_a_module_that_does_not_belong_to_the_job(self):
        self.connection.execute.side_effect = [
            cursor(),
            cursor(one=None),
        ]

        with self.assertRaises(ProcessingError) as raised:
            self.manager.get_module_checkpoint("job-1", "other-module")

        self.assertEqual(raised.exception.code, error_codes.NOT_FOUND)
        self.assertEqual(self.connection.execute.call_count, 2)


if __name__ == "__main__":
    unittest.main()
