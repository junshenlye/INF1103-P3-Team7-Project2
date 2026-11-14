"""Black-box checks for a deployed application stack.

Run against a stack started with Docker Compose (see README). The checks use
only the public HTTP interface: health and readiness, both pages, and creating
a project and reading it back through PostgreSQL. They never call a document
or AI provider and need no credentials.

Usage: python tests/deployment/smoke.py
Set STACKPLAN_DEPLOYMENT_URL to target a URL other than http://127.0.0.1:5173.
"""

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

DEFAULT_URL = "http://127.0.0.1:5173"


def request(url, body=None):
    """Return the status and body of a GET, or a JSON POST when ``body`` is given."""
    req = Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urlopen(req, timeout=10) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def run_checks(base):
    """Yield (name, passed, detail) for each deployment check in order."""
    for path in ("/health", "/ready"):
        status, body = request(base + path)
        yield path, status == 200 and json.loads(body) == {"status": "ok"}, f"HTTP {status}"

    status, body = request(base + "/")
    yield "trimester page", status == 200 and b"/static/app.js" in body, f"HTTP {status}"

    status, body = request(base + "/documents")
    yield "documents page", status == 200 and b"document-workspace.js" in body, f"HTTP {status}"

    name = f"Deployment smoke {uuid4().hex[:8]}"
    status, body = request(base + "/api/projects", {"name": name, "week_count": 14})
    project = json.loads(body) if status == 201 else {}
    try:
        project_id = str(UUID(project.get("id", "")))
    except ValueError:
        project_id = None
    yield "create project", status == 201 and project_id is not None, f"HTTP {status}"
    if project_id is None:
        return

    status, body = request(base + "/api/projects/" + project_id)
    saved = json.loads(body) if status == 200 else {}
    yield (
        "read project",
        saved.get("id") == project_id and saved.get("name") == name and saved.get("status") == "Created",
        f"HTTP {status}",
    )

    status, body = request(base + "/api/projects")
    listed = [p.get("id") for p in json.loads(body)] if status == 200 else []
    yield "list projects", project_id in listed, f"HTTP {status}"


def main():
    base = os.getenv("STACKPLAN_DEPLOYMENT_URL", DEFAULT_URL).rstrip("/")
    passed = failed = 0
    try:
        for name, ok, detail in run_checks(base):
            print(f"{'PASS' if ok else 'FAIL'} {name} ({detail})")
            passed += ok
            failed += not ok
    except URLError as error:
        print(f"FAIL could not reach {base}: {error.reason}")
        failed += 1
    print(f"DEPLOYMENT RESULT: {passed} checks passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
