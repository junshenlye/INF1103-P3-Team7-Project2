import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

import httpx
from psycopg import sql
import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.managers.ai_manager import AIManager
from src.managers.data_manager import DataManager
from src.managers.logic_manager import LogicManager
from test_api import create, submit
from test_pipeline import parsed, extraction, process
from test_storage import image_bytes


def test_a_later_module_failure_preserves_validated_partial_result(data, settings):
    client = TestClient(create_app(settings, data))
    pid = create(client)
    modules = [
        {"module_title": title, "credit": 6, "file_fields": [field]}
        for title, field in [("First", "a"), ("Second", "b")]
    ]
    accepted = submit(
        client,
        pid,
        modules=modules,
        files={
            "a": ("a.png", image_bytes(), "image/png"),
            "b": ("b.png", image_bytes("blue"), "image/png"),
        },
    )
    assert accepted.status_code == 202

    async def run():
        def doc(_request):
            return httpx.Response(200, json=parsed())

        def gpt(request):
            user = json.loads(json.loads(request.content)["messages"][1]["content"])
            return extraction(
                request,
                "invalid_shape" if user["module_title"] == "Second" else "success",
            )

        async with (
            httpx.AsyncClient(
                base_url="http://doc", transport=httpx.MockTransport(doc)
            ) as dc,
            httpx.AsyncClient(
                base_url="http://gpt", transport=httpx.MockTransport(gpt)
            ) as gc,
        ):
            await AIManager(
                data,
                LogicManager(),
                dc,
                gc,
                replace(settings, gpt_api_key="fake", gpt_model="fake"),
            ).process_next_job()

    asyncio.run(run())
    project = client.get(f"/api/projects/{pid}").json()
    assert project["status"] == "Partial" and project["schedule"] is not None
    with data.pool.connection() as conn:
        rows = conn.execute("SELECT id,published FROM extraction_results").fetchall()
    assert len(rows) == 1 and rows[0]["published"]
    assert client.get(f"/api/results/{rows[0]['id']}").status_code == 200
    assert sum(bool(m.get("assessments")) for m in project["modules"]) == 1


def test_hard_crash_after_finalize_before_commit_is_reconciled(data, settings):
    pid = data.create_project("Crash test", 14).id
    code = """
import os
from src.managers.data_manager import DataManager
from src.managers.logic_manager import LogicManager
from test_storage import snapshot
pool=DataManager.create_pool(os.environ['STACKPLAN_TEST_DATABASE_URL'])
data=DataManager(pool,os.environ['CRASH_DOCUMENT_ROOT'],logic_manager=LogicManager())
command=snapshot(data,os.environ['CRASH_PROJECT_ID'])
finalize=data._finalize
def crash(descriptor):
    finalize(descriptor)
    os._exit(91)
data._finalize=crash
data.create_processing_job(command)
"""
    env = {
        **os.environ,
        "PYTHONPATH": str(Path.cwd())
        + os.pathsep
        + str(Path("tests/backend").resolve()),
        "CRASH_DOCUMENT_ROOT": str(data.root),
        "CRASH_PROJECT_ID": pid,
    }
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, timeout=20
    )
    assert result.returncode == 91, result.stderr.decode()
    assert data.get_project(pid).status == "Created"
    assert data.claim_next_job() is None
    finals = list((data.root / "originals").iterdir())
    assert len(finals) == 1
    past = (datetime.now(timezone.utc) - timedelta(hours=4)).timestamp()
    for p in data.root.rglob("*"):
        if p.is_file() or p.is_dir():
            os.utime(p, (past, past))
    data.cleanup_orphaned_files(datetime.now(timezone.utc) - timedelta(hours=2))
    assert not list((data.root / "originals").iterdir())
    assert not list((data.root / ".staging").iterdir())


def test_hard_worker_crash_restarts_as_interrupted_without_reclaim(data, settings):
    client = TestClient(create_app(settings, data))
    pid = create(client)
    jid = submit(client, pid).json()["job_id"]
    code = """
import os
from src.managers.data_manager import DataManager
from src.managers.logic_manager import LogicManager
pool=DataManager.create_pool(os.environ['STACKPLAN_TEST_DATABASE_URL'])
data=DataManager(pool,os.environ['CRASH_DOCUMENT_ROOT'],logic_manager=LogicManager())
assert data.claim_next_job() is not None
os._exit(92)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "CRASH_DOCUMENT_ROOT": str(data.root)},
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 92
    with data.pool.connection() as conn:
        conn.execute(
            "UPDATE processing_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=%s",
            (jid,),
        )
    with DataManager.create_pool(settings.database_url) as pool:
        restarted = DataManager(pool, data.root, logic_manager=LogicManager())
        assert restarted.cleanup_interrupted_jobs() == 1
        assert restarted.claim_next_job() is not None
    project = client.get(f"/api/projects/{pid}").json()
    assert project["status"] == "Processing" and project["schedule"] is None


def test_live_lease_survives_a_slow_provider_and_deadline_is_bounded(data, settings):
    client = TestClient(create_app(settings, data))
    pid = create(client)
    submit(client, pid)

    async def run():
        async def doc(_request):
            await asyncio.sleep(3.2)
            return httpx.Response(200, json=parsed())

        async with (
            httpx.AsyncClient(
                base_url="http://doc", transport=httpx.MockTransport(doc)
            ) as dc,
            httpx.AsyncClient(
                base_url="http://gpt", transport=httpx.MockTransport(extraction)
            ) as gc,
        ):
            cfg = replace(settings, gpt_api_key="fake", gpt_model="fake")
            task = asyncio.create_task(
                AIManager(data, LogicManager(), dc, gc, cfg).process_next_job()
            )
            await asyncio.sleep(3.1)
            assert await asyncio.to_thread(data.cleanup_interrupted_jobs) == 0
            await task

    asyncio.run(run())
    assert data.get_project(pid).status == "Ready"


def test_database_and_document_snapshot_restore_together(data, settings, tmp_path):
    container = os.getenv("STACKPLAN_TEST_CONTAINER")
    if not container:
        pytest.skip(
            "Set STACKPLAN_TEST_CONTAINER for the coordinated pg_dump/restore test."
        )
    assert container.startswith("stackplan-rebuild-test")
    client = TestClient(create_app(settings, data))
    pid = create(client)
    jid = submit(client, pid).json()["job_id"]
    asyncio.run(process(data, settings))
    before = client.get(f"/api/projects/{pid}").json()
    # No writers run while the database and volume are copied.
    volume = tmp_path / "snapshot"
    shutil.copytree(data.root, volume)
    source_name = urlparse(settings.database_url).path[1:]
    dump = subprocess.run(
        [
            "docker",
            "exec",
            container,
            "pg_dump",
            "-U",
            "stackplan_test",
            "--no-owner",
            "--no-acl",
            "-n",
            "stackplan",
            source_name,
        ],
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout
    restore_name = "stackplan_restore_" + uuid4().hex + "_test"
    with data.pool.connection() as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restore_name)))
    try:
        subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                container,
                "psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "stackplan_test",
                "-d",
                restore_name,
            ],
            input=dump,
            check=True,
            capture_output=True,
            timeout=30,
        )
        url = urlparse(settings.database_url)._replace(path="/" + restore_name)
        restored_settings = replace(
            settings, database_url=urlunparse(url), document_directory=volume
        )
        with DataManager.create_pool(restored_settings.database_url) as pool:
            restored = DataManager(pool, volume, logic_manager=LogicManager())
            restored_client = TestClient(create_app(restored_settings, restored))
            assert restored_client.get(f"/api/projects/{pid}").json() == before
            doc = restored.get_module_documents(
                jid, restored.get_job_modules(jid)[0].id
            )[0]
            assert (
                restored_client.get(f"/api/documents/{doc.id}/original").content
                == image_bytes()
            )
            assert (
                restored_client.get(f"/api/documents/{doc.id}/trace").status_code == 200
            )
    finally:
        with data.pool.connection() as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {}").format(sql.Identifier(restore_name))
            )


def test_original_lost_after_extraction_preserves_schedule_with_correct_warning_ids(
    data, settings
):
    client = TestClient(create_app(settings, data))
    pid = create(client)
    modules = [
        {"module_title": title, "credit": 6, "file_fields": [field]}
        for title, field in [("First", "a"), ("Second", "b")]
    ]
    jid = submit(
        client,
        pid,
        modules=modules,
        files={
            "a": ("a.png", image_bytes(), "image/png"),
            "b": ("b.png", image_bytes("blue"), "image/png"),
        },
    ).json()["job_id"]
    first_module = data.get_job_modules(jid)[0]
    first_doc = data.get_module_documents(jid, first_module.id)[0]

    async def run():
        first_extracted = asyncio.Event()
        def doc(_request):
            return httpx.Response(200, json=parsed())

        async def gpt(request):
            user = json.loads(json.loads(request.content)["messages"][1]["content"])
            if user["module_title"] == "Second":
                await first_extracted.wait()
                (data.root / first_doc.storage_key).unlink()
            else:
                first_extracted.set()
            return extraction(request)

        async with (
            httpx.AsyncClient(
                base_url="http://doc", transport=httpx.MockTransport(doc)
            ) as dc,
            httpx.AsyncClient(
                base_url="http://gpt", transport=httpx.MockTransport(gpt)
            ) as gc,
        ):
            await AIManager(
                data,
                LogicManager(),
                dc,
                gc,
                replace(settings, gpt_api_key="fake", gpt_model="fake"),
            ).process_next_job()

    asyncio.run(run())
    project = client.get(f"/api/projects/{pid}").json()
    assert project["status"] == "Ready" and project["schedule"] is not None
    assert project["issues"][0]["code"] == "source_missing"
    assert project["issues"][0]["module_id"] == first_module.id
    assert project["issues"][0]["document_id"] == first_doc.id
    assert data.get_published_results(pid)
