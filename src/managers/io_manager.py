"""HTTP boundary for the browser workspace and project dashboard."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
from pathlib import Path

from src.config import limits
from src.errors.processing_error import ProcessingError
from src.serialization.event_cursor import parse_event_cursor
from src.serialization.processing_event import encode_processing_event


class IOManager:
    """Serve the frontend and expose the currently available project API."""

    def __init__(self, data_manager, logic_manager, frontend_directory=None):
        self.data = data_manager
        self.logic = logic_manager
        self.frontend = Path(frontend_directory or Path(__file__).parents[2] / "frontend")

    def get_application(self):
        from fastapi import FastAPI, HTTPException, Request
        from fastapi.responses import FileResponse, JSONResponse

        app = FastAPI(title="Stackplan", docs_url=None, redoc_url=None)

        @app.exception_handler(ProcessingError)
        async def domain_error(_request, error):
            return JSONResponse({"issues": [{"code": error.code, "message": error.message, "scope": error.scope}]}, status_code=422)

        @app.get("/health")
        @app.get("/ready")
        async def health():
            return {"status": "ok"}

        @app.get("/")
        async def index():
            return FileResponse(self.frontend / "templates" / "index.html", headers={"Cache-Control": "no-store"})

        @app.get("/documents")
        async def documents():
            return FileResponse(self.frontend / "templates" / "documents.html", headers={"Cache-Control": "no-store"})

        @app.get("/static/{asset_name}")
        async def asset(asset_name: str):
            if Path(asset_name).name != asset_name:
                raise HTTPException(status_code=404)
            path = self.frontend / "static" / asset_name
            if not path.is_file():
                raise HTTPException(status_code=404)
            return FileResponse(path, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

        @app.get("/api/limits")
        async def get_limits():
            return {"request_bytes": limits.REQUEST_BYTES, "document_bytes": limits.DOCUMENT_BYTES, "module_count": limits.MODULE_COUNT, "documents_per_module": limits.DOCUMENTS_PER_MODULE, "project_name_length": limits.PROJECT_NAME_LENGTH, "module_title_length": limits.MODULE_TITLE_LENGTH, "credit": limits.CREDIT, "week_count": limits.WEEK_COUNT, "media_types": limits.MEDIA_TYPES}

        @app.get("/api/projects")
        async def projects():
            return self.data.get_projects()

        @app.post("/api/projects", status_code=201)
        async def create_project(request: Request):
            command = self.logic.validate_project(await request.json())
            return _json(self.data.create_project(command.name, command.week_count))

        @app.get("/api/projects/{project_id}")
        async def project(project_id: str):
            return _json(self.data.get_project(project_id))

        @app.get("/api/projects/{project_id}/events")
        async def project_events(project_id: str, request: Request, after: int = 0):
            return await self.get_project_events(project_id, request, after)

        return app

    async def get_project_events(self, project_id: str, request, after: int = 0):
        """Stream project progress events, resuming after the supplied cursor."""
        from starlette.concurrency import run_in_threadpool
        from starlette.responses import StreamingResponse

        cursor = parse_event_cursor(
            after, last_event_id=request.headers.get("last-event-id")
        )
        await run_in_threadpool(self.data.get_project, project_id)

        async def events():
            sequence = cursor
            while not await request.is_disconnected():
                rows = await run_in_threadpool(
                    self.data.get_processing_events, project_id, sequence
                )
                for event in rows:
                    sequence = event.sequence
                    yield encode_processing_event(event)
                if not rows:
                    yield ": keep-alive\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )


def _json(value):
    return asdict(value) if is_dataclass(value) else value
