"""Remove stored document files that no database record refers to."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil

from src.config import limits
from src.contracts.postgres_pool import PostgresPool

# Advisory lock shared with code that moves accepted uploads into
# ``originals/``. Acceptance should hold it in shared mode while it renames a
# file and inserts its document row, so cleanup (exclusive mode) never sees a
# renamed file before its row commits.
ORIGINALS_LOCK = 719232


def _modified(path: Path) -> float:
    return path.lstat().st_mtime


class PostgresDocumentCleanup:
    """Delete abandoned originals and upload staging directories."""

    def __init__(self, pool: PostgresPool, document_directory: Path):
        self.pool = pool
        self.document_directory = Path(document_directory)

    def cleanup_orphaned_files(self, cutoff: datetime) -> list[str]:
        """Remove unreferenced files last changed before ``cutoff``.

        - ``originals/<name>`` is removed when no document's ``storage_key``
          refers to it. A symbolic link is removed itself, never its target.
        - ``.staging/<directory>`` is removed when neither it nor any entry
          directly inside it changed after ``cutoff``.

        Other directories are never touched. ``cutoff`` must be timezone-aware
        and at least ``CLEANUP_SAFETY_SECONDS`` in the past, so an upload in
        progress is never removed.

        Returns:
            The storage keys removed, sorted.

        Raises:
            ValueError: if ``cutoff`` is naive or too recent.
        """
        if cutoff.tzinfo is None:
            raise ValueError("Cleanup cutoff must include a timezone.")
        latest = datetime.now(timezone.utc) - timedelta(seconds=limits.CLEANUP_SAFETY_SECONDS)
        if cutoff > latest:
            raise ValueError("Cleanup requires at least a one-hour safety interval.")
        limit = cutoff.timestamp()
        removed = []

        with self.pool.connection() as connection, connection.transaction():
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (ORIGINALS_LOCK,))
            registered = {
                row["storage_key"]
                for row in connection.execute("SELECT storage_key FROM stackplan.documents")
            }

            originals = self.document_directory / "originals"
            if originals.is_dir() and not originals.is_symlink():
                for path in originals.iterdir():
                    key = f"originals/{path.name}"
                    if path.is_dir() and not path.is_symlink():
                        continue
                    if key not in registered and _modified(path) < limit:
                        path.unlink()
                        removed.append(key)

            staging = self.document_directory / ".staging"
            if staging.is_dir() and not staging.is_symlink():
                for directory in staging.iterdir():
                    if not directory.is_dir() or directory.is_symlink():
                        continue
                    newest = max([_modified(directory), *(_modified(entry) for entry in directory.iterdir())])
                    if newest < limit:
                        shutil.rmtree(directory)
                        removed.append(f".staging/{directory.name}")
        return sorted(removed)
