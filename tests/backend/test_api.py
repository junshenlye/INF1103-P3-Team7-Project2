from dataclasses import replace
from uuid import uuid4
import json

from fastapi.testclient import TestClient
import pytest

from src.main import create_app
from test_storage import image_bytes


@pytest.fixture
def client(data, settings):
    with TestClient(create_app(settings, data), raise_server_exceptions=False) as c:
        yield c


def create(client):
    response = client.post(
        "/api/projects", json={"name": "Browser trimester", "week_count": 14}
    )
    assert response.status_code == 201
    return response.json()["id"]


def submit(client, project_id, key=None, modules=None, files=None):
    return client.post(
        f"/api/projects/{project_id}/process",
        headers={"Idempotency-Key": key or str(uuid4())},
        data={
            "modules": json.dumps(
                modules
                or [{"module_title": "INF1103", "credit": 6, "file_fields": ["file_0"]}]
            )
        },
        files=files or {"file_0": ("brief.png", image_bytes(), "image/png")},
    )


def test_browser_shaped_acceptance_poll_and_response_recovery(client, data):
    project_id = create(client)
    key = str(uuid4())
    accepted = submit(client, project_id, key)
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["status"] == "queued"
    job_id = accepted.json()["job_id"]
    for _ in range(3):
        assert client.get(f"/api/jobs/{job_id}").json()["status"] == "queued"
    assert data.get_project(project_id).status == "Processing"
    assert submit(client, project_id, key).json()["job_id"] == job_id
    assert submit(client, project_id).status_code == 409
    assert client.get(f"/api/projects/{project_id}").json()["schedule"] is None
    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 404
    assert (
        client.patch(f"/api/projects/{project_id}/schedule", json={}).status_code == 404
    )


@pytest.mark.parametrize("module_title,credit", [("", 6), ("X", True), ("X", 101)])
def test_invalid_modules_leave_no_rows_or_files(client, data, module_title, credit):
    project_id = create(client)
    response = submit(
        client,
        project_id,
        modules=[
            {"module_title": module_title, "credit": credit, "file_fields": ["file_0"]}
        ],
    )
    assert response.status_code == 422, response.text
    assert data.get_project(project_id).status == "Created"
    assert not list((data.root / "originals").iterdir())
    assert not list((data.root / ".staging").iterdir())


def test_duplicate_normalized_title_and_duplicate_document(client, data):
    project_id = create(client)
    modules = [
        {"module_title": title, "credit": 6, "file_fields": [field]}
        for title, field in [(" INF  1103 ", "a"), ("inf 1103", "b")]
    ]
    files = {
        "a": ("a.png", image_bytes(), "image/png"),
        "b": ("b.png", image_bytes(), "image/png"),
    }
    assert submit(client, project_id, modules=modules, files=files).status_code == 409
    modules = [{"module_title": "INF1103", "credit": 6, "file_fields": ["a", "b"]}]
    assert (
        submit(client, project_id, modules=modules, files=files).json()["issues"][0][
            "code"
        ]
        == "duplicate_document"
    )
    assert data.get_project(project_id).status == "Created"
    assert not list((data.root / ".staging").iterdir())


def test_bad_document_json_multipart_and_ids_are_safe(client, data):
    project_id = create(client)
    response = submit(
        client,
        project_id,
        files={
            "file_0": (
                "passwd.png",
                b"secret provider message /tmp/password",
                "image/png",
            )
        },
    )
    assert response.status_code == 422
    assert "/tmp" not in response.text and "secret" not in response.text
    assert (
        client.post(
            "/api/projects",
            content='{"name": NaN}',
            headers={"Content-Type": "application/json"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/projects",
            content='{"name":"a","name":"b","week_count":14}',
            headers={"Content-Type": "application/json"},
        ).status_code
        == 422
    )
    response = client.post(
        f"/api/projects/{project_id}/process",
        content=b"--boundary\r\n",
        headers={
            "Content-Type": "multipart/form-data; boundary=boundary",
            "Idempotency-Key": str(uuid4()),
        },
    )
    assert response.status_code == 422, response.text
    assert client.get("/api/documents/not-a-uuid/original").status_code == 404
    assert client.get("/api/documents/../../etc/passwd").status_code == 404
    assert not list((data.root / ".staging").iterdir())


def test_streamed_total_limit_without_content_length(data, settings):
    limited = replace(settings, request_bytes=1024, document_bytes=1024)
    client = TestClient(create_app(limited, data), raise_server_exceptions=False)
    project_id = create(client)
    boundary = "example"
    payload = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="modules"\r\n\r\n'
        + "x" * 1500
        + f"\r\n--{boundary}--\r\n"
    ).encode()

    def chunks():
        for offset in range(0, len(payload), 37):
            yield payload[offset : offset + 37]

    response = client.post(
        f"/api/projects/{project_id}/process",
        content=chunks(),
        headers={
            "Idempotency-Key": str(uuid4()),
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    assert response.status_code == 413, response.text
    assert data.get_project(project_id).status == "Created"
    assert not list((data.root / ".staging").iterdir())


@pytest.mark.parametrize("kind", ["pdf", "jpeg"])
def test_real_pdf_and_jpeg_content_is_accepted(client, data, kind):
    from io import BytesIO
    from pypdf import PdfWriter
    from PIL import Image

    stream = BytesIO()
    if kind == "pdf":
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(stream)
        filename = "brief.pdf"
        media = "application/pdf"
    else:
        Image.new("RGB", (32, 32), "white").save(stream, format="JPEG")
        filename = "brief.jpeg"
        media = "image/jpeg"
    pid = create(client)
    response = submit(
        client, pid, files={"file_0": (filename, stream.getvalue(), media)}
    )
    assert response.status_code == 202, response.text
    document = data.get_module_documents(
        response.json()["job_id"], data.get_job_modules(response.json()["job_id"])[0].id
    )[0]
    assert (
        client.get(f"/api/documents/{document.id}/original").content
        == stream.getvalue()
    )


def test_public_form_limits_use_the_same_configuration_and_domain_bounds(
    client, data, settings
):
    from src.config import limits

    actual = client.get("/api/limits").json()
    assert actual == {
        "request_bytes": settings.request_bytes,
        "document_bytes": settings.document_bytes,
        "module_count": limits.MODULE_COUNT,
        "documents_per_module": limits.DOCUMENTS_PER_MODULE,
        "project_name_length": limits.PROJECT_NAME_LENGTH,
        "module_title_length": limits.MODULE_TITLE_LENGTH,
        "credit": limits.CREDIT,
        "week_count": limits.WEEK_COUNT,
        "media_types": list(limits.MEDIA_TYPES),
    }
    pid = create(client)
    modules = [
        {"module_title": str(i), "credit": 1, "file_fields": [f"file_{i}"]}
        for i in range(limits.MODULE_COUNT + 1)
    ]
    response = submit(client, pid, modules=modules)
    assert response.status_code == 422 and data.get_project(pid).status == "Created"
    assert not list((data.root / ".staging").iterdir())


def test_sql_constraints_and_public_limits_share_the_same_persisted_bounds(
    data, settings, client
):
    from src.config import limits
    import psycopg
    from uuid import uuid4

    created = data.create_project("x" * limits.PROJECT_NAME_LENGTH, limits.WEEK_COUNT)
    assert created.week_count == limits.WEEK_COUNT
    with pytest.raises(psycopg.errors.CheckViolation):
        data.create_project("x" * (limits.PROJECT_NAME_LENGTH + 1), 1)
    with pytest.raises(psycopg.errors.CheckViolation):
        data.create_project("x", limits.WEEK_COUNT + 1)
    pid = create(client)
    accepted = submit(
        client,
        pid,
        modules=[
            {
                "module_title": "x" * limits.MODULE_TITLE_LENGTH,
                "credit": limits.CREDIT,
                "file_fields": ["file_0"],
            }
        ],
    )
    assert accepted.status_code == 202
    job_id = accepted.json()["job_id"]
    with data.pool.connection() as conn:
        for title, credit, position in [
            ("bad credit", limits.CREDIT + 1, 1),
            ("bad position", 1, limits.MODULE_COUNT),
            ("x" * (limits.MODULE_TITLE_LENGTH + 1), 1, 1),
        ]:
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(
                    "INSERT INTO modules(id,project_id,job_id,module_title,normalized_title,credit,position) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (str(uuid4()), pid, job_id, title, title, credit, position),
                )
        definitions = conn.execute(
            "SELECT pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE conrelid='stackplan.documents'::regclass AND contype='c'"
        ).fetchall()
    assert any(str(limits.DOCUMENT_BYTES) in row["definition"] for row in definitions)
