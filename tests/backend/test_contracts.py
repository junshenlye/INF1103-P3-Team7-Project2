from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict, replace
from http.server import ThreadingHTTPServer
from io import BytesIO
from threading import Thread
from types import SimpleNamespace
from uuid import uuid4
import asyncio
import json

import httpx
import pytest

from provider_handler import ProviderHandler
from src.config import limits
from src.contracts.provider_client import ProviderClient
from src.contracts.worker_data import WorkerData
from src.managers.ai_manager import AIManager
from src.managers.data_manager import DataManager
from src.managers.logic_manager import LogicManager
from src.errors.processing_error import ProcessingError
from src.models.documents.source_element import SourceElement
from src.config.settings import Settings
from test_api import create, submit
from test_pipeline import parsed, extraction
from src.main import create_app
from fastapi.testclient import TestClient


@asynccontextmanager
async def clients(kind, dispatch):
    if kind == "mock":
        async with httpx.AsyncClient(
            base_url="http://provider", transport=httpx.MockTransport(dispatch)
        ) as client:
            yield client
        return
    server = ThreadingHTTPServer(("127.0.0.1", 0), ProviderHandler)
    server.dispatch = dispatch
    thread = Thread(
        target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
    )
    thread.start()
    try:
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{server.server_port}", trust_env=False
        ) as client:
            yield client
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("kind", ["mock", "http"])
@pytest.mark.parametrize(
    "outcome", ["success", "http_error", "invalid_json", "oversized"]
)
def test_provider_clients_follow_the_same_behavioural_contract(kind, outcome, tmp_path):
    calls = []

    def dispatch(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/chat/completions"):
            body = json.loads(request.content)
            response_format = body["response_format"]
            assert response_format["type"] == "json_schema"
            assert response_format["json_schema"]["strict"] is True
            sent = json.loads(body["messages"][1]["content"])["source_elements"]
            assert response_format["json_schema"]["schema"]["$defs"]["source_id"][
                "enum"
            ] == sorted(e["id"] for e in sent)
        if outcome == "http_error":
            return httpx.Response(503, content=b"private provider detail")
        if outcome == "invalid_json":
            return httpx.Response(200, content=b"not JSON: private provider detail")
        if outcome == "oversized":
            return httpx.Response(
                200, content=b"x" * (limits.DOCLING_RESPONSE_BYTES + 1)
            )
        if request.url.path.endswith("/convert/file"):
            assert b"original-document-bytes" in request.content
            return httpx.Response(200, json=parsed())
        return extraction(request)

    async def exercise():
        async with clients(kind, dispatch) as client:
            assert isinstance(client, ProviderClient)
            settings = Settings(
                "postgresql://local/contracts_test",
                tmp_path,
                gpt_api_key="fake",
                gpt_model="fake",
            )
            ai = AIManager(None, LogicManager(), client, client, settings)
            document = {'id': str(uuid4()), 'module_id': "module", 'filename': "brief.pdf", 'media_type': "application/pdf", 'size': 23, 'checksum': "checksum"}
            element = SourceElement(
                str(uuid4()),
                document['id'],
                str(uuid4()),
                "Final exam in Week 12",
                [],
                "paragraph",
            )
            operations = [
                lambda: ai._call_docling(BytesIO(b"original-document-bytes"), document),
                lambda: ai._call_gpt("INF1103", [element.to_record()]),
            ]
            for operation in operations:
                if outcome == "success":
                    assert isinstance(await operation(), dict)
                elif outcome == "http_error":
                    with pytest.raises(httpx.HTTPStatusError) as failure:
                        await operation()
                    assert failure.value.response.status_code == 503
                else:
                    with pytest.raises(ProcessingError) as failure:
                        await operation()
                    assert failure.value.code == "invalid_extraction"
                    assert "private" not in failure.value.message
            # A response exposes only the two operations consumed by AIManager.
            async with client.stream(
                "POST", "/v1/convert/file", content=b"original-document-bytes"
            ) as response:
                assert isinstance(response, httpx.Response)

    asyncio.run(exercise())
    assert calls.count("/chat/completions") == 1  # No hidden transport retries.
    assert calls.count("/v1/convert/file") == 2


def test_persistence_accepts_a_connection_factory_with_only_the_pool_contract(
    data, settings
):
    leases = []

    @contextmanager
    def connection():
        leases.append(True)
        with data.pool.connection() as conn:
            yield conn

    substitute = SimpleNamespace(connection=connection)
    assert callable(data.pool.connection) and callable(substitute.connection)
    alternate = DataManager(substitute, settings.document_directory, logic_manager=LogicManager())
    project = alternate.create_project("Narrow pool contract", 14)
    assert asdict(alternate.get_project(project.id)) == asdict(data.get_project(project.id))
    assert len(leases) == 2


def test_worker_uses_only_its_consumer_persistence_contract_over_real_http(
    data, settings
):
    facade = SimpleNamespace(**{
        name: getattr(data, name) for name, value in WorkerData.__dict__.items()
        if callable(value) and not name.startswith('_')
    })
    assert isinstance(data, WorkerData)
    with pytest.raises(TypeError):
        WorkerData()
    client = TestClient(create_app(settings, data))
    project_id = create(client)
    submit(client, project_id)
    calls = []

    def dispatch(request):
        calls.append(request.url.path)
        return (
            httpx.Response(200, json=parsed())
            if request.url.path.endswith("/convert/file")
            else extraction(request)
        )

    async def run():
        async with clients("http", dispatch) as providers:
            ai = AIManager(
                facade,
                LogicManager(),
                providers,
                providers,
                replace(settings, gpt_api_key="fake", gpt_model="fake"),
            )
            assert await ai.process_next_job()
            assert not await ai.process_next_job()

    asyncio.run(run())
    project = client.get(f"/api/projects/{project_id}").json()
    assert project["status"] == "Ready" and project["schedule"]["weeks"][11]["items"]
    assert calls == ["/v1/convert/file", "/chat/completions"]
