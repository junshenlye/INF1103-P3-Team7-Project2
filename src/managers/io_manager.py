from __future__ import annotations

from src.config import limits
from src.errors import error_codes as errors
from src.models.processing import lifecycle

from contextlib import asynccontextmanager
from dataclasses import asdict
import re
import asyncio
import json
from urllib.parse import unquote
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse, Response
from python_multipart import MultipartParser
from python_multipart.multipart import parse_options_header
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from src.errors.issues import issue_from_error
from src.serialization.json_data import load_json
from src.errors.processing_error import ProcessingError


def _json(raw):
    try:
        return load_json(raw)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ProcessingError(
            errors.INVALID_REQUEST, "Provide valid JSON without duplicate keys."
        ) from exc


class IOManager:
    """The only HTTP boundary. No provider, SQL or filesystem access."""

    def __init__(
        self,
        data_manager,
        logic_manager,
        request_bytes=limits.REQUEST_BYTES,
        document_bytes=limits.DOCUMENT_BYTES,
    ):
        self._data = data_manager
        self._logic = logic_manager
        self.request_bytes = request_bytes
        self.document_bytes = document_bytes

    def get_application(self, on_close=None):
        @asynccontextmanager
        async def lifespan(_app):
            yield
            if on_close:
                on_close()

        app = FastAPI(
            title="Stackplan", lifespan=lifespan, docs_url=None, redoc_url=None
        )
        routes = [
            ("/api/documents/{document_id}/replacement", self.handle_document_replacement, ["POST"]),
            ("/api/projects/{project_id}/events", self.get_project_events, ["GET"]),
            ("/api/documents/{document_id}/retry", self.handle_document_retry, ["POST"]),
            ("/health", self.get_health, ["GET"]),
            ("/ready", self.get_health, ["GET"]),
            ("/", self.get_frontend, ["GET"]),
            ("/documents", self.get_document_view, ["GET"]),
            ("/static/{asset_name}", self.get_frontend_asset, ["GET"]),
            ("/api/limits", self.get_limits, ["GET"]),
            ("/api/projects", self.get_projects, ["GET"]),
            ("/api/projects", self.handle_create_project, ["POST"]),
            ("/api/projects/{project_id}", self.get_project, ["GET"]),
            ("/api/projects/{project_id}/process", self.handle_submit_bucket, ["POST"]),
            ("/api/jobs/{job_id}", self.get_job_status, ["GET"]),
            ("/api/results/{result_id}", self.get_result, ["GET"]),
            ("/api/results/{result_id}/documents", self.get_result_documents, ["GET"]),
            ("/api/documents/{document_id}/trace", self.get_document_trace, ["GET"]),
            ("/api/documents/{document_id}/original", self.get_document, ["GET"]),
            (
                "/api/results/{result_id}/assessments/{assessment_id}/reviews",
                self.handle_assessment_review,
                ["POST"],
            ),
        ]
        for path, handler, methods in routes:
            app.add_api_route(path, handler, methods=methods)

        @app.exception_handler(ProcessingError)
        async def domain_error(_request, error):
            return self._error(error)

        @app.exception_handler(RequestValidationError)
        async def validation_error(_request, _error):
            return self._error(
                ProcessingError(
                    errors.INVALID_REQUEST, "Request parameters are invalid."
                )
            )

        @app.exception_handler(HTTPException)
        async def http_error(_request, error):
            return self._error(
                ProcessingError(
                    errors.NOT_FOUND
                    if error.status_code == 404
                    else errors.INVALID_REQUEST,
                    "The requested operation is unavailable.",
                ),
                error.status_code,
            )

        @app.exception_handler(Exception)
        async def unexpected_error(_request, _error):
            return self._error(
                ProcessingError(
                    errors.SERVICE_UNAVAILABLE,
                    "The request could not be completed. Read the project to check whether a task was accepted.",
                    "system",
                ),
            )

        return app

    def _error(self, error, status=None):
        statuses = {
            errors.NOT_FOUND: 404,
            errors.DUPLICATE_MODULE: 409,
            errors.DUPLICATE_DOCUMENT: 409,
            errors.PROJECT_FROZEN: 409,
            errors.REVISION_CONFLICT: 409,
            errors.REQUEST_TOO_LARGE: 413,
            errors.INVALID_DOCUMENT: 422,
            errors.SERVICE_UNAVAILABLE: 503,
        }
        issue = issue_from_error(error)
        return JSONResponse(
            {'issues': [issue]},
            status_code=status or statuses.get(error.code, 422),
        )

    def _id(self, value):
        try:
            return str(UUID(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ProcessingError(
                errors.NOT_FOUND, "The requested record was not found."
            ) from exc

    async def _read_json(self, request):
        if (
            request.headers.get("content-type", "").split(";")[0].strip()
            != "application/json"
        ):
            raise ProcessingError(
                errors.INVALID_REQUEST, "Send project and review requests as JSON."
            )
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > limits.JSON_BYTES:
                raise ProcessingError(
                    errors.REQUEST_TOO_LARGE, "JSON exceeds the supported limit."
                )
            raw.extend(chunk)
        return _json(raw)

    def get_frontend(self):
        return Response(
            self._data.get_frontend_page("index"),
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    def get_document_view(self):
        return Response(
            self._data.get_frontend_page("documents"),
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    def get_frontend_asset(self, asset_name: str):
        content, media_type = self._data.get_frontend_asset(asset_name)
        return Response(
            content,
            media_type=media_type,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    def get_limits(self):
        """Public form bounds share the backend's authoritative values."""
        return {
            "request_bytes": self.request_bytes,
            "document_bytes": self.document_bytes,
            "module_count": limits.MODULE_COUNT,
            "documents_per_module": limits.DOCUMENTS_PER_MODULE,
            "project_name_length": limits.PROJECT_NAME_LENGTH,
            "module_title_length": limits.MODULE_TITLE_LENGTH,
            "credit": limits.CREDIT,
            "week_count": limits.WEEK_COUNT,
            "media_types": limits.MEDIA_TYPES,
        }

    def get_health(self):
        return self._data.get_health()

    def get_projects(self):
        return self._data.get_projects()

    async def handle_create_project(self, request: Request):
        command = self._logic.validate_project(await self._read_json(request))
        project = await run_in_threadpool(
            self._data.create_project, command['name'], command['week_count']
        )
        return JSONResponse(asdict(project), status_code=201)

    async def handle_submit_bucket(self, project_id: str, request: Request):
        project_id = self._id(project_id)
        key = request.headers.get("idempotency-key", "")
        if not re.fullmatch(limits.SUBMISSION_KEY_PATTERN, key):
            raise ProcessingError(
                errors.INVALID_REQUEST, "Provide a browser-generated Idempotency-Key."
            )
        length = request.headers.get("content-length")
        if length and (not length.isdecimal() or int(length) > self.request_bytes):
            raise ProcessingError(
                errors.REQUEST_TOO_LARGE,
                "The upload exceeds the supported request size limit.",
            )
        existing = await run_in_threadpool(self._data.get_submission, project_id, key)
        if existing:
            return self._accepted(existing)
        media, options = parse_options_header(request.headers.get("content-type", ""))
        boundary = options.get(b"boundary", b"")
        if (
            media != b"multipart/form-data"
            or not 1 <= len(boundary) <= limits.MULTIPART_BOUNDARY_LENGTH
        ):
            raise ProcessingError(
                errors.INVALID_REQUEST,
                "Send modules and documents as multipart form data.",
            )
        request_id = str(uuid4())
        documents = {}
        metadata = None
        part = {}
        header_name = bytearray()
        header_value = bytearray()
        part_count = 0
        ended = False

        def begin():
            nonlocal part, part_count
            part_count += 1
            if part_count > limits.MULTIPART_PART_COUNT:
                raise ProcessingError(
                    errors.INVALID_REQUEST, "Too many multipart fields."
                )
            part = {"headers": {}, "header_bytes": 0, "value": bytearray()}

        def header_field(data, start, end):
            header_name.extend(data[start:end])
            limit_header(end - start)

        def header_value_data(data, start, end):
            header_value.extend(data[start:end])
            limit_header(end - start)

        def limit_header(size):
            part["header_bytes"] += size
            if part["header_bytes"] > limits.MULTIPART_HEADER_BYTES:
                raise ProcessingError(
                    errors.INVALID_REQUEST,
                    "Multipart headers exceed the supported limit.",
                )

        def header_end():
            name = bytes(header_name).lower()
            if name in part["headers"]:
                raise ProcessingError(
                    errors.INVALID_REQUEST, "Duplicate multipart headers are invalid."
                )
            part["headers"][name] = bytes(header_value)
            header_name.clear()
            header_value.clear()

        def headers_finished():
            disposition, parameters = parse_options_header(
                part["headers"].get(b"content-disposition", b"")
            )
            try:
                name = parameters.get(b"name", b"").decode("utf-8")
            except UnicodeError:
                raise ProcessingError(
                    errors.INVALID_REQUEST, "Invalid multipart field name."
                )
            if disposition != b"form-data" or not re.fullmatch(
                limits.FIELD_NAME_PATTERN, name
            ):
                raise ProcessingError(
                    errors.INVALID_REQUEST, "Invalid multipart disposition."
                )
            part["name"] = name
            if b"filename" in parameters:
                if name == "modules" or name in documents:
                    raise ProcessingError(
                        errors.INVALID_REQUEST, "Upload field names must be unique."
                    )
                try:
                    filename = parameters[b"filename"].decode("utf-8")
                except UnicodeError:
                    raise ProcessingError(
                        errors.INVALID_DOCUMENT,
                        "The document filename is invalid.",
                        "document",
                    )
                part["document"] = self._data.stage_document(request_id, filename)
                documents[name] = part["document"]
            elif name != "modules":
                raise ProcessingError(
                    errors.INVALID_REQUEST, "Unexpected multipart field."
                )

        def data_received(data, start, end):
            value = data[start:end]
            if "document" in part:
                self._data.save_staged_chunk(part["document"]['document_id'], value)
            else:
                if len(part["value"]) + len(value) > limits.MODULE_METADATA_BYTES:
                    raise ProcessingError(
                        errors.INVALID_REQUEST,
                        "Module metadata exceeds the supported limit.",
                    )
                part["value"].extend(value)

        def end_part():
            nonlocal metadata
            if "document" in part:
                self._data.complete_staged_document(part["document"]['document_id'])
            elif metadata is not None:
                raise ProcessingError(
                    errors.INVALID_REQUEST, "Only one modules field is allowed."
                )
            else:
                metadata = _json(part["value"])

        def end():
            nonlocal ended
            ended = True

        parser = MultipartParser(
            boundary,
            {
                "on_part_begin": begin,
                "on_header_field": header_field,
                "on_header_value": header_value_data,
                "on_header_end": header_end,
                "on_headers_finished": headers_finished,
                "on_part_data": data_received,
                "on_part_end": end_part,
                "on_end": end,
            },
        )
        try:
            total = 0
            async for chunk in request.stream():
                total += len(chunk)
                if total > self.request_bytes:
                    raise ProcessingError(
                        errors.REQUEST_TOO_LARGE,
                        "The upload exceeds the supported request size limit.",
                    )
                parser.write(chunk)
            parser.finalize()
            if not ended:
                raise ProcessingError(
                    errors.INVALID_REQUEST, "The multipart upload is incomplete."
                )
            modules = self._logic.validate_submission(metadata, documents)
            snapshot = {'project_id': project_id, 'submission_key': key,
                        'modules': modules, 'document_fields': documents}
            job = await run_in_threadpool(self._data.create_processing_job, snapshot)
            return self._accepted(job)
        except ProcessingError:
            raise
        except (ValueError, KeyError) as exc:
            raise ProcessingError(
                errors.INVALID_REQUEST, "The multipart upload is malformed."
            ) from exc
        finally:
            self._data.discard_staged_documents(request_id)

    def _accepted(self, job):
        return JSONResponse(
            {"project_id": job.project_id, "job_id": job.id, "status": job.status},
            status_code=202,
        )

    def get_job_status(self, job_id: str):
        row = self._data.get_job(self._id(job_id))
        response = {key: row[key] for key in ('id', 'project_id', 'status', 'stage', 'progress')}
        response['issues'] = self._data.get_issues(row['id'])
        return {**row, **response}

    def get_project(self, project_id: str):
        snapshot = self._data.get_project_snapshot(self._id(project_id))
        project = snapshot['project']
        assessments = list(snapshot['assessments'])
        module_rows = [
            {'id': m.id, 'module_title': m.module_title, 'credit': m.credit, 'position': m.position,
             'assessments': [a for a in assessments if a['module_id'] == m.id]}
            for m in snapshot['modules']
        ]
        schedule = self._logic.build_schedule(
            snapshot['modules'], assessments, project.week_count, project.id
        ).to_record() if assessments else None
        return {
            'id': project.id, 'name': project.name, 'week_count': project.week_count,
            'status': project.status, 'job_id': project.job_id, 'modules': module_rows,
            'schedule': schedule, 'issues': list(snapshot['issues']),
            'processing_status': 'running' if project.status == lifecycle.PROCESSING else 'idle' if project.status == lifecycle.CREATED else 'settled',
            'coverage': self._logic.coverage(project.status, bool(assessments), snapshot['documents'], snapshot['stale']),
            'documents': list(snapshot['documents']), 'schedule_revision_id': snapshot['revision_id'],
            'stale': snapshot['stale'], 'event_cursor': snapshot['event_cursor'],
        }

    def get_result(self, result_id: str):
        return self._data.get_result(self._id(result_id))

    def get_result_documents(self, result_id: str):
        result = self._data.get_result(self._id(result_id))
        documents = self._data.get_module_documents(
            result["job_id"], result["module_id"]
        )
        return [
            {"id": d.id, "filename": d.filename, "media_type": d.media_type}
            for d in documents
        ]

    def get_document_trace(self, document_id: str):
        return self._data.get_document_trace(self._id(document_id))

    def get_document(self, document_id: str):
        document_id = self._id(document_id)
        document = self._data.get_document(document_id)
        chunks = self._data.open_original_chunks(document_id)
        return StreamingResponse(
            chunks,
            media_type=document.media_type,
            headers={
                "Content-Disposition": f'inline; filename="document-{document.id}.{document.media_type.split("/")[-1]}"',
                "Content-Length": str(document.size),
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, no-store",
            },
        )

    async def handle_assessment_review(
        self, result_id: str, assessment_id: str, request: Request
    ):
        result_id, assessment_id = self._id(result_id), self._id(assessment_id)
        raw = await self._read_json(request)
        if (
            not isinstance(raw, dict)
            or set(raw)
            not in (
                {"expected_revision", "changes"},
                {"expected_revision", "changes", "evidence"},
            )
            or type(raw["expected_revision"]) is not int
            or raw["expected_revision"] < 0
        ):
            raise ProcessingError(
                errors.INVALID_REQUEST,
                "Provide changes and the current review revision.",
            )
        result = await run_in_threadpool(self._data.get_result, result_id)
        original = next(
            (a for a in result["assessments"] if a["id"] == assessment_id), None
        )
        if not original:
            raise ProcessingError(
                errors.NOT_FOUND, "Published assessment was not found.", "assessment"
            )
        job = await run_in_threadpool(self._data.get_job, result["job_id"])
        project = await run_in_threadpool(self._data.get_project, job["project_id"])
        facts = self._logic.correct_assessment(
            original["facts"], raw["changes"], project.week_count
        )
        sources = await run_in_threadpool(
            self._data.get_source_elements, result["module_id"]
        )
        evidence = raw.get("evidence", {})
        if not isinstance(evidence, dict):
            raise ProcessingError(
                errors.INVALID_REQUEST,
                "Review evidence must identify saved source elements.",
                "assessment",
            )
        evidence = {**original["evidence"], **evidence}
        self._logic.validate_source_references(
            {**facts, "evidence": evidence}, {s["id"] for s in sources}
        )
        records = [
            a["facts"] if a["id"] != assessment_id else facts
            for a in result["assessments"]
        ]
        self._logic.validate_relationships(records)
        revision = await run_in_threadpool(
            self._data.save_review_revision,
            result_id,
            assessment_id,
            raw["expected_revision"],
            facts,
            evidence,
            {a["id"]: a["revision"] for a in result["assessments"]},
        )
        return JSONResponse(
            {"assessment_id": assessment_id, "revision": revision, "facts": facts},
            status_code=201,
        )

    async def handle_document_retry(self, document_id: str, request: Request):
        raw = await self._read_json(request)
        key = request.headers.get('idempotency-key', '')
        if not isinstance(raw, dict) or set(raw) != {'expected_generation'} or type(raw['expected_generation']) is not int or not re.fullmatch(limits.SUBMISSION_KEY_PATTERN, key):
            raise ProcessingError(errors.INVALID_REQUEST, 'Provide expected_generation and an Idempotency-Key.')
        result = await run_in_threadpool(self._data.retry_document, self._id(document_id), key, raw['expected_generation'])
        return JSONResponse(result, status_code=202)

    async def get_project_events(self, project_id: str, request: Request, after: int = 0):
        project_id = self._id(project_id)
        await run_in_threadpool(self._data.get_project, project_id)
        cursor = request.headers.get('last-event-id', str(after))
        if not cursor.isdecimal() or len(cursor) > 18:
            raise ProcessingError(errors.INVALID_REQUEST, 'Use a nonnegative event cursor.')

        async def events():
            sequence = int(cursor)
            while not await request.is_disconnected():
                rows = await run_in_threadpool(self._data.get_processing_events, project_id, sequence)
                for row in rows:
                    sequence = row['sequence']
                    yield f"id: {sequence}\nevent: progress\ndata: {json.dumps(row)}\n\n"
                if not rows:
                    yield ': keep-alive\n\n'
                await asyncio.sleep(1)
        return StreamingResponse(events(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


    async def handle_document_replacement(self, document_id: str, request: Request):
        key = request.headers.get('idempotency-key', '')
        generation = request.headers.get('expected-generation', '')
        filename = unquote(request.headers.get('x-filename', ''))
        if not re.fullmatch(limits.SUBMISSION_KEY_PATTERN, key) or not generation.isdecimal() or not filename or len(filename) > limits.DOCUMENT_NAME_LENGTH:
            raise ProcessingError(errors.INVALID_REQUEST, 'Provide a filename, expected generation and Idempotency-Key.')
        document_id = self._id(document_id)
        await run_in_threadpool(self._data.get_document, document_id)
        request_id = str(uuid4())
        descriptor = await run_in_threadpool(self._data.stage_document, request_id, filename)
        try:
            async for chunk in request.stream():
                await run_in_threadpool(self._data.save_staged_chunk, descriptor['document_id'], chunk)
            descriptor = await run_in_threadpool(self._data.complete_staged_document, descriptor['document_id'])
            result = await run_in_threadpool(self._data.replace_document, document_id, descriptor, key, int(generation))
            return JSONResponse(result, status_code=202)
        finally:
            await run_in_threadpool(self._data.discard_staged_documents, request_id)
