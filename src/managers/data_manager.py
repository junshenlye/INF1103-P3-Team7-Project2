"""Persist trimester projects in PostgreSQL."""

from uuid import uuid4

from src.contracts.postgres_pool import PostgresPool
from src.errors import error_codes as errors
from src.errors.processing_error import ProcessingError
from src.models.projects.project import Project


class DataManager:
    """Own SQL access for trimester project records."""

    def __init__(self, pool: PostgresPool):
        self.pool = pool

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
