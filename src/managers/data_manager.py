"""Persist trimester projects and read processing progress from PostgreSQL."""

import hashlib
from uuid import uuid4

from src.config.settings import Settings
from src.contracts.postgres_pool import PostgresPool
from src.errors import error_codes as errors
from src.errors.processing_error import ProcessingError
from src.models.documents.document_reference import DocumentReference
from src.models.processing import lifecycle
from src.models.processing.checkpoint import ModuleCheckpoint
from src.models.processing.processing_event import ProcessingEvent
from src.models.processing.project_snapshot import ProjectSnapshot
from src.models.projects.module import Module
from src.models.projects.project import Project
from src.schemas.job_status_response import JobStatusResponse
from src.serialization.event_cursor import parse_event_cursor
from src.storage.original_document import open_verified_document
from src.storage.postgres_document_originals import PostgresDocumentOriginals


class DataManager:
    """Own SQL access for trimester projects and their processing progress."""

    def __init__(self, pool: PostgresPool, *, document_directory=Settings.document_directory):
        self.pool = pool
        self.document_originals = PostgresDocumentOriginals(pool, document_directory)

    def open_original(self, document_id: str):
        """Open a verified original for the browser."""
        return self.document_originals.open_original(document_id)

    def get_document_trace(self, document_id: str) -> dict:
        """Read saved evidence and verify whether the original is still available."""
        document = self.document_originals.get_document(document_id)
        with self.pool.connection() as connection:
            parse = connection.execute(
                """
                SELECT id::text AS id, document_id::text AS document_id, parser_version, chunk_count
                FROM stackplan.parse_snapshots WHERE document_id = %s
                """,
                (document_id,),
            ).fetchone()
            elements = []
            if parse is not None:
                # The parse and its elements are saved together and are immutable.
                elements = connection.execute(
                    """
                    SELECT id::text AS id, document_id::text AS document_id,
                           parse_id::text AS parse_id, text, regions, context, position
                    FROM stackplan.source_elements WHERE parse_id = %s ORDER BY position
                    """,
                    (parse["id"],),
                ).fetchall()

        try:
            with open_verified_document(self.document_originals.document_directory, document):
                original_available = True
        except ProcessingError as error:
            if error.code != errors.SOURCE_MISSING:
                raise
            original_available = False

        return {
            "document_id": document.id,
            "filename": document.filename,
            "checksum": document.checksum,
            "original_available": original_available,
            "parse": dict(parse) if parse is not None else None,
            "elements": [dict(element) for element in elements],
        }

    def get_health(self) -> dict[str, str]:
        """Check that PostgreSQL is reachable and the schema is migrated."""
        with self.pool.connection() as connection:
            row = connection.execute(
                "SELECT version FROM stackplan.schema_migrations LIMIT 1"
            ).fetchone()
        if row is None:
            raise RuntimeError("Database schema migrations have not been applied.")
        return {"status": "ok"}

    def create_project(self, name: str, week_count: int) -> Project:
        """Store a new project and return its initial state."""
        project = Project(str(uuid4()), name, week_count)
        with self.pool.connection() as connection:
            connection.execute(
                "INSERT INTO stackplan.projects (id, name, week_count) VALUES (%s, %s, %s)",
                (project.id, project.name, project.week_count),
            )
        return project

    def get_projects(self) -> list[dict]:
        """Return at most 100 project summaries, newest first."""
        with self.pool.connection() as connection:
            rows = connection.execute(
                "SELECT id::text AS id, name, week_count, status, job_id::text AS job_id "
                "FROM stackplan.projects ORDER BY created_at DESC, id DESC LIMIT 100"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_project(self, project_id: str) -> Project:
        """Read a project or raise a domain error if it does not exist."""
        with self.pool.connection() as connection:
            row = connection.execute(
                "SELECT id::text AS id, name, week_count, status, job_id::text AS job_id "
                "FROM stackplan.projects WHERE id = %s",
                (project_id,),
            ).fetchone()
        if row is None:
            raise ProcessingError(errors.NOT_FOUND, "Project was not found.")
        return Project(**row)

    def get_job_status(self, job_id: str) -> JobStatusResponse:
        """Read job status, current document progress and issues in one snapshot."""
        with self.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT job.id::text AS id, job.project_id::text AS project_id,
                       job.status, job.stage,
                       COALESCE((
                           SELECT jsonb_agg(jsonb_build_object(
                               'document_id', document.id, 'module_id', module.id,
                               'module_title', module.module_title, 'filename', document.filename,
                               'state', COALESCE(progress.state, 'waiting')
                           ) ORDER BY module.position, document.id)
                           FROM stackplan.documents AS document
                           JOIN stackplan.modules AS module ON module.id = document.module_id
                           LEFT JOIN stackplan.document_progress AS progress
                               ON progress.document_id = document.id
                           WHERE module.job_id = job.id AND NOT EXISTS (
                               SELECT 1 FROM stackplan.document_replacements AS replacement
                               WHERE replacement.old_document_id = document.id
                           )
                       ), '[]'::jsonb) AS documents,
                       COALESCE((
                           SELECT jsonb_agg(jsonb_build_object(
                               'code', issue.code, 'severity', issue.severity,
                               'message', issue.message, 'scope', issue.scope,
                               'job_id', issue.job_id, 'module_id', issue.module_id,
                               'document_id', issue.document_id
                           ) ORDER BY issue.code, issue.module_id, issue.document_id, issue.id)
                           FROM stackplan.processing_issues AS issue
                           WHERE issue.job_id = job.id AND NOT issue.resolved
                       ), '[]'::jsonb) AS issues
                FROM stackplan.processing_jobs AS job WHERE job.id = %s
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            raise ProcessingError(errors.NOT_FOUND, "Processing task was not found.")

        status = row["status"]
        documents = []
        for saved in row["documents"]:
            state = saved["state"]
            if status == lifecycle.READY:
                state = lifecycle.EXTRACTED
            elif status in (lifecycle.FAILED, lifecycle.INTERRUPTED):
                if state in (lifecycle.PARSING, lifecycle.EXTRACTING):
                    state = status.lower()
                elif state == "waiting":
                    state = "not_processed"
            documents.append({**saved, "state": state})

        return JobStatusResponse(
            row["id"], row["project_id"], status, row["stage"], row["issues"],
            {
                "total_documents": len(documents),
                "extracted_documents": sum(d["state"] == lifecycle.EXTRACTED for d in documents),
                "documents": documents,
            },
        )

    def get_project_snapshot(self, project_id: str) -> ProjectSnapshot:
        """Read project state and related records from one repeatable SQL snapshot."""
        with self.pool.connection() as connection, connection.transaction():
            connection.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            row = connection.execute(
                "SELECT id::text AS id, name, week_count, status, "
                "job_id::text AS job_id, event_sequence "
                "FROM stackplan.projects WHERE id = %s",
                (project_id,),
            ).fetchone()
            if row is None:
                raise ProcessingError(errors.NOT_FOUND, "Project was not found.")

            project_row = dict(row)
            event_cursor = int(project_row.pop("event_sequence"))
            project = Project(**project_row)
            modules = []
            heads = []
            assessments = []
            documents = []
            issues = []

            if project.job_id is not None:
                modules = connection.execute(
                    "SELECT id::text AS id, project_id::text AS project_id, "
                    "job_id::text AS job_id, module_title, normalized_title, "
                    "credit, position FROM stackplan.modules "
                    "WHERE job_id = %s ORDER BY position",
                    (project.job_id,),
                ).fetchall()
                heads = connection.execute(
                    "SELECT head.result_id::text AS result_id, head.stale "
                    "FROM stackplan.module_result_heads AS head "
                    "JOIN stackplan.modules AS module ON module.id = head.module_id "
                    "WHERE module.project_id = %s ORDER BY module.position",
                    (project_id,),
                ).fetchall()
                result_ids = [head["result_id"] for head in heads]
                if result_ids:
                    assessments = connection.execute(
                        "SELECT assessment.id::text AS id, "
                        "assessment.result_id::text AS result_id, "
                        "assessment.module_id::text AS module_id, "
                        "assessment.parent_assessment_id::text AS parent_assessment_id, "
                        "assessment.facts "
                        "FROM stackplan.assessments AS assessment "
                        "WHERE assessment.result_id = ANY(%s) "
                        "ORDER BY assessment.module_id, assessment.id",
                        (result_ids,),
                    ).fetchall()
                documents = connection.execute(
                    "SELECT document.id::text AS id, "
                    "document.module_id::text AS module_id, module.module_title, "
                    "document.filename, document.media_type, document.size, "
                    "document.checksum, "
                    "COALESCE(task.state, progress.state, 'unknown') AS state, "
                    "COALESCE(task.inference, 'unknown') AS inference, "
                    "task.generation, replacement.new_document_id::text AS replaced_by "
                    "FROM stackplan.documents AS document "
                    "JOIN stackplan.modules AS module ON module.id = document.module_id "
                    "LEFT JOIN stackplan.document_tasks AS task "
                    "ON task.document_id = document.id "
                    "LEFT JOIN stackplan.document_progress AS progress "
                    "ON progress.document_id = document.id "
                    "LEFT JOIN stackplan.document_replacements AS replacement "
                    "ON replacement.old_document_id = document.id "
                    "WHERE module.job_id = %s ORDER BY module.position, document.id",
                    (project.job_id,),
                ).fetchall()
                issues = connection.execute(
                    "SELECT code, severity, message, scope, job_id::text AS job_id, "
                    "module_id::text AS module_id, document_id::text AS document_id "
                    "FROM stackplan.processing_issues "
                    "WHERE job_id = %s AND NOT resolved "
                    "ORDER BY code, module_id, document_id",
                    (project.job_id,),
                ).fetchall()

            revision = connection.execute(
                "SELECT max(id) AS id FROM stackplan.schedule_revisions "
                "WHERE project_id = %s",
                (project_id,),
            ).fetchone()
            return ProjectSnapshot(
                project=project,
                modules=tuple(Module(**dict(module)) for module in modules),
                assessments=tuple(dict(assessment) for assessment in assessments),
                issues=tuple(dict(issue) for issue in issues),
                documents=tuple(dict(document) for document in documents),
                revision_id=revision["id"] if revision else None,
                stale=any(head["stale"] for head in heads),
                event_cursor=event_cursor,
            )

    def get_published_result(self, result_id: str) -> dict:
        """Read a published revision with its current assessment facts and citations."""
        with self.pool.connection() as connection, connection.transaction():
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            result = connection.execute(
                """
                SELECT id::text AS id, job_id::text AS job_id, module_id::text AS module_id,
                       uncertainties, metrics
                FROM stackplan.extraction_results WHERE id = %s AND published
                """,
                (result_id,),
            ).fetchone()
            if result is None:
                raise ProcessingError(errors.NOT_FOUND, "Published result was not found.", "module")

            assessments = connection.execute(
                """
                SELECT a.id::text AS id, a.result_id::text AS result_id,
                       a.module_id::text AS module_id,
                       a.parent_assessment_id::text AS parent_assessment_id,
                       COALESCE(review.facts, a.facts) AS facts,
                       COALESCE(review.revision, 0) AS revision,
                       COALESCE(citations.evidence, '{}'::jsonb) AS evidence
                FROM stackplan.assessments AS a
                LEFT JOIN LATERAL (
                    SELECT id, facts, revision FROM stackplan.review_revisions
                    WHERE assessment_id = a.id ORDER BY revision DESC LIMIT 1
                ) AS review ON TRUE
                LEFT JOIN LATERAL (
                    SELECT jsonb_object_agg(field, sources) AS evidence
                    FROM (
                        SELECT field, jsonb_agg(source_element_id ORDER BY source_element_id) AS sources
                        FROM (
                            SELECT field, source_element_id FROM stackplan.assessment_evidence
                            WHERE assessment_id = a.id AND review.id IS NULL
                            UNION ALL
                            SELECT field, source_element_id FROM stackplan.review_evidence
                            WHERE review_id = review.id
                        ) AS source_rows
                        GROUP BY field
                    ) AS fields
                ) AS citations ON TRUE
                WHERE a.result_id = %s ORDER BY a.id
                """,
                (result_id,),
            ).fetchall()

        return {**result, "assessments": [dict(row) for row in assessments]}

    def get_published_result_documents(self, result_id: str) -> list[dict]:
        """List the result's module documents, including historical sources."""
        with self.pool.connection() as connection:
            result = connection.execute(
                """
                SELECT COALESCE(
                    jsonb_agg(jsonb_build_object(
                        'id', document.id, 'filename', document.filename, 'media_type', document.media_type
                    ) ORDER BY document.id) FILTER (WHERE document.id IS NOT NULL),
                    '[]'::jsonb
                ) AS documents
                FROM stackplan.extraction_results AS result
                LEFT JOIN stackplan.documents AS document ON document.module_id = result.module_id
                WHERE result.id = %s AND result.published
                GROUP BY result.id
                """,
                (result_id,),
            ).fetchone()
        if result is None:
            raise ProcessingError(errors.NOT_FOUND, "Published result was not found.", "module")
        return result["documents"]

    def get_processing_events(self, project_id: str, after: int = 0) -> list[ProcessingEvent]:
        """Return up to 100 events after the project-scoped cursor."""
        cursor = parse_event_cursor(after)
        with self.pool.connection() as connection:
            # A left join distinguishes an empty event page from a missing project.
            rows = connection.execute(
                """
                SELECT event.sequence, event.kind, event.payload
                FROM stackplan.projects AS project
                LEFT JOIN LATERAL (
                    SELECT sequence, kind, payload
                    FROM stackplan.processing_events
                    WHERE project_id = project.id AND sequence > %s
                    ORDER BY sequence
                    LIMIT 100
                ) AS event ON TRUE
                WHERE project.id = %s
                ORDER BY event.sequence
                """,
                (cursor, project_id),
            ).fetchall()
        if not rows:
            raise ProcessingError(errors.NOT_FOUND, "Project was not found.")
        if rows[0]["sequence"] is None:
            return []
        return [
            ProcessingEvent(row["sequence"], row["kind"], row["payload"])
            for row in rows
        ]

    def get_job_modules(self, job_id: str) -> list[Module]:
        """Return a job's submitted modules in submission order."""
        with self.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT id::text AS id, project_id::text AS project_id, job_id::text AS job_id,
                       module_title, normalized_title, credit, position
                FROM stackplan.modules
                WHERE job_id = %s
                ORDER BY position
                """,
                (job_id,),
            ).fetchall()
        return [Module(**row) for row in rows]

    def get_processing_documents(self, job_id: str, module_id: str) -> list[DocumentReference]:
        """Return document metadata for a module belonging to the job."""
        with self.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT document.id::text AS id, document.module_id::text AS module_id,
                       document.filename, document.media_type, document.size, document.checksum
                FROM stackplan.documents AS document
                JOIN stackplan.modules AS module ON module.id = document.module_id
                WHERE module.job_id = %s AND module.id = %s
                ORDER BY document.id
                """,
                (job_id, module_id),
            ).fetchall()
        return [DocumentReference(**row) for row in rows]


    def get_module_checkpoint(
        self, job_id: str, module_id: str
    ) -> ModuleCheckpoint:
        """Read the saved extraction candidates and review state for one module.

        All inputs come from one repeatable-read snapshot. Replaced source
        documents are excluded, and the latest accepted chunk per document
        and index is used so a retry cannot mix generations.
        """
        with self.pool.connection() as connection, connection.transaction():
            connection.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            module = connection.execute(
                "SELECT id FROM stackplan.modules WHERE id = %s AND job_id = %s",
                (module_id, job_id),
            ).fetchone()
            if module is None:
                raise ProcessingError(
                    errors.NOT_FOUND,
                    "Module was not found for this processing job.",
                    "module",
                    module_id=module_id,
                )

            chunks = connection.execute(
                """
                SELECT DISTINCT ON (chunk.document_id, chunk.chunk_index)
                       chunk.records, chunk.uncertainties
                FROM stackplan.document_chunks AS chunk
                JOIN stackplan.documents AS document
                  ON document.id = chunk.document_id
                JOIN stackplan.modules AS module
                  ON module.id = document.module_id
                JOIN stackplan.document_tasks AS task
                  ON task.document_id = document.id
                WHERE module.id = %s AND module.job_id = %s
                  AND chunk.generation >= task.minimum_generation
                  AND NOT EXISTS (
                      SELECT 1 FROM stackplan.document_replacements AS replacement
                      WHERE replacement.old_document_id = document.id
                  )
                ORDER BY chunk.document_id, chunk.chunk_index, chunk.generation DESC
                """,
                (module_id, job_id),
            ).fetchall()
            source_rows = connection.execute(
                """
                SELECT source.id::text AS id
                FROM stackplan.source_elements AS source
                JOIN stackplan.documents AS document
                  ON document.id = source.document_id
                JOIN stackplan.modules AS module
                  ON module.id = document.module_id
                WHERE module.id = %s AND module.job_id = %s
                  AND NOT EXISTS (
                      SELECT 1 FROM stackplan.document_replacements AS replacement
                      WHERE replacement.old_document_id = document.id
                  )
                ORDER BY source.id
                """,
                (module_id, job_id),
            ).fetchall()
            current = connection.execute(
                """
                SELECT result_id::text AS result_id, manifest
                FROM stackplan.module_result_heads
                WHERE module_id = %s
                """,
                (module_id,),
            ).fetchone()

            previous_assessments = []
            previous_versions = {}
            if current is not None:
                stored_assessments = connection.execute(
                    """
                    SELECT assessment.id::text AS id,
                           assessment.result_id::text AS result_id,
                           assessment.module_id::text AS module_id,
                           assessment.parent_assessment_id::text AS parent_assessment_id,
                           assessment.facts AS original_facts,
                           COALESCE(review.facts, assessment.facts) AS facts,
                           COALESCE(review.revision, 0) AS revision,
                           review.id::text AS review_revision_id
                    FROM stackplan.assessments AS assessment
                    LEFT JOIN LATERAL (
                        SELECT id, facts, revision
                        FROM stackplan.review_revisions
                        WHERE assessment_id = assessment.id
                        ORDER BY revision DESC
                        LIMIT 1
                    ) AS review ON TRUE
                    WHERE assessment.result_id = %s
                    ORDER BY assessment.id
                    """,
                    (current["result_id"],),
                ).fetchall()

                assessment_ids = [row["id"] for row in stored_assessments]
                original_evidence_rows = []
                review_evidence_rows = []
                if assessment_ids:
                    original_evidence_rows = connection.execute(
                        """
                        SELECT assessment_id::text AS assessment_id, field,
                               source_element_id::text AS source_element_id
                        FROM stackplan.assessment_evidence
                        WHERE assessment_id = ANY(%s::uuid[])
                        ORDER BY assessment_id, field, source_element_id
                        """,
                        (assessment_ids,),
                    ).fetchall()
                    review_ids = [
                        row["review_revision_id"]
                        for row in stored_assessments
                        if row["review_revision_id"] is not None
                    ]
                    if review_ids:
                        review_evidence_rows = connection.execute(
                            """
                            SELECT review_id::text AS review_id, field,
                                   source_element_id::text AS source_element_id
                            FROM stackplan.review_evidence
                            WHERE review_id = ANY(%s::uuid[])
                            ORDER BY review_id, field, source_element_id
                            """,
                            (review_ids,),
                        ).fetchall()

                def group_evidence(rows, owner_key):
                    grouped = {}
                    for evidence in rows:
                        grouped.setdefault(evidence[owner_key], {}).setdefault(
                            evidence["field"], []
                        ).append(evidence["source_element_id"])
                    return grouped

                original_evidence = group_evidence(
                    original_evidence_rows, "assessment_id"
                )
                reviewed_evidence = group_evidence(review_evidence_rows, "review_id")
                for stored in stored_assessments:
                    assessment = dict(stored)
                    review_id = assessment.pop("review_revision_id")
                    assessment["original_evidence"] = original_evidence.get(
                        assessment["id"], {}
                    )
                    assessment["evidence"] = (
                        reviewed_evidence.get(review_id, {})
                        if review_id is not None
                        else assessment["original_evidence"]
                    )
                    previous_assessments.append(assessment)
                    previous_versions[assessment["id"]] = assessment["revision"]

        manifest = hashlib.sha256(repr(chunks).encode("utf-8")).hexdigest()
        return ModuleCheckpoint(
            records=tuple(record for row in chunks for record in row["records"]),
            uncertainties=tuple(
                sorted({item for row in chunks for item in row["uncertainties"]})
            ),
            source_ids=frozenset(row["id"] for row in source_rows),
            manifest=manifest,
            unchanged=bool(current and current["manifest"] == manifest),
            previous_assessments=tuple(previous_assessments),
            previous_versions=previous_versions,
        )
