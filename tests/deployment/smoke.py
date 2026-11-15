"""Black-box deployed-stack checks; no real provider calls or credentials."""

import json
import os
from urllib.request import Request, urlopen
from uuid import UUID


def request(url, body=None):
    req = Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    with urlopen(req, timeout=10) as response:
        return response.status, response.read()


def main():
    api = os.getenv("STACKPLAN_DEPLOYMENT_API_URL", "http://127.0.0.1:15185")
    frontend = os.getenv("STACKPLAN_DEPLOYMENT_FRONTEND_URL", "http://127.0.0.1:15185")
    for base in (api, frontend):
        assert json.loads(request(base + "/health")[1]) == {"status": "ok"}
    assert b"/static/app.js" in request(frontend)[1]
    assert b"document-workspace.js" in request(frontend + "/documents")[1]
    assert json.loads(request(api + "/ready")[1]) == {"status": "ok"}
    status, body = request(
        frontend + "/api/projects", {"name": "Deployment smoke test", "week_count": 14}
    )
    project = json.loads(body)
    assert status == 201 and UUID(project["id"])
    saved = json.loads(request(api + "/api/projects/" + project["id"])[1])
    assert (
        saved["name"] == project["name"]
        and saved["status"] == "Created"
        and saved["schedule"] is None
    )
    assert project["id"] in [
        p["id"] for p in json.loads(request(frontend + "/api/projects")[1])
    ]
    print("DEPLOYMENT RESULT: 7 checks passed, 0 failed")


if __name__ == "__main__":
    main()
