"""Isolated browser test stack: real API, PostgreSQL and worker; fake providers."""

import asyncio
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import time
from urllib.parse import urlparse

import httpx
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from src.main import create_app
from src.managers.ai_manager import AIManager
from src.managers.data_manager import DataManager
from src.managers.logic_manager import LogicManager
from src.config.settings import Settings
from test_pipeline import parsed, parsed_table, extraction
from test_storage import image_bytes


def main():
    url = os.environ["STACKPLAN_TEST_DATABASE_URL"]
    if not urlparse(url).path.endswith("_test"):
        raise ValueError("Disposable test database required.")
    directory = tempfile.TemporaryDirectory(prefix="stackplan-browser-")
    settings = Settings(
        url,
        Path(directory.name) / "documents",
        request_bytes=8 * 1024 * 1024,
        document_bytes=2 * 1024 * 1024,
        gpt_api_key="fake",
        gpt_model="fake",
    )
    pool = DataManager.create_pool(url)
    data = DataManager(
        pool,
        settings.document_directory,
        settings.document_bytes,
        settings.lease_seconds, logic_manager=LogicManager())
    with pool.connection() as conn:
        conn.execute("DROP SCHEMA IF EXISTS stackplan CASCADE")
    data.create_schema()
    controls = {"mode": "success", "docling_calls": 0, "gpt_calls": 0}
    app = create_app(settings, data)
    from fastapi import Request
    from fastapi.responses import Response

    @app.post("/__test__/mode")
    async def mode(request: Request):
        controls["mode"] = (await request.json())["mode"]
        return controls

    @app.get("/__test__/counts")
    def counts():
        with pool.connection() as conn:
            jobs = conn.execute("SELECT count(*) AS n FROM processing_jobs").fetchone()[
                "n"
            ]
            published = conn.execute(
                "SELECT count(*) AS n FROM extraction_results WHERE published"
            ).fetchone()["n"]
        return {**controls, "jobs": jobs, "published": published}

    @app.get("/__test__/image")
    def image():
        return Response(image_bytes(), media_type="image/png")

    @app.post("/__test__/missing/{project_id}")
    def missing(project_id: str):
        project = data.get_project(project_id)
        document = data.get_module_documents(
            project.job_id, data.get_job_modules(project.job_id)[0].id
        )[0]
        (data.root / document.storage_key).unlink()
        return {"document_id": document.id}

    stop = threading.Event()

    async def worker():
        def doc(request):
            assert image_bytes() in request.content
            controls["docling_calls"] += 1
            return httpx.Response(200, json=parsed_table() if controls["mode"] == "table" else parsed())

        async def gpt(request):
            controls["gpt_calls"] += 1
            await asyncio.sleep(0.1)
            while controls["mode"] == "hold" and not stop.is_set():
                await asyncio.sleep(0.05)
            module_title = json.loads(json.loads(request.content)["messages"][1]["content"])["module_title"]
            if controls["mode"] == "failure" or (controls["mode"] == "selective_failure" and module_title == "Bad"):

                return httpx.Response(503, text="private provider error")
            return extraction(request, controls["mode"])

        async with (
            httpx.AsyncClient(
                base_url="http://doc", transport=httpx.MockTransport(doc)
            ) as dc,
            httpx.AsyncClient(
                base_url="http://gpt", transport=httpx.MockTransport(gpt)
            ) as gc,
        ):
            ai = AIManager(data, LogicManager(), dc, gc, settings)
            while not stop.is_set():
                await ai.process_next_job()
                await asyncio.sleep(0.1)

    worker_thread = threading.Thread(target=lambda: asyncio.run(worker()), daemon=True)
    worker_thread.start()
    api_port = int(os.getenv("STACKPLAN_BROWSER_API_PORT", "18083"))
    api = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=api_port, log_level="warning")
    )
    api_thread = threading.Thread(target=api.run, daemon=True)
    api_thread.start()
    while not api.started:
        time.sleep(0.02)
    print("BROWSER_TEST_STACK_READY", flush=True)

    def shutdown(*_args):
        stop.set()
        api.should_exit = True

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        while not stop.wait(0.1):
            if not api_thread.is_alive():
                raise RuntimeError("Browser API exited unexpectedly.")
    finally:
        stop.set()
        api.should_exit = True
        worker_thread.join(5)
        api_thread.join(5)
        pool.close()
        directory.cleanup()


if __name__ == "__main__":
    main()
