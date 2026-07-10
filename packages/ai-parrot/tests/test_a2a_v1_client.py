"""Unit tests for the A2AClient v1.0 upgrade (FEAT-272 TASK-1717)."""
from parrot.a2a.client import A2AClient
from parrot.a2a.models import TaskState


class _FakeResp:
    def __init__(self, status=200, payload=None):
        self.status = status
        self._payload = payload or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    async def json(self):
        return self._payload


class _FakeSession:
    """Minimal fake aiohttp session driven by a routing table."""

    def __init__(self, routes):
        # routes: dict[(method, url_suffix)] -> _FakeResp or callable
        self.routes = routes
        self.calls = []

    def _resolve(self, method, url):
        for (m, suffix), resp in self.routes.items():
            if m == method and url.endswith(suffix):
                return resp
        return _FakeResp(status=404, payload={"error": "not found"})

    def get(self, url, **kwargs):
        self.calls.append(("GET", url))
        return self._resolve("GET", url)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url))
        return self._resolve("POST", url)

    def delete(self, url, **kwargs):
        self.calls.append(("DELETE", url))
        return self._resolve("DELETE", url)


V1_CARD = {
    "name": "Remote", "description": "d", "version": "1.0",
    "supportedInterfaces": [{"url": "https://a.com/a2a", "protocolBinding": "JSONRPC",
                             "protocolVersion": "1.0"}],
    "capabilities": {"streaming": True},
    "defaultInputModes": ["text/plain"], "defaultOutputModes": ["text/plain"],
    "skills": [],
}

V03_CARD = {
    "name": "Remote", "description": "d", "version": "1.0",
    "url": "https://a.com/a2a", "preferredTransport": "JSONRPC",
    "protocolVersion": "0.3.0",
    "capabilities": {"streaming": True},
    "defaultInputModes": ["text/plain"], "defaultOutputModes": ["text/plain"],
    "skills": [],
}


class TestA2AClientV1:
    def test_sends_version_header(self):
        client = A2AClient("http://localhost:8080")
        assert client._default_headers.get("A2A-Version") == "1.0"

    async def test_discover_tries_v1_endpoint_first(self):
        client = A2AClient("http://localhost:8080")
        client._session = _FakeSession({
            ("GET", "/.well-known/agent-card.json"): _FakeResp(200, V1_CARD),
        })
        card = await client.discover()
        assert client._server_version == "1.0"
        assert card.url == "https://a.com/a2a"
        # The v1.0 endpoint must have been the first GET.
        assert client._session.calls[0][1].endswith("/.well-known/agent-card.json")

    async def test_discover_falls_back_to_v03(self):
        client = A2AClient("http://localhost:8080")
        client._session = _FakeSession({
            ("GET", "/.well-known/agent-card.json"): _FakeResp(404, {}),
            ("GET", "/.well-known/agent.json"): _FakeResp(200, V03_CARD),
        })
        card = await client.discover()
        assert client._server_version == "0.3"
        assert card.url == "https://a.com/a2a"

    async def test_deserialize_v1_task(self):
        client = A2AClient("http://localhost:8080")
        task = client._parse_task({
            "id": "t1", "contextId": "c1",
            "status": {"state": "TASK_STATE_COMPLETED"},
            "artifacts": [], "history": [],
        })
        assert task.status.state == TaskState.COMPLETED

    async def test_deserialize_v03_task(self):
        client = A2AClient("http://localhost:8080")
        task = client._parse_task({
            "id": "t1", "contextId": "c1",
            "status": {"state": "completed"},
            "artifacts": [], "history": [],
        })
        assert task.status.state == TaskState.COMPLETED

    async def test_push_config_crud(self):
        client = A2AClient("http://localhost:8080")
        client._session = _FakeSession({
            ("POST", "/pushNotificationConfigs"): _FakeResp(200, {
                "id": "c1", "taskId": "t1", "url": "https://ex.com/h"}),
            ("GET", "/pushNotificationConfigs/c1"): _FakeResp(200, {
                "id": "c1", "taskId": "t1", "url": "https://ex.com/h"}),
            ("GET", "/pushNotificationConfigs"): _FakeResp(200, {
                "configs": [{"id": "c1", "taskId": "t1", "url": "https://ex.com/h"}]}),
            ("DELETE", "/pushNotificationConfigs/c1"): _FakeResp(200, {"deleted": True}),
        })
        created = await client.create_push_config("t1", "https://ex.com/h")
        assert created.id == "c1"
        got = await client.get_push_config("t1", "c1")
        assert got.url == "https://ex.com/h"
        lst = await client.list_push_configs("t1")
        assert len(lst) == 1
        assert await client.delete_push_config("t1", "c1") is True
