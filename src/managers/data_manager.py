from __future__ import annotations

from src.config import limits
from src.errors import error_codes as errors
from src.models.processing import lifecycle

from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import hashlib
import mimetypes
import os
from pathlib import Path
import shutil
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from PIL import Image
from pypdf import PdfReader

from src.errors.issues import make_issue
from src.contracts.worker_data import WorkerData
from src.models.documents.document import Document
from src.errors.processing_error import ProcessingError
from src.models.processing.processing_job import ProcessingJob
from src.models.documents.source_element import SourceElement
from src.models.projects.project import Project
from src.models.projects.module import Module


def _serialize_database_value(value):
    if isinstance(value, (UUID, datetime)):
        return str(value)
    if isinstance(value, dict):
        return {k: _serialize_database_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_database_value(v) for v in value]
    return value


class DataManager(WorkerData):
    """The single owner of SQL, storage paths and filesystem operations."""

    def __init__(
        self,
        connection_pool: ConnectionPool,
        document_root,
        document_bytes=limits.DOCUMENT_BYTES,
        lease_seconds=limits.LEASE_SECONDS,
        frontend_directory=None,
        *,
        logic_manager,
    ):
        self.frontend_root = Path(
            frontend_directory or Path(__file__).parents[2] / "frontend"
        ).resolve()
        self._pool = connection_pool
        self._logic = logic_manager
        self.root = Path(document_root).resolve()
        self.document_bytes = document_bytes
        self.lease_seconds = lease_seconds
        self._staging = {}
        self.root.mkdir(parents=True, exist_ok=True)
        for key in (".staging", "originals", "generated"):
            self._resolve(key).mkdir(exist_ok=True)
        if (
            self._resolve(".staging").stat().st_dev
            != self._resolve("originals").stat().st_dev
        ):
            raise ValueError("Staging and originals must share one volume.")

    @property
    def pool(self):
        return self._pool

    @property
    def logic_manager(self):
        return self._logic

    @staticmethod
    def create_pool(database_url, max_size=limits.POOL_SIZE):
        pool = ConnectionPool(
            database_url,
            open=True,
            min_size=1,
            max_size=max_size,
            timeout=5,
            kwargs={
                "autocommit": True,
                "row_factory": dict_row,
                "connect_timeout": 5,
                "options": "-c search_path=stackplan,public -c statement_timeout=5000 -c lock_timeout=2000",
            },
        )
        pool.wait(timeout=10)
        return pool

    def create_schema(self):
        """Explicit migration entry point; never called by a web request."""
        with self._pool.connection() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(719231)")
            conn.execute("CREATE SCHEMA IF NOT EXISTS stackplan")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS stackplan.schema_migrations(version text PRIMARY KEY, checksum text NOT NULL)"
            )
            for file in sorted(
                (Path(__file__).parents[2] / "database" / "migrations").glob("*.sql")
            ):
                contents = file.read_text()
                checksum = hashlib.sha256(contents.encode()).hexdigest()
                existing = conn.execute(
                    "SELECT checksum FROM stackplan.schema_migrations WHERE version=%s",
                    (file.name,),
                ).fetchone()
                if existing:
                    if existing["checksum"] != checksum:
                        raise ValueError("An applied migration has changed.")
                    continue
                conn.execute(contents)
                conn.execute(
                    "INSERT INTO stackplan.schema_migrations VALUES(%s,%s)",
                    (file.name, checksum),
                )

    def get_health(self):
        with self._pool.connection() as conn:
            conn.execute("SELECT version FROM schema_migrations LIMIT 1").fetchone()
        return {"status": "ok"}

    def _resolve(self, key):
        if (
            not isinstance(key, str)
            or not key
            or Path(key).is_absolute()
            or ".." in Path(key).parts
            or "\\" in key
        ):
            raise ProcessingError(
                errors.INVALID_STORAGE_KEY,
                "The document reference is unavailable.",
                "document",
            )
        if key.split("/")[0] not in {".staging", "originals", "generated"}:
            raise ProcessingError(
                errors.INVALID_STORAGE_KEY,
                "The document reference is unavailable.",
                "document",
            )
        result = (self.root / key).resolve()
        if not result.is_relative_to(self.root):
            raise ProcessingError(
                errors.INVALID_STORAGE_KEY,
                "The document reference is unavailable.",
                "document",
            )
        return result

    def _frontend_content(self, directory, filename):
        base = (self.frontend_root / directory).resolve()
        path = (base / filename).resolve()
        if (
            Path(filename).name != filename
            or filename.startswith(".")
            or not path.is_relative_to(base)
            or not path.is_file()
        ):
            raise ProcessingError(errors.NOT_FOUND, "Page asset was not found.")
        return path.read_bytes()

    def get_frontend_page(self, page):
        if page not in ("index", "documents"):
            raise ProcessingError(errors.NOT_FOUND, "Page was not found.")
        return self._frontend_content("templates", page + ".html")

    def get_frontend_asset(self, filename):
        if Path(filename).suffix.lower() not in {
            ".js",
            ".css",
            ".svg",
            ".ico",
            ".png",
            ".jpeg",
            ".jpg",
            ".webp",
            ".woff",
            ".woff2",
        }:
            raise ProcessingError(errors.NOT_FOUND, "Page asset was not found.")
        content = self._frontend_content("static", filename)
        return content, mimetypes.guess_type(filename)[0] or "application/octet-stream"

    def create_project(self, name, week_count):
        project = Project(str(uuid4()), name, week_count)
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO projects(id,name,week_count) VALUES(%s,%s,%s)",
                (project.id, name, week_count),
            )
        return project

    def get_projects(self):
        with self._pool.connection() as conn:
            return _serialize_database_value(
                conn.execute(
                    "SELECT id,name,week_count,status,job_id FROM projects ORDER BY created_at DESC LIMIT 100"
                ).fetchall()
            )

    def get_project(self, project_id):
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT id,name,week_count,status,job_id FROM projects WHERE id=%s",
                (project_id,),
            ).fetchone()
        if not row:
            raise ProcessingError(errors.NOT_FOUND, "Project was not found.")
        return Project(**_serialize_database_value(row))

    def stage_document(self, request_id, filename):
        # Both IDs originate here, never in a request field or browser path.
        UUID(request_id)
        document_id = str(uuid4())
        filename = (
            "".join(
                c for c in filename.replace("\\", "/").split("/")[-1] if c.isprintable()
            )[: limits.DOCUMENT_NAME_LENGTH]
            or "document"
        )
        key = f".staging/{request_id}/{document_id}"
        path = self._resolve(key)
        path.parent.mkdir(exist_ok=True)
        descriptor = {'request_id': request_id, 'document_id': document_id, 'filename': filename,
                      'staging_key': key, 'final_key': '', 'media_type': '', 'size': 0, 'checksum': ''}
        self._staging[document_id] = (descriptor, path.open("xb"), hashlib.sha256())
        return descriptor

    def save_staged_chunk(self, document_id, chunk):
        descriptor, stream, digest = self._staging[document_id]
        descriptor['size'] += len(chunk)
        if descriptor['size'] > self.document_bytes:
            raise ProcessingError(
                errors.INVALID_DOCUMENT,
                "A document exceeds the supported size limit.",
                "document",
            )
        stream.write(chunk)
        digest.update(chunk)

    def complete_staged_document(self, document_id):
        descriptor, stream, digest = self._staging[document_id]
        stream.flush()
        os.fsync(stream.fileno())
        stream.close()
        path = self._resolve(descriptor['staging_key'])
        try:
            with path.open("rb") as source:
                header = source.read(8)
            extension = Path(descriptor['filename']).suffix.lower()
            if header.startswith(b"%PDF-") and extension == ".pdf":
                reader = PdfReader(path, strict=True)
                if (
                    reader.is_encrypted
                    or not 1 <= len(reader.pages) <= limits.PDF_PAGES
                ):
                    raise ValueError("unsupported PDF")
                media_type, suffix = limits.MEDIA_TYPE_PDF, ".pdf"
            else:
                with Image.open(path) as image:
                    fmt, dimensions = image.format, image.size
                    image.verify()
                if (
                    fmt not in {"PNG", "JPEG"}
                    or max(dimensions) > limits.IMAGE_LONG_SIDE
                    or dimensions[0] * dimensions[1] > limits.IMAGE_PIXELS
                ):
                    raise ValueError("unsupported image")
                if extension not in ({".png"} if fmt == "PNG" else {".jpg", ".jpeg"}):
                    raise ValueError("extension mismatch")
                media_type, suffix = (
                    (limits.MEDIA_TYPE_PNG, ".png")
                    if fmt == "PNG"
                    else (limits.MEDIA_TYPE_JPEG, ".jpg")
                )
            if descriptor['size'] == 0:
                raise ValueError("empty document")
        except Exception as exc:
            raise ProcessingError(
                errors.INVALID_DOCUMENT,
                "Upload a readable PDF, PNG or JPEG with a matching filename.",
                "document",
            ) from exc
        descriptor['media_type'] = media_type
        descriptor['checksum'] = digest.hexdigest()
        descriptor['final_key'] = f"originals/{descriptor['document_id']}{suffix}"
        return descriptor

    def discard_staged_documents(self, request_id):
        UUID(request_id)
        for doc_id, (descriptor, stream, _) in list(self._staging.items()):
            if descriptor['request_id'] == request_id:
                stream.close()
                del self._staging[doc_id]
        directory = self._resolve(f".staging/{request_id}")
        if directory.exists():
            shutil.rmtree(directory)

    def _recover_or_require_created(self, project, existing, submission_key):
        if not project:
            raise ProcessingError(errors.NOT_FOUND, "Project was not found.")
        if existing and existing["submission_key"] == submission_key:
            return ProcessingJob(**_serialize_database_value(existing))
        if project["status"] != lifecycle.CREATED or existing:
            raise ProcessingError(
                errors.PROJECT_FROZEN,
                "This project has an accepted task. Create a new project for another submission.",
            )
        return None

    def get_submission(self, project_id, submission_key):
        # The same rule serves an inexpensive preflight and the locked commit.
        with self._pool.connection() as conn:
            project = conn.execute(
                "SELECT status FROM projects WHERE id=%s", (project_id,)
            ).fetchone()
            row = conn.execute(
                "SELECT id,project_id,submission_key,status,stage,lease_token FROM processing_jobs WHERE project_id=%s",
                (project_id,),
            ).fetchone()
        return self._recover_or_require_created(project, row, submission_key)

    def _finalize(self, descriptor):
        original, final = (
            self._resolve(descriptor['staging_key']),
            self._resolve(descriptor['final_key']),
        )
        # Atomic exclusive publication: link refuses an existing destination,
        # unlike POSIX rename, which could overwrite an immutable original.
        linked = False
        try:
            os.link(original, final)
            linked = True
            original.unlink()
            final.chmod(0o400)
            for directory in (original.parent, final.parent):
                fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        except BaseException:
            if linked:
                final.unlink(missing_ok=True)
            raise

    def create_processing_job(self, submission):
        job_id, final_keys = str(uuid4()), []
        prepared = False
        try:
            with self._pool.connection() as conn, conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock_shared(719232)")
                project = conn.execute(
                    "SELECT * FROM projects WHERE id=%s FOR UPDATE",
                    (submission['project_id'],),
                ).fetchone()
                existing = conn.execute(
                    "SELECT id,project_id,submission_key,status,stage,lease_token FROM processing_jobs WHERE project_id=%s",
                    (submission['project_id'],),
                ).fetchone()
                recovered = self._recover_or_require_created(
                    project, existing, submission['submission_key']
                )
                if recovered:
                    return recovered
                conn.execute(
                    "INSERT INTO processing_jobs(id,project_id,submission_key,status,stage) VALUES(%s,%s,%s,%s,%s)",
                    (
                        job_id,
                        submission['project_id'],
                        submission['submission_key'],
                        lifecycle.QUEUED,
                        lifecycle.QUEUED,
                    ),
                )
                for position, module in enumerate(submission['modules']):
                    module_id = str(uuid4())
                    conn.execute(
                        "INSERT INTO modules(id,project_id,job_id,module_title,normalized_title,credit,position) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                        (
                            module_id,
                            submission['project_id'],
                            job_id,
                            module['module_title'],
                            module['normalized_title'],
                            module['credit'],
                            position,
                        ),
                    )
                    for field in module['file_fields']:
                        d = submission['document_fields'][field]
                        conn.execute(
                            "INSERT INTO documents VALUES(%s,%s,%s,%s,%s,%s,%s)",
                            (
                                d['document_id'],
                                module_id,
                                d['filename'],
                                d['media_type'],
                                d['size'],
                                d['checksum'],
                                d['final_key'],
                            ),
                        )
                for d in submission['document_fields'].values():
                    self._finalize(d)
                    final_keys.append(d['final_key'])
                conn.execute(
                    "UPDATE projects SET status=%s,job_id=%s WHERE id=%s",
                    (lifecycle.PROCESSING, job_id, submission['project_id']),
                )
                prepared = True
            return ProcessingJob(
                job_id,
                submission['project_id'],
                submission['submission_key'],
                lifecycle.QUEUED,
                lifecycle.QUEUED,
            )
        except Exception as exc:
            # COMMIT can succeed even when its acknowledgement is lost. Never
            # delete referenced originals on an indeterminate connection failure.
            cleanup = not prepared or isinstance(exc, psycopg.IntegrityError)
            if prepared:
                try:
                    recovered = self.get_submission(
                        submission['project_id'], submission['submission_key']
                    )
                    if recovered:
                        return recovered
                except Exception:
                    cleanup = False
            if cleanup:
                for key in final_keys:
                    self._resolve(key).unlink(missing_ok=True)
            if isinstance(exc, psycopg.errors.UniqueViolation):
                raise ProcessingError(
                    errors.DUPLICATE_DOCUMENT,
                    "A module contains duplicate documents.",
                    "document",
                ) from exc
            raise

    def get_job(self, job_id):
        with self._pool.connection() as conn:
            return self._read_job(conn, job_id)

    def _read_job(self, conn, job_id):
        # One statement gives status and document checkpoints the same snapshot.
        row = conn.execute(
            """SELECT j.id,j.project_id,j.status,j.stage,j.created_at,j.started_at,j.finished_at,
                COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'document_id',d.id,'module_id',m.id,'module_title',m.module_title,
                    'filename',d.filename,'media_type',d.media_type,'state',COALESCE(p.state,'waiting'),
                    'execution',t.state,'inference',t.inference,'generation',t.generation,'issues',t.issues,'uncertainties',t.uncertainties)
                    ORDER BY m.position,d.id)
                FROM documents d JOIN modules m ON m.id=d.module_id
                LEFT JOIN document_progress p ON p.document_id=d.id
                LEFT JOIN document_tasks t ON t.document_id=d.id
                WHERE m.job_id=j.id AND NOT EXISTS(SELECT 1 FROM document_replacements x WHERE x.old_document_id=d.id)),'[]'::jsonb) AS documents
                FROM processing_jobs j WHERE j.id=%s""",
            (job_id,),
        ).fetchone()
        if not row:
            raise ProcessingError(errors.NOT_FOUND, "Processing task was not found.")
        documents = row.pop("documents")
        for document in documents:
            document['retryable'] = self._logic.can_retry_document(row['status'], document['execution'], document['issues'])
            document["original_url"] = f"/api/documents/{document['document_id']}/original"
            document["trace_url"] = f"/api/documents/{document['document_id']}/trace"
            if row["status"] == lifecycle.READY:
                document["state"] = lifecycle.EXTRACTED
            elif row["status"] in (lifecycle.FAILED, lifecycle.INTERRUPTED):
                if document["state"] in (lifecycle.PARSING, lifecycle.EXTRACTING):
                    document["state"] = row["status"].lower()
                elif document["state"] == "waiting":
                    document["state"] = "not_processed"
        row["progress"] = {
            "total_documents": len(documents),
            "extracted_documents": sum(d["state"] == lifecycle.EXTRACTED for d in documents),
            "documents": documents,
        }
        return _serialize_database_value(row)

    def get_job_modules(self, job_id):
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM modules WHERE job_id=%s ORDER BY position", (job_id,)
            ).fetchall()
        return [Module(**_serialize_database_value(row)) for row in rows]

    def get_module_documents(self, job_id, module_id):
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT d.* FROM documents d JOIN modules m ON m.id=d.module_id WHERE m.id=%s AND m.job_id=%s ORDER BY d.id",
                (module_id, job_id),
            ).fetchall()
            return [self._hydrate_document(conn, row) for row in rows]

    @staticmethod
    def _document_metadata(document):
        """Worker transport excludes the original's private storage key."""
        return {key: getattr(document, key)
                for key in ('id', 'module_id', 'filename', 'media_type', 'size', 'checksum')}

    @staticmethod
    def _source_element(record, document_id, parse_id=None):
        """Enforce exclusive source ownership before constructing an entity."""
        if record['document_id'] != document_id or (parse_id is not None and record['parse_id'] != parse_id):
            raise ProcessingError(errors.INVALID_EXTRACTION,
                                  'Source evidence belongs to another document or parse.', 'document',
                                  document_id=document_id)
        return SourceElement(record['id'], document_id, record['parse_id'], record['text'],
                             record['regions'], record['context'])

    def _hydrate_document(self, conn, row, source_records=None):
        values = _serialize_database_value(row)
        if source_records is None:
            source_records = _serialize_database_value(conn.execute(
                'SELECT id,document_id,parse_id,text,regions,context FROM source_elements WHERE document_id=%s ORDER BY position',
                (values['id'],)).fetchall())
        sources = tuple(self._source_element(record, values['id']) for record in source_records)
        if len({element.id for element in sources}) != len(sources):
            raise ProcessingError(errors.INVALID_EXTRACTION, 'Source identities must be unique.', 'document')
        storage_key = values.pop('storage_key')
        return Document(**values, _storage_key=storage_key, _sources=sources)

    def get_processing_documents(self, job_id, module_id):
        return [self._document_metadata(d)
                for d in self.get_module_documents(job_id, module_id)]

    def get_document(self, document_id):
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE id=%s", (document_id,)
            ).fetchone()
            if not row:
                raise ProcessingError(
                    errors.NOT_FOUND, "Document was not found.", "document"
                )
            return self._hydrate_document(conn, row)

    @contextmanager
    def _open_verified_document(self, document):
        stream = None
        try:
            stream = self._resolve(document.storage_key).open("rb")
            if (
                os.fstat(stream.fileno()).st_size != document.size
                or self._checksum(stream) != document.checksum
            ):
                raise OSError("checksum mismatch")
            stream.seek(0)
        except (OSError, ProcessingError) as exc:
            if stream:
                stream.close()
            raise ProcessingError(
                errors.SOURCE_MISSING,
                "The original document is unavailable.",
                "document",
                document_id=document.id,
                module_id=document.module_id,
            ) from exc
        try:
            yield stream
        finally:
            stream.close()

    @contextmanager
    def open_document(self, document_id):
        with self._open_verified_document(self.get_document(document_id)) as stream:
            yield stream

    def get_original_available(self, document_id):
        try:
            with self.open_document(document_id):
                return True
        except ProcessingError as error:
            if error.code != errors.SOURCE_MISSING:
                raise
            return False

    def open_original_chunks(self, document_id):
        manager = self.open_document(document_id)
        stream = manager.__enter__()

        def chunks():
            try:
                while True:
                    chunk = stream.read(limits.STREAM_CHUNK_BYTES)
                    if not chunk:
                        break
                    yield chunk
            finally:
                manager.__exit__(None, None, None)

        return chunks()

    def _checksum(self, stream):
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(limits.STREAM_CHUNK_BYTES), b""):
            digest.update(chunk)
        return digest.hexdigest()

    def cleanup_orphaned_files(self, cutoff):
        if cutoff > datetime.now(timezone.utc) - timedelta(
            seconds=limits.CLEANUP_SAFETY_SECONDS
        ):
            raise ValueError("Cleanup requires at least a one-hour safety interval.")
        removed = []
        with self._pool.connection() as conn, conn.transaction():
            # Serialize with acceptance so no renamed but uncommitted file is
            # mistaken for an orphan, even across app and worker processes.
            conn.execute("SELECT pg_advisory_xact_lock(719232)")
            registered = {
                r["storage_key"]
                for r in conn.execute("SELECT storage_key FROM documents")
            }
            for path in self._resolve("originals").iterdir():
                key = f"originals/{path.name}"
                if key not in registered and path.lstat().st_mtime < cutoff.timestamp():
                    self._resolve(key).unlink()
                    removed.append(key)
            for directory in self._resolve(".staging").iterdir():
                if directory.is_dir() and not directory.is_symlink():
                    ages = [p.lstat().st_mtime for p in directory.iterdir()]
                    if max(ages + [directory.stat().st_mtime]) < cutoff.timestamp():
                        shutil.rmtree(self._resolve(f".staging/{directory.name}"))
                        removed.append(f".staging/{directory.name}")
        return removed

    def claim_next_job(self):
        with self._pool.connection() as conn, conn.transaction():
            row = conn.execute(
                "SELECT id,project_id,submission_key FROM processing_jobs WHERE status=%s ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1",
                (lifecycle.QUEUED,),
            ).fetchone()
            if not row:
                return None
            token = str(uuid4())
            conn.execute(
                "UPDATE processing_jobs SET status=%s,stage=%s,lease_token=%s,lease_expires_at=now()+(%s * interval '1 second'),started_at=now() WHERE id=%s",
                (
                    lifecycle.RUNNING,
                    lifecycle.PARSING,
                    token,
                    self.lease_seconds,
                    row["id"],
                ),
            )
            return ProcessingJob(
                str(row["id"]),
                str(row["project_id"]),
                row["submission_key"],
                lifecycle.RUNNING,
                lifecycle.PARSING,
                token,
            )

    def _require_claim(self, conn, job):
        row = conn.execute(
            "SELECT * FROM processing_jobs WHERE id=%s AND status=%s AND lease_token=%s AND lease_expires_at>now() FOR UPDATE",
            (job.id, lifecycle.RUNNING, job.lease_token),
        ).fetchone()
        if not row:
            raise ProcessingError(
                errors.PROCESSING_INTERRUPTED,
                "The worker no longer owns this task.",
                "system",
                job_id=job.id,
            )
        return row

    def save_job_heartbeat(self, job, stage=None):
        with self._pool.connection() as conn, conn.transaction():
            self._require_claim(conn, job)
            conn.execute(
                "UPDATE processing_jobs SET lease_expires_at=now()+(%s * interval '1 second'),stage=COALESCE(%s,stage) WHERE id=%s",
                (self.lease_seconds, stage, job.id),
            )

    def save_document_progress(self, job, document_id, state):
        """Record an actual worker checkpoint under its exclusive, live job claim."""
        if state not in (lifecycle.PARSING, lifecycle.EXTRACTING, lifecycle.EXTRACTED):
            raise ValueError("Unsupported document checkpoint.")
        with self._pool.connection() as conn, conn.transaction():
            self._require_claim(conn, job)
            updated = conn.execute(
                """INSERT INTO document_progress(document_id,state)
                    SELECT d.id,%s FROM documents d JOIN modules m ON m.id=d.module_id
                    WHERE d.id=%s AND m.job_id=%s
                        AND (%s='parsing' OR EXISTS(SELECT 1 FROM document_progress p WHERE p.document_id=d.id))
                    ON CONFLICT(document_id) DO UPDATE SET state=EXCLUDED.state
                    WHERE (document_progress.state IN ('waiting','unknown') AND EXCLUDED.state='parsing')
                        OR document_progress.state=EXCLUDED.state
                        OR (document_progress.state='parsing' AND EXCLUDED.state='extracting')
                        OR (document_progress.state='extracting' AND EXCLUDED.state='extracted')
                    RETURNING document_id""",
                (state, document_id, job.id, state),
            ).fetchone()
            if not updated:
                raise ProcessingError(
                    errors.INVALID_EXTRACTION,
                    "The document checkpoint is invalid for this task.",
                    "document",
                    document_id=document_id,
                )
            conn.execute(
                "UPDATE processing_jobs SET lease_expires_at=now()+(%s * interval '1 second'),stage=COALESCE(%s,stage) WHERE id=%s",
                (self.lease_seconds, state if state != lifecycle.EXTRACTED else None, job.id),
            )

    def cleanup_interrupted_jobs(self):
        with self._pool.connection() as conn, conn.transaction():
            rows = conn.execute(
                "SELECT id,project_id FROM processing_jobs WHERE status=%s AND lease_expires_at<=now() FOR UPDATE SKIP LOCKED",
                (lifecycle.RUNNING,),
            ).fetchall()
            for row in rows:
                count = conn.execute('SELECT recoveries FROM processing_jobs WHERE id=%s', (row['id'],)).fetchone()['recoveries']
                conn.execute("UPDATE document_tasks SET state='queued',owner_token=NULL WHERE job_id=%s AND state='running'", (row['id'],))
                conn.execute("UPDATE document_progress SET state='waiting' WHERE document_id IN (SELECT document_id FROM document_tasks WHERE job_id=%s AND state='queued')", (row['id'],))
                if count < 3:
                    conn.execute("UPDATE processing_jobs SET status='queued',stage='queued',lease_token=NULL,lease_expires_at=NULL,recoveries=recoveries+1 WHERE id=%s", (row['id'],))
                else:
                    self._stop_unfinished_documents(conn, row['id'])
                    self._insert_issue(conn, row['id'], make_issue(errors.PROCESSING_INTERRUPTED, 'Automatic worker recovery was exhausted. Retry the unfinished documents.'))
                    self._finish_job(conn, row['id'], row['project_id'], lifecycle.INTERRUPTED)
                self._append_event(conn, row['project_id'], 'processing.recovered', {'recoveries': count + 1})
        return len(rows)

    def save_parse_snapshot(
        self, job, document_id, parse_id, parser_version, elements, chunk_count, chunk_bytes=limits.CHUNK_BYTES
    ):
        with self._pool.connection() as conn, conn.transaction():
            self._require_claim(conn, job)
            doc = conn.execute(
                "SELECT d.* FROM documents d JOIN modules m ON m.id=d.module_id WHERE d.id=%s AND m.job_id=%s",
                (document_id, job.id),
            ).fetchone()
            if not doc:
                raise ProcessingError(
                    errors.INVALID_EXTRACTION,
                    "The parse does not belong to this task.",
                    "document",
                )
            for record in elements:
                if record['parse_id'] != parse_id:
                    raise ProcessingError(errors.INVALID_EXTRACTION, 'Source evidence belongs to another parse.', 'document')
            document = self._hydrate_document(conn, doc, elements)
            conn.execute(
                "INSERT INTO parse_snapshots(id,document_id,parser_version,chunk_count,chunk_bytes) VALUES(%s,%s,%s,%s,%s)",
                (parse_id, document_id, parser_version, chunk_count, chunk_bytes),
            )
            for position, element in enumerate(document.get_sources()):
                conn.execute(
                    "INSERT INTO source_elements VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (
                        element.id,
                        document_id,
                        parse_id,
                        element.text,
                        Jsonb(element.regions),
                        element.context,
                        position,
                    ),
                )

    def save_extraction_result(self, job, result, assessments, manifest="legacy", previous_versions=None, review_transfers=()):
        if (
            result['job_id'] != job.id
            or tuple(a.id for a in assessments) != result['assessment_ids']
            or any(
                a.result_id != result['id'] or a.module_id != result['module_id']
                for a in assessments
            )
        ):
            raise ProcessingError(
                errors.INVALID_EXTRACTION, "Result ownership is invalid.", "module"
            )
        with self._pool.connection() as conn, conn.transaction():
            self._require_claim(conn, job)
            if previous_versions is not None:
                _, current_versions = self._review_state(conn, result['module_id'])
                if current_versions != previous_versions:
                    raise ProcessingError(errors.REVISION_CONFLICT, 'Module reviews changed during reconciliation. Reload and retry publication.', 'module')

            conn.execute(
                "INSERT INTO extraction_results(id,job_id,module_id,uncertainties,metrics) VALUES(%s,%s,%s,%s,%s)",
                (
                    result['id'],
                    job.id,
                    result['module_id'],
                    Jsonb(list(result['uncertainties'])),
                    Jsonb(result['metrics']),
                ),
            )
            for assessment in assessments:
                conn.execute(
                    "INSERT INTO assessments VALUES(%s,%s,%s,%s,%s)",
                    (
                        assessment.id,
                        result['id'],
                        result['module_id'],
                        assessment.parent_assessment_id,
                        Jsonb(assessment.facts),
                    ),
                )
                for field, ids in assessment.evidence.items():
                    for source_id in ids:
                        owned = conn.execute(
                            "SELECT s.id FROM source_elements s JOIN documents d ON d.id=s.document_id WHERE s.id=%s AND d.module_id=%s",
                            (source_id, result['module_id']),
                        ).fetchone()
                        if not owned:
                            raise ProcessingError(
                                errors.INVALID_EXTRACTION,
                                "Evidence belongs to another module.",
                                "module",
                                module_id=result['module_id'],
                            )
                        conn.execute(
                            "INSERT INTO assessment_evidence VALUES(%s,%s,%s)",
                            (assessment.id, field, source_id),
                        )
            by_key = {a.facts['key']: a for a in assessments}
            for transfer in review_transfers:
                assessment = by_key[transfer['key']]
                self._append_review(conn, assessment.id, result['id'], result['module_id'],
                                    transfer['revision'], transfer['facts'], transfer['evidence'])
                conn.execute('INSERT INTO assessment_review_lineage VALUES(%s,%s)',
                             (assessment.id, transfer['previous_assessment_id']))
            conn.execute("UPDATE extraction_results SET published=true WHERE id=%s", (result['id'],))
            conn.execute("INSERT INTO module_result_heads(module_id,result_id,manifest) VALUES(%s,%s,%s) ON CONFLICT(module_id) DO UPDATE SET result_id=EXCLUDED.result_id,manifest=EXCLUDED.manifest,stale=false", (result['module_id'], result['id'], manifest))
            conn.execute('UPDATE processing_issues SET resolved=true WHERE job_id=%s AND module_id=%s AND document_id IS NULL', (job.id, result['module_id']))
            self._refresh_module_outcomes(conn, result['module_id'])
            heads = conn.execute("SELECT h.module_id,h.result_id FROM module_result_heads h JOIN extraction_results r ON r.id=h.result_id WHERE r.job_id=%s ORDER BY h.module_id", (job.id,)).fetchall()
            revision = conn.execute("INSERT INTO schedule_revisions(project_id,results) VALUES(%s,%s) RETURNING id", (job.project_id, Jsonb(_serialize_database_value(heads)))).fetchone()['id']
            self._append_event(conn, job.project_id, 'schedule.updated', {'revision': revision})

    def complete_job(self, job):
        with self._pool.connection() as conn, conn.transaction():
            self._require_claim(conn, job)
            status = self._job_result_status(conn, job.id)
            self._finish_job(conn, job.id, job.project_id, status)
            self._append_event(conn, job.project_id, 'processing.settled', {'status': status})

    def _finish_job(self, conn, job_id, project_id, status):
        conn.execute(
            "UPDATE processing_jobs SET status=%s,stage=%s,lease_token=NULL,lease_expires_at=NULL,finished_at=now() WHERE id=%s",
            (status, lifecycle.TERMINAL_STAGES[status], job_id),
        )
        conn.execute("UPDATE projects SET status=%s WHERE id=%s", (status, project_id))

    def _insert_issue(self, conn, job_id, issue):
        conn.execute(
            "INSERT INTO processing_issues(id,job_id,module_id,document_id,code,severity,message,scope) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (
                str(uuid4()),
                job_id,
                issue.get("module_id"),
                issue.get("document_id"),
                issue["code"],
                issue.get("severity", "error"),
                issue["message"],
                issue["scope"],
            ),
        )

    def fail_job(self, job, issues, interrupted=False):
        with self._pool.connection() as conn, conn.transaction():
            row = conn.execute(
                "SELECT * FROM processing_jobs WHERE id=%s AND status=%s AND lease_token=%s FOR UPDATE",
                (job.id, lifecycle.RUNNING, job.lease_token),
            ).fetchone()
            if not row:
                return
            for issue in issues:
                self._insert_issue(conn, job.id, issue)
            self._stop_unfinished_documents(conn, job.id)
            status = lifecycle.INTERRUPTED if interrupted else lifecycle.FAILED
            self._finish_job(conn, job.id, job.project_id, status)

    def get_issues(self, job_id):
        with self._pool.connection() as conn:
            return _serialize_database_value(
                conn.execute(
                    "SELECT code,severity,message,scope,job_id,module_id,document_id FROM processing_issues WHERE job_id=%s AND NOT resolved ORDER BY code,module_id,document_id",
                    (job_id,),
                ).fetchall()
            )

    def get_source_elements(self, module_id):
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT s.* FROM source_elements s JOIN documents d ON d.id=s.document_id WHERE d.module_id=%s ORDER BY s.document_id,s.position",
                (module_id,),
            ).fetchall()
        return _serialize_database_value(rows)

    def get_document_trace(self, document_id):
        document = self.get_document(document_id)
        with self._pool.connection() as conn:
            parse = conn.execute(
                "SELECT id,document_id,parser_version,chunk_count FROM parse_snapshots WHERE document_id=%s",
                (document_id,),
            ).fetchone()
            sources = conn.execute(
                "SELECT id,document_id,parse_id,text,regions,context,position FROM source_elements WHERE document_id=%s ORDER BY position",
                (document_id,),
            ).fetchall()
        return {
            "document_id": document.id,
            "filename": document.filename,
            "checksum": document.checksum,
            "original_available": self.get_original_available(document.id),
            "parse": _serialize_database_value(parse),
            "elements": _serialize_database_value(sources),
        }

    def get_result(self, result_id):
        with self._pool.connection() as conn:
            result = conn.execute(
                "SELECT id,job_id,module_id,uncertainties,metrics FROM extraction_results WHERE id=%s AND published",
                (result_id,),
            ).fetchone()
            if not result:
                raise ProcessingError(
                    errors.NOT_FOUND, "Published result was not found.", "module"
                )
            result = _serialize_database_value(result)
            result["assessments"] = self._load_assessments(conn, [result_id])
        return result

    def _load_assessments(self, conn, result_ids):
        rows = _serialize_database_value(
            conn.execute(
                "SELECT a.id,a.result_id,a.module_id,a.parent_assessment_id,COALESCE(v.facts,a.facts) AS facts,COALESCE(v.revision,0) AS revision,v.id AS review_revision_id FROM assessments a LEFT JOIN LATERAL (SELECT id,facts,revision FROM review_revisions WHERE assessment_id=a.id ORDER BY revision DESC LIMIT 1) v ON true WHERE a.result_id=ANY(%s::uuid[]) ORDER BY a.id",
                (result_ids,),
            ).fetchall()
        )
        for row in rows:
            evidence = conn.execute(
                "SELECT field,source_element_id FROM assessment_evidence WHERE assessment_id=%s ORDER BY field,source_element_id",
                (row["id"],),
            ).fetchall()
            revision_id = row.pop("review_revision_id")
            if revision_id:
                evidence = conn.execute(
                    "SELECT field,source_element_id FROM review_evidence WHERE review_id=%s ORDER BY field,source_element_id",
                    (revision_id,),
                ).fetchall()
            row["evidence"] = {}
            for item in evidence:
                row["evidence"].setdefault(item["field"], []).append(
                    str(item["source_element_id"])
                )
        return rows

    def get_published_results(self, project_id):
        with self._pool.connection() as conn, conn.transaction():
            results = conn.execute(
                "SELECT r.id FROM extraction_results r JOIN module_result_heads h ON h.result_id=r.id JOIN projects p ON p.job_id=r.job_id WHERE p.id=%s AND r.published ORDER BY r.module_id",
                (project_id,),
            ).fetchall()
            return self._load_assessments(conn, [str(r["id"]) for r in results])

    def get_integrity_issues(self, project_id):
        project = self.get_project(project_id)
        if project.status not in (lifecycle.READY, lifecycle.PARTIAL):
            return []
        for module in self.get_job_modules(project.job_id):
            for document in self.get_module_documents(project.job_id, module.id):
                if not self.get_original_available(document.id):
                    with self._pool.connection() as conn:
                        self._insert_issue(
                            conn,
                            project.job_id,
                            make_issue(
                                errors.SOURCE_MISSING,
                                "The original document is unavailable. Parsed evidence remains available.",
                                "document",
                                severity="warning",
                                module_id=module.id,
                                document_id=document.id,
                            ),
                        )
        return self.get_issues(project.job_id)

    def save_review_revision(
        self,
        result_id,
        assessment_id,
        expected_revision,
        facts,
        evidence,
        expected_versions,
    ):
        with self._pool.connection() as conn, conn.transaction():
            job = conn.execute('SELECT j.* FROM processing_jobs j JOIN extraction_results r ON r.job_id=j.id WHERE r.id=%s FOR UPDATE OF j', (result_id,)).fetchone()
            if not job:
                raise ProcessingError(errors.NOT_FOUND, 'Published result was not found.', 'module')

            conn.execute(
                "SELECT id FROM extraction_results WHERE id=%s FOR UPDATE", (result_id,)
            ).fetchone()
            versions = conn.execute(
                "SELECT a.id,COALESCE(max(v.revision),0) AS revision FROM assessments a LEFT JOIN review_revisions v ON v.assessment_id=a.id WHERE a.result_id=%s GROUP BY a.id",
                (result_id,),
            ).fetchall()
            if {str(v["id"]): v["revision"] for v in versions} != expected_versions:
                raise ProcessingError(
                    errors.REVISION_CONFLICT,
                    "This module has newer review facts. Reload it.",
                    "assessment",
                )
            row = conn.execute(
                "SELECT a.module_id FROM assessments a JOIN extraction_results r ON r.id=a.result_id JOIN projects p ON p.job_id=r.job_id WHERE a.id=%s AND a.result_id=%s AND r.published AND EXISTS(SELECT 1 FROM module_result_heads h WHERE h.result_id=r.id) FOR UPDATE OF a",
                (assessment_id, result_id),
            ).fetchone()
            if not row:
                raise ProcessingError(
                    errors.NOT_FOUND,
                    "Published assessment was not found.",
                    "assessment",
                )
            current = conn.execute(
                "SELECT COALESCE(max(revision),0) AS revision FROM review_revisions WHERE assessment_id=%s",
                (assessment_id,),
            ).fetchone()["revision"]
            if current != expected_revision:
                raise ProcessingError(
                    errors.REVISION_CONFLICT,
                    "This assessment has a newer review revision. Reload it.",
                    "assessment",
                )
            revision = current + 1
            self._append_review(conn, assessment_id, result_id, row['module_id'], revision, facts, evidence)
            self._refresh_module_outcomes(conn, row['module_id'])
            self._refresh_settled_status(conn, job)
            heads = conn.execute('SELECT h.module_id,h.result_id FROM module_result_heads h JOIN modules m ON m.id=h.module_id WHERE m.job_id=%s ORDER BY m.id', (job['id'],)).fetchall()
            schedule_revision = conn.execute('INSERT INTO schedule_revisions(project_id,results) VALUES(%s,%s) RETURNING id', (job['project_id'], Jsonb(_serialize_database_value(heads)))).fetchone()['id']
            self._append_event(conn, job['project_id'], 'schedule.updated', {'revision': schedule_revision, 'review_revision': revision})
        return revision

    def _append_event(self, conn, project_id, kind, payload):
        sequence = conn.execute(
            "UPDATE projects SET event_sequence=event_sequence+1 WHERE id=%s RETURNING event_sequence",
            (project_id,),
        ).fetchone()['event_sequence']
        conn.execute("INSERT INTO processing_events VALUES(%s,%s,%s,%s,now())",
                     (project_id, sequence, kind, Jsonb(payload)))

    def get_processing_events(self, project_id, after=0):
        self.get_project(project_id)
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT sequence,kind,payload FROM processing_events WHERE project_id=%s AND sequence>%s ORDER BY sequence LIMIT 100",
                (project_id, after),
            ).fetchall()
        return _serialize_database_value(rows)

    def claim_document_task(self, job):
        with self._pool.connection() as conn, conn.transaction():
            self._require_claim(conn, job)
            row = conn.execute(
                "SELECT t.document_id,t.generation FROM document_tasks t WHERE t.job_id=%s AND t.state='queued' AND NOT EXISTS(SELECT 1 FROM document_replacements x WHERE x.old_document_id=t.document_id) ORDER BY t.document_id FOR UPDATE SKIP LOCKED LIMIT 1",
                (job.id,),
            ).fetchone()
            if not row:
                return None
            conn.execute("UPDATE document_tasks SET state='running',owner_token=%s,updated_at=now() WHERE document_id=%s",
                         (job.lease_token, row['document_id']))
            document = conn.execute("SELECT * FROM documents WHERE id=%s", (row['document_id'],)).fetchone()
            self._append_event(conn, job.project_id, 'document.started', {'document_id': str(row['document_id'])})
        return {'document': {key: _serialize_database_value(document[key])
                             for key in ('id', 'module_id', 'filename', 'media_type', 'size', 'checksum')},
                'generation': row['generation']}

    def _require_document_task(self, conn, job, task):
        self._require_claim(conn, job)
        row = conn.execute(
            "SELECT document_id FROM document_tasks WHERE document_id=%s AND job_id=%s AND generation=%s AND owner_token=%s AND state='running' FOR UPDATE",
            (task['document']['id'], job.id, task['generation'], job.lease_token),
        ).fetchone()
        if not row:
            raise ProcessingError(errors.PROCESSING_INTERRUPTED, 'This document attempt is no longer current.', 'document')

    def get_document_checkpoint(self, document_id):
        with self._pool.connection() as conn:
            parse = conn.execute('SELECT id,chunk_count,chunk_bytes FROM parse_snapshots WHERE document_id=%s', (document_id,)).fetchone()
            elements = conn.execute('SELECT id,document_id,parse_id,text,regions,context FROM source_elements WHERE document_id=%s ORDER BY position', (document_id,)).fetchall()
            chunks = conn.execute('SELECT DISTINCT ON(c.chunk_index) c.chunk_index,c.records,c.uncertainties FROM document_chunks c JOIN document_tasks t ON t.document_id=c.document_id WHERE c.document_id=%s AND c.generation>=t.minimum_generation AND (jsonb_array_length(c.records)>0 OR c.generation=t.generation) ORDER BY c.chunk_index,c.generation DESC', (document_id,)).fetchall()
        return {'parse_id': str(parse['id']) if parse else None,
                'elements': tuple(_serialize_database_value(e) for e in elements),
                'chunks': {c['chunk_index']: {'records': c['records'], 'uncertainties': c['uncertainties']} for c in chunks},
                'chunk_bytes': parse['chunk_bytes'] if parse else limits.CHUNK_BYTES,
                'chunk_count': parse['chunk_count'] if parse else 0}

    def save_document_chunk(self, job, task, index, parse_id, records, uncertainties):
        with self._pool.connection() as conn, conn.transaction():
            self._require_document_task(conn, job, task)
            conn.execute('INSERT INTO document_chunks(document_id,chunk_index,parse_id,records,uncertainties,generation) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                         (task['document']['id'], index, parse_id, Jsonb(records), Jsonb(uncertainties), task['generation']))
            self._append_event(conn, job.project_id, 'chunk.validated', {'document_id': task['document']['id'], 'chunk_index': index})

    def record_extraction_attempt(self, job, task, stage, index, attempt, code, message, status=None, rejected=None):
        with self._pool.connection() as conn, conn.transaction():
            self._require_document_task(conn, job, task)
            conn.execute('INSERT INTO extraction_attempts(document_id,generation,stage,chunk_index,attempt,code,message,provider_status,rejected) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                         (task['document']['id'], task['generation'], stage, index, attempt, code, message[:500], status, Jsonb(rejected) if rejected is not None else None))
            self._append_event(conn, job.project_id, 'document.retry_status', {'document_id': task['document']['id'], 'stage': stage, 'attempt': attempt, 'code': code, 'message': message[:500]})

    def finish_document_task(self, job, task, outcome):
        with self._pool.connection() as conn, conn.transaction():
            self._require_document_task(conn, job, task)
            state = 'succeeded' if outcome['records'] else 'failed'
            conn.execute("UPDATE document_tasks SET state=%s,inference=%s,issues=%s,uncertainties=%s,owner_token=NULL,updated_at=now() WHERE document_id=%s",
                         (state, outcome['inference'], Jsonb(list(outcome['issues'])), Jsonb(list(outcome['uncertainties'])), task['document']['id']))
            checkpoint = 'extracted' if outcome['records'] else 'failed'
            conn.execute('INSERT INTO document_progress VALUES(%s,%s) ON CONFLICT(document_id) DO UPDATE SET state=EXCLUDED.state', (task['document']['id'], checkpoint))
            for issue in outcome['issues']:
                self._insert_issue(conn, job.id, issue)
            self._append_event(conn, job.project_id, 'document.completed', {'document_id': task['document']['id'], 'inference': outcome['inference'], 'state': state})

    def get_module_checkpoint(self, job_id, module_id):
        with self._pool.connection() as conn, conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            rows = conn.execute('SELECT DISTINCT ON(c.document_id,c.chunk_index) c.records,c.uncertainties FROM document_chunks c JOIN documents d ON d.id=c.document_id JOIN document_tasks t ON t.document_id=d.id WHERE d.module_id=%s AND c.generation>=t.minimum_generation AND NOT EXISTS(SELECT 1 FROM document_replacements x WHERE x.old_document_id=d.id) ORDER BY c.document_id,c.chunk_index,c.generation DESC', (module_id,)).fetchall()
            source_ids = conn.execute('SELECT s.id FROM source_elements s JOIN documents d ON d.id=s.document_id WHERE d.module_id=%s AND NOT EXISTS(SELECT 1 FROM document_replacements x WHERE x.old_document_id=d.id)', (module_id,)).fetchall()
            current = conn.execute('SELECT manifest FROM module_result_heads WHERE module_id=%s', (module_id,)).fetchone()
            previous, versions = self._review_state(conn, module_id)
        manifest = hashlib.sha256(repr(rows).encode()).hexdigest()
        return {'records': tuple(r for row in rows for r in row['records']),
                'uncertainties': tuple(sorted({u for row in rows for u in row['uncertainties']})),
                'source_ids': frozenset(str(s['id']) for s in source_ids), 'manifest': manifest,
                'unchanged': bool(current and current['manifest'] == manifest),
                'previous_assessments': tuple(previous), 'previous_versions': versions}

    def save_module_issue(self, job, issue):
        with self._pool.connection() as conn, conn.transaction():
            self._require_claim(conn, job)
            self._insert_issue(conn, job.id, issue)
            # An old valid module remains inspectable, but conflicting new facts
            # must not be mistaken for its current contribution.
            conn.execute('UPDATE module_result_heads SET stale=true WHERE module_id=%s', (issue['module_id'],))
            conn.execute("UPDATE document_tasks SET issues=(SELECT COALESCE(jsonb_agg(i),'[]'::jsonb) FROM jsonb_array_elements(issues) i WHERE i->>'document_id' IS NOT NULL) || %s::jsonb,inference='partially_understood' WHERE document_id IN (SELECT d.id FROM documents d WHERE d.module_id=%s AND NOT EXISTS(SELECT 1 FROM document_replacements x WHERE x.old_document_id=d.id)) AND state='succeeded'", (Jsonb([issue]), issue['module_id']))
            self._append_event(conn, job.project_id, 'module.needs_review', issue)

    def retry_document(self, document_id, request_key, expected_generation):
        document = self.get_document(document_id)
        with self._pool.connection() as conn, conn.transaction():
            job = conn.execute('SELECT j.* FROM processing_jobs j JOIN modules m ON m.job_id=j.id WHERE m.id=%s FOR UPDATE OF j', (document.module_id,)).fetchone()
            previous = conn.execute('SELECT generation FROM retry_requests WHERE document_id=%s AND request_key=%s', (document_id, request_key)).fetchone()
            if previous:
                return {'job_id': str(job['id']), 'document_id': document_id, 'generation': previous['generation']}
            task = conn.execute('SELECT * FROM document_tasks WHERE document_id=%s FOR UPDATE', (document_id,)).fetchone()
            replaced = bool(conn.execute('SELECT 1 FROM document_replacements WHERE old_document_id=%s', (document_id,)).fetchone())
            if task['generation'] != expected_generation or not self._logic.can_retry_document(job['status'], task['state'], task['issues'], replaced):
                raise ProcessingError(errors.REVISION_CONFLICT, 'This document is already processing or has newer results. Reload its status.', 'document')
            generation = task['generation'] + 1
            if any(i.get('document_id') is None for i in task['issues']):
                conn.execute('UPDATE document_tasks SET minimum_generation=%s WHERE document_id=%s', (generation, document_id))
            conn.execute("UPDATE document_tasks SET state='queued',inference='unknown',issues='[]',generation=%s,owner_token=NULL,updated_at=now() WHERE document_id=%s", (generation, document_id))
            conn.execute("INSERT INTO document_progress VALUES(%s,'waiting') ON CONFLICT(document_id) DO UPDATE SET state='waiting'", (document_id,))
            conn.execute('UPDATE processing_issues SET resolved=true WHERE job_id=%s AND (document_id=%s OR (module_id=%s AND document_id IS NULL))', (job['id'], document_id, document.module_id))
            conn.execute('INSERT INTO retry_requests VALUES(%s,%s,%s)', (document_id, request_key, generation))
            conn.execute("UPDATE processing_jobs SET status='queued',stage='queued',finished_at=NULL,recoveries=0 WHERE id=%s", (job['id'],))
            conn.execute("UPDATE projects SET status='Processing' WHERE id=%s", (job['project_id'],))
            self._append_event(conn, job['project_id'], 'document.queued', {'document_id': document_id, 'generation': generation})
        return {'job_id': str(job['id']), 'document_id': document_id, 'generation': generation}

    def acquire_provider_permit(self, job, provider, capacity):
        with self._pool.connection() as conn, conn.transaction():
            self._require_claim(conn, job)
            row = conn.execute("SELECT p.slot FROM provider_permits p WHERE p.provider=%s AND p.slot<=%s AND NOT EXISTS(SELECT 1 FROM processing_jobs j WHERE j.id=p.job_id AND j.status='running' AND j.lease_token=p.owner_token AND j.lease_expires_at>now()) ORDER BY p.slot FOR UPDATE OF p SKIP LOCKED LIMIT 1", (provider, capacity)).fetchone()
            if not row:
                return None
            conn.execute('UPDATE provider_permits SET job_id=%s,owner_token=%s WHERE provider=%s AND slot=%s', (job.id, job.lease_token, provider, row['slot']))
            return row['slot']

    def release_provider_permit(self, job, provider, slot):
        with self._pool.connection() as conn:
            conn.execute('UPDATE provider_permits SET job_id=NULL,owner_token=NULL WHERE provider=%s AND slot=%s AND job_id=%s AND owner_token=%s', (provider, slot, job.id, job.lease_token))


    def get_schedule_revision(self, project_id):
        with self._pool.connection() as conn:
            row = conn.execute('SELECT max(id) AS id FROM schedule_revisions WHERE project_id=%s', (project_id,)).fetchone()
        return row['id']

    def replace_document(self, document_id, descriptor, request_key, expected_generation):
        original = self.get_document(document_id)
        finalized = False
        try:
            with self._pool.connection() as conn, conn.transaction():
                conn.execute('SELECT pg_advisory_xact_lock_shared(719232)')
                job = conn.execute('SELECT j.* FROM processing_jobs j JOIN modules m ON m.job_id=j.id WHERE m.id=%s FOR UPDATE OF j', (original.module_id,)).fetchone()
                existing = conn.execute('SELECT new_document_id,request_key FROM document_replacements WHERE old_document_id=%s', (document_id,)).fetchone()
                if existing:
                    if existing['request_key'] != request_key:
                        raise ProcessingError(errors.REVISION_CONFLICT, 'This document has already been replaced.', 'document')
                    return {'job_id': str(job['id']), 'document_id': str(existing['new_document_id']), 'generation': 1}
                task = conn.execute('SELECT generation FROM document_tasks WHERE document_id=%s', (document_id,)).fetchone()
                if job['status'] in (lifecycle.RUNNING, lifecycle.QUEUED) or task['generation'] != expected_generation:
                    raise ProcessingError(errors.REVISION_CONFLICT, 'Wait for processing to settle and reload before replacing a document.', 'document')
                self._finalize(descriptor)
                finalized = True
                conn.execute('INSERT INTO documents VALUES(%s,%s,%s,%s,%s,%s,%s)', (descriptor['document_id'], original.module_id, descriptor['filename'], descriptor['media_type'], descriptor['size'], descriptor['checksum'], descriptor['final_key']))
                conn.execute('INSERT INTO document_replacements VALUES(%s,%s,%s)', (document_id, descriptor['document_id'], request_key))
                # Legacy module results did not save per-document candidates. Only
                # those siblings need re-extraction to reconcile a replacement.
                conn.execute("UPDATE document_tasks t SET state='queued',inference='unknown',generation=generation+1 WHERE t.document_id IN (SELECT d.id FROM documents d WHERE d.module_id=%s AND d.id NOT IN (%s,%s)) AND t.state='succeeded' AND NOT EXISTS(SELECT 1 FROM document_chunks c WHERE c.document_id=t.document_id)", (original.module_id, document_id, descriptor['document_id']))
                conn.execute("UPDATE document_progress SET state='waiting' WHERE document_id IN (SELECT document_id FROM document_tasks WHERE job_id=%s AND state='queued')", (job['id'],))
                conn.execute('UPDATE module_result_heads SET stale=true WHERE module_id=%s', (original.module_id,))
                conn.execute('UPDATE processing_issues SET resolved=true WHERE job_id=%s AND (document_id=%s OR (module_id=%s AND document_id IS NULL))', (job['id'], document_id, original.module_id))
                conn.execute("UPDATE processing_jobs SET status='queued',stage='queued',finished_at=NULL,recoveries=0 WHERE id=%s", (job['id'],))
                conn.execute("UPDATE projects SET status='Processing' WHERE id=%s", (job['project_id'],))
                self._append_event(conn, job['project_id'], 'document.replaced', {'document_id': descriptor['document_id'], 'replaces': document_id})
            return {'job_id': str(job['id']), 'document_id': descriptor['document_id'], 'generation': 1}
        except psycopg.errors.UniqueViolation as error:
            raise ProcessingError(errors.DUPLICATE_DOCUMENT, 'This module already contains that document.', 'document') from error
        finally:
            # Indeterminate commits retain originals for orphan reconciliation.
            if not finalized:
                self.discard_staged_documents(descriptor['request_id'])


    def has_stale_results(self, project_id):
        with self._pool.connection() as conn:
            return bool(conn.execute('SELECT 1 FROM module_result_heads h JOIN modules m ON m.id=h.module_id WHERE m.project_id=%s AND h.stale', (project_id,)).fetchone())

    def get_project_snapshot(self, project_id):
        """Build the whole response from one repeatable, read-only SQL snapshot."""
        self.get_integrity_issues(project_id)
        with self._pool.connection() as conn, conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            row = conn.execute('SELECT id,name,week_count,status,job_id,event_sequence FROM projects WHERE id=%s', (project_id,)).fetchone()
            if not row:
                raise ProcessingError(errors.NOT_FOUND, 'Project was not found.')
            cursor = row.pop('event_sequence')
            project = Project(**_serialize_database_value(row))
            modules = conn.execute('SELECT * FROM modules WHERE job_id=%s ORDER BY position', (project.job_id,)).fetchall() if project.job_id else []
            heads = conn.execute('SELECT h.result_id,h.stale FROM module_result_heads h JOIN modules m ON m.id=h.module_id WHERE m.project_id=%s ORDER BY m.position', (project_id,)).fetchall()
            assessments = self._load_assessments(conn, [str(h['result_id']) for h in heads])
            documents = self._read_job(conn, project.job_id)['progress']['documents'] if project.job_id else []
            issues = conn.execute('SELECT code,severity,message,scope,job_id,module_id,document_id FROM processing_issues WHERE job_id=%s AND NOT resolved ORDER BY code,module_id,document_id', (project.job_id,)).fetchall() if project.job_id else []
            revision = conn.execute('SELECT max(id) AS id FROM schedule_revisions WHERE project_id=%s', (project_id,)).fetchone()['id']
            return {'project': project, 'modules': tuple(Module(**_serialize_database_value(m)) for m in modules),
                    'assessments': tuple(assessments), 'issues': tuple(_serialize_database_value(issues)),
                    'documents': tuple(documents), 'revision_id': revision,
                    'stale': any(h['stale'] for h in heads), 'event_cursor': cursor}

    def _review_state(self, conn, module_id):
        head = conn.execute('SELECT result_id FROM module_result_heads WHERE module_id=%s', (module_id,)).fetchone()
        if not head:
            return [], {}
        previous = self._load_assessments(conn, [str(head['result_id'])])
        for old in previous:
            old['original_facts'] = conn.execute('SELECT facts FROM assessments WHERE id=%s', (old['id'],)).fetchone()['facts']
            evidence = conn.execute('SELECT field,source_element_id FROM assessment_evidence WHERE assessment_id=%s ORDER BY field,source_element_id', (old['id'],)).fetchall()
            old['original_evidence'] = {}
            for citation in evidence:
                old['original_evidence'].setdefault(citation['field'], []).append(str(citation['source_element_id']))
        return previous, {old['id']: old['revision'] for old in previous}

    def _append_review(self, conn, assessment_id, result_id, module_id, revision, facts, evidence):
        review_id = str(uuid4())
        conn.execute('INSERT INTO review_revisions(id,result_id,assessment_id,module_id,revision,facts) VALUES(%s,%s,%s,%s,%s,%s)',
                     (review_id, result_id, assessment_id, module_id, revision, Jsonb(facts)))
        for field, source_ids in evidence.items():
            for source_id in set(source_ids):
                conn.execute('INSERT INTO review_evidence VALUES(%s,%s,%s)', (review_id, field, source_id))

    def _refresh_module_outcomes(self, conn, module_id):
        """Recompute document understanding from effective facts, preserving gaps."""
        head = conn.execute('SELECT result_id,stale,manifest FROM module_result_heads WHERE module_id=%s', (module_id,)).fetchone()
        if not head or head['stale']:
            return
        assessments = self._load_assessments(conn, [str(head['result_id'])])
        by_key = {a['facts']['key']: a for a in assessments}
        tasks = conn.execute("SELECT t.* FROM document_tasks t JOIN documents d ON d.id=t.document_id WHERE d.module_id=%s AND NOT EXISTS(SELECT 1 FROM document_replacements x WHERE x.old_document_id=d.id) FOR UPDATE OF t", (module_id,)).fetchall()
        for task in tasks:
            if task['state'] != 'succeeded':
                continue
            chunks = conn.execute('SELECT DISTINCT ON(chunk_index) records,uncertainties FROM document_chunks WHERE document_id=%s AND generation>=%s ORDER BY chunk_index,generation DESC', (task['document_id'], task['minimum_generation'])).fetchall()
            keys = {r['key'] for chunk in chunks for r in chunk['records']}
            if not chunks:
                # Old published results have source evidence but no chunk cache.
                ids = {str(r['id']) for r in conn.execute('SELECT id FROM source_elements WHERE document_id=%s', (task['document_id'],)).fetchall()}
                keys = {a['facts']['key'] for a in assessments if any(ids.intersection(v) for v in a['evidence'].values())}
            if not keys:
                continue
            own_issues = [i for i in task['issues'] if i.get('document_id') is not None]
            parse = conn.execute('SELECT chunk_count FROM parse_snapshots WHERE document_id=%s', (task['document_id'],)).fetchone()
            if head['manifest'] != 'legacy' and parse and len(chunks) < parse['chunk_count'] and not own_issues:
                own_issues.append(make_issue(errors.INVALID_EXTRACTION,
                                             'Some source chunks still need extraction. Retry this document.',
                                             'document', module_id=str(module_id), document_id=str(task['document_id'])))
            # Missing chunks and provider uncertainties remain unresolved. Only
            # module-derived errors and generated unknown-field notes are replaced.
            records = [{**by_key[key]['facts'], 'evidence': by_key[key]['evidence']} for key in sorted(keys) if key in by_key]
            unknowns = sorted({u for chunk in chunks for u in chunk['uncertainties']})
            if not chunks:
                unknowns = conn.execute('SELECT uncertainties FROM extraction_results WHERE id=%s', (head['result_id'],)).fetchone()['uncertainties']
            outcome = self._logic.build_document_outcome([{'records': records, 'uncertainties': unknowns}], own_issues)
            conn.execute('UPDATE document_tasks SET inference=%s,issues=%s,uncertainties=%s WHERE document_id=%s',
                         (outcome['inference'], Jsonb(list(outcome['issues'])), Jsonb(list(outcome['uncertainties'])), task['document_id']))

    def _job_result_status(self, conn, job_id):
        modules = conn.execute('SELECT count(*) AS n FROM modules WHERE job_id=%s', (job_id,)).fetchone()['n']
        heads = conn.execute('SELECT h.stale FROM module_result_heads h JOIN modules m ON m.id=h.module_id WHERE m.job_id=%s', (job_id,)).fetchall()
        tasks = conn.execute("SELECT state,inference,issues FROM document_tasks t WHERE job_id=%s AND NOT EXISTS(SELECT 1 FROM document_replacements x WHERE x.old_document_id=t.document_id)", (job_id,)).fetchall()
        errors_present = bool(conn.execute("SELECT 1 FROM processing_issues WHERE job_id=%s AND NOT resolved AND severity='error' LIMIT 1", (job_id,)).fetchone())
        return self._logic.settled_status(modules, len(heads), tasks, errors_present, any(h['stale'] for h in heads))

    def _refresh_settled_status(self, conn, job):
        if job['status'] not in (lifecycle.READY, lifecycle.PARTIAL, lifecycle.FAILED):
            return False
        status = self._job_result_status(conn, job['id'])
        if status != job['status']:
            self._finish_job(conn, job['id'], job['project_id'], status)
            return True
        return False

    def _stop_unfinished_documents(self, conn, job_id):
        conn.execute("UPDATE document_tasks SET state='failed',owner_token=NULL WHERE job_id=%s AND state IN ('queued','running')", (job_id,))

    def repair_completed_outcomes(self):
        """Idempotent upgrade repair; no inference or changes to immutable facts."""
        with self._pool.connection() as conn, conn.transaction():
            jobs = conn.execute("SELECT * FROM processing_jobs WHERE status IN ('Ready','Partial','Failed') ORDER BY id FOR UPDATE").fetchall()
            for job in jobs:
                heads = conn.execute('SELECT h.module_id FROM module_result_heads h JOIN modules m ON m.id=h.module_id WHERE m.job_id=%s AND NOT h.stale', (job['id'],)).fetchall()
                for head in heads:
                    self._refresh_module_outcomes(conn, head['module_id'])
                if self._refresh_settled_status(conn, job):
                    self._append_event(conn, job['project_id'], 'schedule.updated', {'coverage_repaired': True})
