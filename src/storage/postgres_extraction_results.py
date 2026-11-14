"""Publish a reconciled module result in PostgreSQL."""

from __future__ import annotations

import json
from typing import Mapping, Sequence
from uuid import uuid4

from src.contracts.postgres_pool import PostgresPool
from src.errors import error_codes as errors
from src.errors.processing_error import ProcessingError
from src.models.assessments.assessment import Assessment
from src.models.processing.document_task import DocumentOutcome
from src.models.processing.extraction_result import ExtractionResult
from src.models.processing.processing_job import ProcessingJob
from src.models.processing.review_transfer import ReviewTransfer
from src.storage.postgres_job_records import require_live_lease


def _plain(value):
    """Return JSON-ready data for the read-only values domain objects hold."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(item) for item in value]
    return value


def _json(value) -> str:
    return json.dumps(_plain(value), ensure_ascii=False)


class PostgresExtractionResults:
    """Implement the worker's save_extraction_result operation."""

    def __init__(self, pool: PostgresPool):
        self.pool = pool

    def save_extraction_result(
        self,
        job: ProcessingJob,
        result: ExtractionResult,
        assessments: Sequence[Assessment],
        manifest: str = "legacy",
        previous_versions: Mapping[str, int] | None = None,
        review_transfers: tuple[ReviewTransfer, ...] = (),
    ) -> int:
        """Publish ``result`` as the module's current result.

        In one transaction, while the job's lease is live:

        - when ``previous_versions`` is given, it must still equal the review
          revision of every assessment in the module's current result, so a
          review saved during processing is never silently lost;
        - the result, its assessments and their evidence are stored, with
          every cited source required to belong to the module;
        - each review transfer is stored as a review of its new assessment,
          linked to the assessment it came from;
        - the result is published and becomes the module's current, fresh
          head, and the module's earlier module-wide issues are resolved;
        - the module's succeeded document tasks drop module-wide issues and
          recompute their outcome from their saved chunks;
        - a schedule revision listing the job's current results is recorded.

        Returns:
            The id of the new schedule revision.

        Raises:
            ProcessingError: ``invalid_extraction`` if the result, assessments
                or evidence do not belong together; ``revision_conflict`` if a
                review changed; ``processing_interrupted`` if the lease was lost.
        """
        if (
            result.job_id != job.id
            or tuple(a.id for a in assessments) != tuple(result.assessment_ids)
            or any(a.result_id != result.id or a.module_id != result.module_id for a in assessments)
        ):
            raise ProcessingError(
                errors.INVALID_EXTRACTION,
                "Result ownership is invalid.",
                "module",
                module_id=result.module_id,
            )
        by_key = {assessment.facts["key"]: assessment for assessment in assessments}
        if any(transfer.key not in by_key for transfer in review_transfers):
            raise ProcessingError(
                errors.INVALID_EXTRACTION,
                "A review transfer does not match a published assessment.",
                "module",
                module_id=result.module_id,
            )

        with self.pool.connection() as connection, connection.transaction():
            require_live_lease(connection, job)
            head = connection.execute(
                "SELECT result_id::text AS result_id FROM stackplan.module_result_heads "
                "WHERE module_id = %s FOR UPDATE",
                (result.module_id,),
            ).fetchone()
            if previous_versions is not None:
                current = {}
                if head is not None:
                    rows = connection.execute(
                        """
                        SELECT assessment.id::text AS id,
                               COALESCE(max(review.revision), 0) AS revision
                        FROM stackplan.assessments AS assessment
                        LEFT JOIN stackplan.review_revisions AS review
                            ON review.assessment_id = assessment.id
                        WHERE assessment.result_id = %s
                        GROUP BY assessment.id
                        """,
                        (head["result_id"],),
                    ).fetchall()
                    current = {row["id"]: row["revision"] for row in rows}
                if current != dict(previous_versions):
                    raise ProcessingError(
                        errors.REVISION_CONFLICT,
                        "Module reviews changed during reconciliation. Reload and retry publication.",
                        "module",
                        module_id=result.module_id,
                    )

            cited = {
                source_id
                for assessment in assessments
                for ids in assessment.evidence.values()
                for source_id in ids
            } | {
                source_id
                for transfer in review_transfers
                for ids in transfer.evidence.values()
                for source_id in ids
            }
            if cited:
                owned = connection.execute(
                    """
                    SELECT count(*) AS count FROM stackplan.source_elements AS source
                    JOIN stackplan.documents AS document ON document.id = source.document_id
                    WHERE source.id = ANY(%s::uuid[]) AND document.module_id = %s
                    """,
                    (sorted(cited), result.module_id),
                ).fetchone()["count"]
                if owned != len(cited):
                    raise ProcessingError(
                        errors.INVALID_EXTRACTION,
                        "Evidence belongs to another module.",
                        "module",
                        module_id=result.module_id,
                    )

            connection.execute(
                """
                INSERT INTO stackplan.extraction_results (id, job_id, module_id, uncertainties, metrics)
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
                """,
                (result.id, job.id, result.module_id, _json(result.uncertainties), _json(result.metrics)),
            )
            for assessment in assessments:
                connection.execute(
                    """
                    INSERT INTO stackplan.assessments (id, result_id, module_id, parent_assessment_id, facts)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (assessment.id, result.id, result.module_id, assessment.parent_assessment_id, _json(assessment.facts)),
                )
                self._insert_evidence(connection, "assessment_evidence", assessment.id, assessment.evidence)
            for transfer in review_transfers:
                review_id = str(uuid4())
                assessment = by_key[transfer.key]
                connection.execute(
                    """
                    INSERT INTO stackplan.review_revisions (id, result_id, assessment_id, module_id, revision, facts)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (review_id, result.id, assessment.id, result.module_id, transfer.revision, _json(transfer.facts)),
                )
                self._insert_evidence(connection, "review_evidence", review_id, transfer.evidence)
                connection.execute(
                    "INSERT INTO stackplan.assessment_review_lineage (assessment_id, previous_assessment_id) VALUES (%s, %s)",
                    (assessment.id, transfer.previous_assessment_id),
                )

            connection.execute(
                "UPDATE stackplan.extraction_results SET published = true WHERE id = %s",
                (result.id,),
            )
            connection.execute(
                """
                INSERT INTO stackplan.module_result_heads (module_id, result_id, manifest)
                VALUES (%s, %s, %s)
                ON CONFLICT (module_id) DO UPDATE
                SET result_id = EXCLUDED.result_id, manifest = EXCLUDED.manifest, stale = false
                """,
                (result.module_id, result.id, manifest),
            )
            connection.execute(
                """
                UPDATE stackplan.processing_issues SET resolved = true
                WHERE job_id = %s AND module_id = %s AND document_id IS NULL
                """,
                (job.id, result.module_id),
            )
            self._refresh_document_outcomes(connection, result.module_id)
            heads = connection.execute(
                """
                SELECT head.module_id::text AS module_id, head.result_id::text AS result_id
                FROM stackplan.module_result_heads AS head
                JOIN stackplan.extraction_results AS stored ON stored.id = head.result_id
                WHERE stored.job_id = %s ORDER BY head.module_id
                """,
                (job.id,),
            ).fetchall()
            revision = connection.execute(
                "INSERT INTO stackplan.schedule_revisions (project_id, results) VALUES (%s, %s::jsonb) RETURNING id",
                (job.project_id, _json([dict(row) for row in heads])),
            ).fetchone()["id"]
        return revision

    @staticmethod
    def _insert_evidence(connection, table, owner_id, evidence):
        owner = "assessment_id" if table == "assessment_evidence" else "review_id"
        for field, source_ids in evidence.items():
            for source_id in sorted(set(source_ids)):
                connection.execute(
                    f"INSERT INTO stackplan.{table} ({owner}, field, source_element_id) VALUES (%s, %s, %s)",
                    (owner_id, field, source_id),
                )

    @staticmethod
    def _refresh_document_outcomes(connection, module_id):
        """Recompute succeeded documents' outcomes without module-wide issues."""
        tasks = connection.execute(
            """
            SELECT task.document_id::text AS document_id, task.minimum_generation, task.issues
            FROM stackplan.document_tasks AS task
            JOIN stackplan.documents AS document ON document.id = task.document_id
            WHERE document.module_id = %s AND task.state = 'succeeded'
                AND NOT EXISTS (
                    SELECT 1 FROM stackplan.document_replacements AS replaced
                    WHERE replaced.old_document_id = document.id
                )
            FOR UPDATE OF task
            """,
            (module_id,),
        ).fetchall()
        for task in tasks:
            chunks = connection.execute(
                """
                SELECT DISTINCT ON (chunk_index) records, uncertainties
                FROM stackplan.document_chunks
                WHERE document_id = %s AND generation >= %s
                ORDER BY chunk_index, generation DESC
                """,
                (task["document_id"], task["minimum_generation"]),
            ).fetchall()
            own_issues = [issue for issue in task["issues"] if issue.get("document_id") is not None]
            if not chunks:
                connection.execute(
                    "UPDATE stackplan.document_tasks SET issues = %s::jsonb WHERE document_id = %s",
                    (_json(own_issues), task["document_id"]),
                )
                continue
            outcome = DocumentOutcome.from_chunks([dict(chunk) for chunk in chunks], own_issues)
            connection.execute(
                """
                UPDATE stackplan.document_tasks
                SET inference = %s, issues = %s::jsonb, uncertainties = %s::jsonb
                WHERE document_id = %s
                """,
                (outcome.inference, _json(outcome.issues), _json(outcome.uncertainties), task["document_id"]),
            )
