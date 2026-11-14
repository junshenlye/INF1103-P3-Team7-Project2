"""HTTP boundary for the browser workspace and project dashboard."""

from dataclasses import asdict, is_dataclass
from pathlib import Path

from src.config import limits
from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.serialization.request_json import read_request_json


class IOManager:
    """Serve the frontend and expose the currently available project API."""

    def __init__(self, data_manager, logic_manager, frontend_directory=None):
        self.data = data_manager
        self.logic = logic_manager
        self.frontend = Path(frontend_directory or Path(__file__).parents[2] / "frontend")

    def get_application(self, *, lifespan=None):
        from fastapi import FastAPI, HTTPException, Request
        from fastapi.responses import FileResponse, JSONResponse
        from starlette.concurrency import run_in_threadpool

        app = FastAPI(lifespan=lifespan, title="Stackplan", docs_url=None, redoc_url=None)

        @app.exception_handler(ProcessingError)
        async def domain_error(_request, error):
            status = 413 if error.code == error_codes.REQUEST_TOO_LARGE else 422
            return JSONResponse({"issues": [{"code": error.code, "message": error.message, "scope": error.scope}]}, status_code=status)

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
            raw = await read_request_json(
                request.headers.get("content-type", ""), request.stream()
            )
            command = self.logic.validate_project(raw)
            project = await run_in_threadpool(
                self.data.create_project, command.name, command.week_count
            )
            return _json(project)

        @app.get("/api/projects/{project_id}")
        async def project(project_id: str):
            return _json(self.data.get_project(project_id))

        return app


def _json(value):
    return asdict(value) if is_dataclass(value) else value
