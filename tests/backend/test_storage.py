from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
import os
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image

from src.managers.logic_manager import LogicManager
from src.errors.processing_error import ProcessingError


def image_bytes(color="white"):
    buffer = BytesIO()
    Image.new("RGB", (32, 32), color).save(buffer, format="PNG")
    return buffer.getvalue()


def snapshot(data, project_id, key=None, duplicate=False):
    request_id = str(uuid4())
    docs = {}
    for field in ["a", "b"] if duplicate else ["a"]:
        d = data.stage_document(request_id, "../../brief.png")
        for pos in range(0, len(image_bytes()), 7):
            data.save_staged_chunk(d['document_id'], image_bytes()[pos : pos + 7])
        data.complete_staged_document(d['document_id'])
        docs[field] = d
    modules = LogicManager().validate_submission(
        [{"module_title": " INF 1103 ", "credit": 6, "file_fields": list(docs)}], docs
    )
    return {'project_id': project_id, 'submission_key': key or str(uuid4()), 'modules': modules, 'document_fields': docs}


def test_staging_acceptance_idempotency_restart(data):
    project = data.create_project("Test", 14)
    command = snapshot(data, project.id)
    job = data.create_processing_job(command)
    for doc in command['document_fields'].values():
        data.discard_staged_documents(doc['request_id'])
        assert not Path(doc['final_key']).is_absolute()
        assert doc['filename'] == "brief.png"
        with data.open_document(doc['document_id']) as stream:
            assert stream.read() == image_bytes()
    assert data.get_project(project.id).status == "Processing"
    assert data.get_submission(project.id, command['submission_key']).id == job.id
    repeated = snapshot(data, project.id, command['submission_key'])
    assert data.create_processing_job(repeated).id == job.id
    for doc in repeated['document_fields'].values():
        data.discard_staged_documents(doc['request_id'])
    assert len(list(data.root.joinpath("originals").iterdir())) == 1


def test_duplicate_checksum_rolls_back(data):
    project = data.create_project("Test", 14)
    command = snapshot(data, project.id, duplicate=True)
    with pytest.raises(ProcessingError, match="duplicate documents"):
        data.create_processing_job(command)
    for d in command['document_fields'].values():
        data.discard_staged_documents(d['request_id'])
    assert data.get_project(project.id).status == "Created"
    with data.pool.connection() as c:
        for table in ("modules", "documents", "processing_jobs"):
            assert c.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0
    assert not list((data.root / "originals").iterdir())
    assert not list((data.root / ".staging").iterdir())


def test_finalize_failure_compensates(data, monkeypatch):
    project = data.create_project("Test", 14)
    command = snapshot(data, project.id)

    def fail(d):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(data, "_finalize", fail)
    with pytest.raises(OSError):
        data.create_processing_job(command)
    assert data.get_project(project.id).status == "Created"
    assert not list((data.root / "originals").iterdir())


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_bucket_acceptance(data, same_key):
    project = data.create_project("Test", 14)
    first = snapshot(data, project.id)
    second = snapshot(data, project.id, first['submission_key'] if same_key else None)

    def accept(command):
        try:
            return data.create_processing_job(command).id
        except ProcessingError as exc:
            return exc.code
        finally:
            for d in command['document_fields'].values():
                data.discard_staged_documents(d['request_id'])

    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(accept, [first, second]))
    if same_key:
        assert outcomes[0] == outcomes[1]
    else:
        assert outcomes.count("project_frozen") == 1
    assert len(list((data.root / "originals").iterdir())) == 1


def test_path_containment_and_symlink(data, tmp_path):
    for key in (
        "/etc/passwd",
        "../other",
        "originals/../../etc/passwd",
        "unknown/file",
        "originals\\bad",
    ):
        with pytest.raises(ProcessingError):
            data._resolve(key)
    outside = tmp_path / "outside"
    outside.mkdir()
    (data.root / "originals" / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ProcessingError):
        data._resolve("originals/escape/secret")


def test_content_checks_and_document_bounds(data):
    req = str(uuid4())
    d = data.stage_document(req, "wrong.png")
    data.save_staged_chunk(d['document_id'], b"%PDF-1.7 fake")
    with pytest.raises(ProcessingError):
        data.complete_staged_document(d['document_id'])
    data.discard_staged_documents(req)
    data.document_bytes = 10
    d = data.stage_document(req, "x.png")
    with pytest.raises(ProcessingError):
        data.save_staged_chunk(d['document_id'], b"x" * 11)
    data.discard_staged_documents(req)
    assert not list((data.root / ".staging").iterdir())


def test_aged_orphan_cleanup_preserves_registered_and_recent(data):
    p = data.create_project("Test", 14)
    command = snapshot(data, p.id)
    data.create_processing_job(command)
    for d in command['document_fields'].values():
        data.discard_staged_documents(d['request_id'])
    old = data.root / "originals" / "orphan.png"
    old.write_bytes(image_bytes())
    recent = data.root / "originals" / "recent.png"
    recent.write_bytes(image_bytes())
    stage = data.root / ".staging" / str(uuid4())
    stage.mkdir()
    (stage / "partial").write_bytes(b"x")
    past = (datetime.now(timezone.utc) - timedelta(hours=3)).timestamp()
    for path in [
        old,
        stage / "partial",
        stage,
        *[data.root / d['final_key'] for d in command['document_fields'].values()],
    ]:
        os.utime(path, (past, past))
    removed = data.cleanup_orphaned_files(
        datetime.now(timezone.utc) - timedelta(hours=2)
    )
    assert "originals/orphan.png" in removed and not old.exists()
    assert recent.exists() and not stage.exists()
    assert all(
        (data.root / d['final_key']).exists() for d in command['document_fields'].values()
    )


def test_claim_is_exclusive_and_expired_jobs_can_resume(data):
    project = data.create_project("Test", 14)
    command = snapshot(data, project.id)
    data.create_processing_job(command)
    with ThreadPoolExecutor(2) as pool:
        jobs = list(pool.map(lambda _: data.claim_next_job(), range(2)))
    assert sum(j is not None for j in jobs) == 1
    job = next(j for j in jobs if j)
    with data.pool.connection() as c:
        c.execute(
            "UPDATE processing_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=%s",
            (job.id,),
        )
    assert data.cleanup_interrupted_jobs() == 1
    assert data.get_project(project.id).status == "Processing"
    assert data.claim_next_job() is not None
    with pytest.raises(ProcessingError):
        data.save_job_heartbeat(job)


def test_later_finalize_failure_compensates_already_finalized_files(data, monkeypatch):
    project = data.create_project("Two files", 14)
    request_id = str(uuid4())
    docs = {}
    for field, color in [("a", "white"), ("b", "blue")]:
        d = data.stage_document(request_id, field + ".png")
        data.save_staged_chunk(d['document_id'], image_bytes(color))
        data.complete_staged_document(d['document_id'])
        docs[field] = d
    modules = LogicManager().validate_submission(
        [{"module_title": "A", "credit": 6, "file_fields": ["a", "b"]}], docs
    )
    command = {'project_id': project.id, 'submission_key': str(uuid4()), 'modules': modules, 'document_fields': docs}
    finalize = data._finalize
    calls = 0

    def fail_second(d):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected disk failure")
        finalize(d)

    monkeypatch.setattr(data, "_finalize", fail_second)
    with pytest.raises(OSError):
        data.create_processing_job(command)
    data.discard_staged_documents(request_id)
    assert data.get_project(project.id).status == "Created"
    assert not list((data.root / "originals").iterdir())
    with data.pool.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM documents").fetchone()["n"] == 0


def test_acceptance_and_cleanup_coordinate_across_connections(data, monkeypatch):
    from threading import Event

    project = data.create_project("Concurrent cleanup", 14)
    command = snapshot(data, project.id)
    old = (datetime.now(timezone.utc) - timedelta(hours=4)).timestamp()
    for d in command['document_fields'].values():
        os.utime(data.root / d['staging_key'], (old, old))
    renamed = Event()
    release = Event()
    finalize = data._finalize

    def pause(d):
        finalize(d)
        renamed.set()
        assert release.wait(2)

    monkeypatch.setattr(data, "_finalize", pause)
    with ThreadPoolExecutor(2) as pool:
        accepted = pool.submit(data.create_processing_job, command)
        assert renamed.wait(2)
        cleanup = pool.submit(
            data.cleanup_orphaned_files, datetime.now(timezone.utc) - timedelta(hours=2)
        )
        assert not cleanup.done()
        release.set()
        accepted.result()
        cleanup.result()
    assert all(
        (data.root / d['final_key']).exists() for d in command['document_fields'].values()
    )
