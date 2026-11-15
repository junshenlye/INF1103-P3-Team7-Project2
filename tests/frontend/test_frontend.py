"""Project 2 pages keep their design while all HTTP/storage belongs to managers."""

from fastapi.testclient import TestClient

from src.main import create_app


def test_preserved_project2_pages_and_registered_assets(data, settings):
    client = TestClient(create_app(settings, data))
    index = client.get("/")
    assert index.status_code == 200 and "/static/app.js" in index.text
    assert "/static/input-workspace.css" in index.text
    viewer = client.get("/documents")
    assert viewer.status_code == 200 and "document-workspace.js" in viewer.text
    for asset in (
        "app.js",
        "input-workspace.js",
        "document-workspace.js",
        "styles.css",
        "input-workspace.css",
        "document-workspace.css",
    ):
        response = client.get("/static/" + asset)
        assert (
            response.status_code == 200
            and response.headers["x-content-type-options"] == "nosniff"
        )
    assert client.get("/ready").json() == {"status": "ok"}


def test_page_assets_cannot_expose_documents_or_local_paths(data, settings):
    client = TestClient(create_app(settings, data))
    for path in (
        "/static/.env",
        "/static/../../.env",
        "/static/..%5C.env",
        "/static/documents/originals/test.pdf",
        "/frontend/templates/index.html",
    ):
        assert client.get(path).status_code == 404
    assert client.get("/static/app.js").headers["cache-control"] == "no-store"
