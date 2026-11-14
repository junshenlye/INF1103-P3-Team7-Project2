"""Verify publishing module results in PostgreSQL."""

from contextlib import nullcontext
import json
import unittest
from unittest.mock import Mock

from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.models.assessments.assessment import Assessment
from src.models.processing.extraction_result import ExtractionResult
from src.models.processing.processing_job import ProcessingJob
from src.models.processing.review_transfer import ReviewTransfer
from src.storage.postgres_extraction_results import PostgresExtractionResults

JOB = ProcessingJob("job", "project", "submission", "running", "validating", "lease")


def facts(key, **changes):
    return {
        "key": key, "name": key.title(), "kind": "assessment", "weight_percent": None,
        "weight_scope": "unknown", "week": 3, "end_week": None, "parent_key": None, **changes,
    }


QUIZ = Assessment.create("a-quiz", "result", "module", facts("quiz"), {"name": ["s1"], "week": ["s1", "s2"]})
EXAM = Assessment.create("a-exam", "result", "module", facts("exam"), {"name": ["s2"]})
RESULT = ExtractionResult("result", "job", "module", ("a-quiz", "a-exam"), ("Exam: weight unknown.",), {"pipeline": "test"})


class FakeConnection:
    """Answer each query by matching its SQL text, and record every statement."""

    def __init__(self, answers):
        self.answers = answers
        self.statements = []

    def transaction(self):
        return nullcontext()

    def execute(self, sql, params=()):
        self.statements.append((" ".join(sql.split()), params))
        for fragment, answer in self.answers.items():
            if fragment in sql:
                value = answer(params) if callable(answer) else answer
                return Mock(fetchone=Mock(return_value=value), fetchall=Mock(return_value=value))
        return Mock(fetchone=Mock(return_value=None), fetchall=Mock(return_value=[]))

    def matching(self, fragment):
        return [params for sql, params in self.statements if fragment in sql]


class PostgresExtractionResultTests(unittest.TestCase):
    def publish(self, answers=None, assessments=(QUIZ, EXAM), result=RESULT, **kwargs):
        base = {
            "lease_expires_at > clock_timestamp()": {"id": "job"},
            "FROM stackplan.module_result_heads WHERE module_id": None,
            "SELECT count(*) AS count FROM stackplan.source_elements": lambda params: {"count": len(params[0])},
            "INSERT INTO stackplan.schedule_revisions": {"id": 7},
            "FROM stackplan.document_tasks AS task": [],
        }
        self.connection = FakeConnection({**base, **(answers or {})})
        pool = Mock()
        pool.connection.return_value = nullcontext(self.connection)
        return PostgresExtractionResults(pool).save_extraction_result(JOB, result, list(assessments), **kwargs)

    def test_publishes_the_result_assessments_evidence_and_head(self):
        revision = self.publish(manifest="manifest-1", previous_versions={})

        self.assertEqual(revision, 7)
        ((result_id, job, module, uncertainties, metrics),) = self.connection.matching("INSERT INTO stackplan.extraction_results")
        self.assertEqual((result_id, job, module), ("result", "job", "module"))
        self.assertEqual(json.loads(uncertainties), ["Exam: weight unknown."])
        self.assertEqual(json.loads(metrics), {"pipeline": "test"})
        stored = self.connection.matching("INSERT INTO stackplan.assessments")
        self.assertEqual([row[0] for row in stored], ["a-quiz", "a-exam"])
        self.assertEqual(json.loads(stored[0][4])["key"], "quiz")
        self.assertEqual(
            sorted(self.connection.matching("INSERT INTO stackplan.assessment_evidence")),
            [("a-exam", "name", "s2"), ("a-quiz", "name", "s1"), ("a-quiz", "week", "s1"), ("a-quiz", "week", "s2")],
        )
        self.assertEqual(self.connection.matching("SET published = true"), [("result",)])
        self.assertEqual(self.connection.matching("INSERT INTO stackplan.module_result_heads"), [("module", "result", "manifest-1")])
        self.assertEqual(self.connection.matching("SET resolved = true"), [("job", "module")])
        self.assertEqual(self.connection.matching("INSERT INTO stackplan.schedule_revisions")[0][0], "project")

    def test_review_transfers_are_stored_with_lineage(self):
        transfer = ReviewTransfer("quiz", "old-quiz", 2, facts("quiz", week=4), {"week": ["s2"]})
        self.publish(review_transfers=(transfer,))
        ((review_id, result, assessment, module, revision, reviewed),) = self.connection.matching("INSERT INTO stackplan.review_revisions")
        self.assertEqual((result, assessment, module, revision), ("result", "a-quiz", "module", 2))
        self.assertEqual(json.loads(reviewed)["week"], 4)
        self.assertEqual(self.connection.matching("INSERT INTO stackplan.review_evidence"), [(review_id, "week", "s2")])
        self.assertEqual(self.connection.matching("assessment_review_lineage"), [("a-quiz", "old-quiz")])

    def test_changed_review_versions_are_a_conflict(self):
        answers = {
            "FROM stackplan.module_result_heads WHERE module_id": {"result_id": "old-result"},
            "COALESCE(max(review.revision), 0)": [{"id": "old-quiz", "revision": 2}],
        }
        self.publish(answers, previous_versions={"old-quiz": 2})
        with self.assertRaises(ProcessingError) as raised:
            self.publish(answers, previous_versions={"old-quiz": 1})
        self.assertEqual(raised.exception.code, error_codes.REVISION_CONFLICT)
        self.assertEqual(self.connection.matching("INSERT INTO stackplan.extraction_results"), [])

    def test_versions_are_not_checked_when_none_were_read(self):
        answers = {"FROM stackplan.module_result_heads WHERE module_id": {"result_id": "old-result"}}
        self.publish(answers, previous_versions=None)
        self.assertEqual(self.connection.matching("COALESCE(max(review.revision), 0)"), [])

    def test_evidence_from_another_module_is_rejected(self):
        with self.assertRaises(ProcessingError) as raised:
            self.publish({"SELECT count(*) AS count FROM stackplan.source_elements": {"count": 1}})
        self.assertEqual(raised.exception.code, error_codes.INVALID_EXTRACTION)
        self.assertEqual(self.connection.matching("INSERT INTO stackplan.extraction_results"), [])

    def test_lost_lease_writes_nothing(self):
        with self.assertRaises(ProcessingError) as raised:
            self.publish({"lease_expires_at > clock_timestamp()": None})
        self.assertEqual(raised.exception.code, error_codes.PROCESSING_INTERRUPTED)
        self.assertEqual(len(self.connection.statements), 1)

    def test_mismatched_ownership_is_rejected_before_connecting(self):
        cases = {
            "other job": (ExtractionResult("result", "other", "module", ("a-quiz", "a-exam"), (), {}), (QUIZ, EXAM)),
            "ids out of order": (RESULT, (EXAM, QUIZ)),
            "assessment of another result": (RESULT, (QUIZ, Assessment.create("a-exam", "other", "module", facts("exam"), {}))),
        }
        for name, (result, assessments) in cases.items():
            with self.subTest(name):
                pool = Mock()
                with self.assertRaises(ProcessingError):
                    PostgresExtractionResults(pool).save_extraction_result(JOB, result, list(assessments))
                pool.connection.assert_not_called()

    def test_transfer_for_an_unknown_key_is_rejected(self):
        transfer = ReviewTransfer("missing", "old", 1, facts("missing"), {})
        with self.assertRaises(ProcessingError):
            PostgresExtractionResults(Mock()).save_extraction_result(JOB, RESULT, [QUIZ, EXAM], review_transfers=(transfer,))

    def test_succeeded_documents_drop_module_issues_and_are_recomputed(self):
        module_issue = {"code": "invalid_extraction", "message": "Conflict.", "scope": "module", "module_id": "module", "document_id": None}
        own_issue = {"code": "invalid_extraction", "message": "Chunk failed.", "scope": "document", "module_id": "module", "document_id": "d1"}
        record = {**facts("quiz", weight_percent=20, weight_scope="module"), "evidence": {}}
        answers = {
            "FROM stackplan.document_tasks AS task": [
                {"document_id": "d1", "minimum_generation": 1, "issues": [module_issue, own_issue]},
                {"document_id": "d2", "minimum_generation": 1, "issues": [module_issue]},
            ],
            "FROM stackplan.document_chunks": lambda params: (
                [{"records": [record], "uncertainties": []}] if params[0] == "d1" else []
            ),
        }
        self.publish(answers)
        recomputed = self.connection.matching("SET inference = %s, issues = %s::jsonb")
        self.assertEqual(len(recomputed), 1)
        inference, issues, _, document = recomputed[0]
        self.assertEqual((inference, document), ("partially_understood", "d1"))
        self.assertEqual(json.loads(issues), [own_issue])
        self.assertEqual(self.connection.matching("SET issues = %s::jsonb WHERE"), [("[]", "d2")])


if __name__ == "__main__":
    unittest.main()
