"""Verify saving a document's parse checkpoint in PostgreSQL."""

from contextlib import nullcontext
import json
import unittest
from unittest.mock import Mock

from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.models.documents.source_element import SourceElement
from src.models.processing.checkpoint import DocumentCheckpoint
from src.models.processing.processing_job import ProcessingJob
from src.storage.postgres_document_checkpoints import PARSER_VERSION, PostgresDocumentCheckpoints

JOB = ProcessingJob("job", "project", "submission", "running", "parsing", "lease")


def element(index, document="doc", parse="parse"):
    return SourceElement(
        id=f"element-{index}",
        document_id=document,
        parse_id=parse,
        text=f"Quiz {index} 学习",
        regions=[{"page": 1, "bbox": [0.1, 0.2, 0.3, 0.4], "coordinate_origin": "TOPLEFT"}],
        context="Assessment",
    )


def checkpoint(*elements, parse="parse", chunk_count=2):
    return DocumentCheckpoint(parse, elements or (element(0), element(1)), {}, 4096, chunk_count)


class SaveDocumentCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.connection.transaction.return_value = nullcontext()
        pool = Mock()
        pool.connection.return_value = nullcontext(self.connection)
        self.store = PostgresDocumentCheckpoints(pool)
        self.results = []

        def execute(sql, params=()):
            row = self.results.pop(0) if self.results else None
            return Mock(fetchone=Mock(return_value=row))

        self.connection.execute.side_effect = execute

    def save(self, saved_checkpoint=None, lease=True, owned=True, existing=None):
        self.results = [
            {"id": "job"} if lease else None,
            {"parse_id": existing} if owned else None,
        ]
        self.store.save_document_checkpoint(JOB, "doc", saved_checkpoint or checkpoint())

    def statements(self):
        return [call.args for call in self.connection.execute.call_args_list]

    def test_saves_the_parse_and_its_elements_in_order(self):
        self.save()

        (lease_sql, lease_params), (owner_sql, owner_params), (parse_sql, parse_params), *elements = (
            self.statements()
        )
        self.assertIn("lease_token = %s", lease_sql)
        self.assertIn("FOR UPDATE", lease_sql)
        self.assertEqual(lease_params, ("job", "running", "lease"))
        self.assertIn("module.job_id = %s", owner_sql)
        self.assertEqual(owner_params, ("doc", "job"))
        self.assertIn("INSERT INTO stackplan.parse_snapshots", parse_sql)
        self.assertEqual(parse_params, ("parse", "doc", PARSER_VERSION, 2, 4096))
        self.assertEqual([params[6] for _, params in elements], [0, 1])
        self.assertEqual([params[0] for _, params in elements], ["element-0", "element-1"])
        sql, params = elements[0]
        self.assertIn("%s::jsonb", sql)
        self.assertEqual(params[3], "Quiz 0 学习")
        self.assertEqual(
            json.loads(params[4]),
            [{"page": 1, "bbox": [0.1, 0.2, 0.3, 0.4], "coordinate_origin": "TOPLEFT"}],
        )
        self.connection.transaction.assert_called_once_with()

    def test_saving_the_same_parse_again_changes_nothing(self):
        self.save(existing="parse")
        self.assertEqual(len(self.statements()), 2)

    def test_a_different_parse_for_the_document_is_rejected(self):
        with self.assertRaises(ProcessingError) as raised:
            self.save(existing="older-parse")
        self.assertEqual(raised.exception.code, error_codes.INVALID_REQUEST)
        self.assertEqual(len(self.statements()), 2)

    def test_lost_lease_interrupts_before_any_write(self):
        with self.assertRaises(ProcessingError) as raised:
            self.save(lease=False)
        self.assertEqual(raised.exception.code, error_codes.PROCESSING_INTERRUPTED)
        self.assertEqual(len(self.statements()), 1)

    def test_document_outside_the_job_is_rejected(self):
        with self.assertRaises(ProcessingError) as raised:
            self.save(owned=False)
        self.assertEqual(raised.exception.code, error_codes.INVALID_REQUEST)
        self.assertEqual(raised.exception.related_ids, {"document_id": "doc"})
        self.assertEqual(len(self.statements()), 2)

    def test_incomplete_or_mismatched_checkpoints_are_rejected_before_connecting(self):
        cases = {
            "no parse": DocumentCheckpoint(None, (element(0),), {}, 4096, 1),
            "no elements": DocumentCheckpoint("parse", (), {}, 4096, 1),
            "no chunks": checkpoint(chunk_count=0),
            "other document": checkpoint(element(0, document="other")),
            "other parse": checkpoint(element(0, parse="other")),
        }
        for name, invalid in cases.items():
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    self.store.save_document_checkpoint(JOB, "doc", invalid)
        self.connection.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
