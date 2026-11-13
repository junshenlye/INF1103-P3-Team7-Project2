"""Record project processing events in PostgreSQL."""

import json
from typing import Any

from src.errors.error_codes import NOT_FOUND
from src.errors.processing_error import ProcessingError


def append_processing_event(
    connection: Any, project_id: str, kind: str, payload: dict
) -> int:
    """Store one event and return its project-scoped sequence.

    Use the caller's connection so the event can commit with the state
    change it describes. The counter and insert share one SQL statement,
    so a failed insert cannot leave the counter advanced.
    """
    row = connection.execute(
        """
        WITH next_event AS (
            UPDATE stackplan.projects
            SET event_sequence = event_sequence + 1
            WHERE id = %s
            RETURNING id, event_sequence
        )
        INSERT INTO stackplan.processing_events (project_id, sequence, kind, payload)
        SELECT id, event_sequence, %s, %s::jsonb FROM next_event
        RETURNING sequence
        """,
        (project_id, kind, json.dumps(payload, allow_nan=False)),
    ).fetchone()
    if row is None:
        raise ProcessingError(NOT_FOUND, "Project was not found.")
    return row["sequence"]
