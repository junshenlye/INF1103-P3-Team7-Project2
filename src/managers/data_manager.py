"""Persist trimester projects and read processing progress from PostgreSQL."""

from uuid import uuid4

from src.contracts.postgres_pool import PostgresPool
from src.errors import error_codes as errors
from src.errors.processing_error import ProcessingError
from src.models.documents.document_reference import DocumentReference
from src.models.processing.processing_event import ProcessingEvent
from src.models.processing.project_snapshot import ProjectSnapshot
from src.models.projects.module import Module
from src.models.projects.project import Project
from src.serialization.event_cursor import parse_event_cursor


class DataManager:
    """Own SQL access for trimester projects and their processing progress."""

    def __init__(self, pool: PostgresPool):
        self.pool = pool

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
