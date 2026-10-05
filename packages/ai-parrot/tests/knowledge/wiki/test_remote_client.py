import asyncio
import json

import pytest
from aiohttp import web

from parrot.knowledge.wiki.project import WikiRemoteConfig
from parrot.knowledge.wiki.remote import READ_ONLY_TOOLS, RemoteWikiClient, RemoteWikiError, _decode_body


class Fake:
    def __init__(self) -> None:
        self.seen: list[dict[str, str]] = []
        self.session = "s1"
        self.forget = False
        self.calls = 0
        self.sse = False
        self.delay = 0.0
        self.error = False

    async def handle(self, request: web.Request) -> web.StreamResponse:
        self.seen.append(dict(request.headers))
        body = await request.json()
        if request.headers.get("Authorization") != "Bearer t0k3n":
            return web.Response(status=401)
        if self.delay:
            await asyncio.sleep(self.delay)
        if body["method"] == "initialize":
            self.session = f"s{len(self.seen)}"
            return web.json_response(
                {"jsonrpc": "2.0", "id": body["id"], "result": {"protocolVersion": "2025-03-26"}},
                headers={"Mcp-Session-Id": self.session},
            )
        if body["method"].startswith("notifications/"):
            return web.Response(status=202)
        if self.forget and request.headers.get("Mcp-Session-Id") != self.session:
            return web.Response(status=404)
        self.calls += 1
        if self.error:
            return web.json_response(
                {"jsonrpc": "2.0", "id": body.get("id"), "error": {"message": "tool failed"}},
                status=200,
            )
        response = {"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "text", "text": "hello"}]}}
        if self.sse:
            return web.Response(
                body=f"event: message\ndata: {json.dumps(response)}\n\n".encode(),
                content_type="text/event-stream",
            )
        return web.json_response(response)


@pytest.fixture
async def server():
    fake = Fake()
    app = web.Application()
    app.router.add_post("/mcp/w", fake.handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    yield fake, f"http://127.0.0.1:{port}/mcp/w"
    await runner.cleanup()


async def test_roundtrip_and_headers(server, monkeypatch):
    fake, url = server
    monkeypatch.setenv("WIKITOOLKIT_TOKEN", "t0k3n")
    async with RemoteWikiClient(WikiRemoteConfig(url=url), actor="human:t") as client:
        assert await client.call_tool_text("wiki_query", {"question": "x"}) == "hello"
    assert fake.seen[-1]["X-Wiki-Actor"] == "human:t"
    assert fake.seen[-1]["Authorization"] == "Bearer t0k3n"
    assert "text/event-stream" in fake.seen[-1]["Accept"]
    assert fake.seen[-1]["MCP-Protocol-Version"] == "2025-03-26"


async def test_sse_roundtrip_and_list_tools(server, monkeypatch):
    fake, url = server
    monkeypatch.setenv("WIKITOOLKIT_TOKEN", "t0k3n")
    async with RemoteWikiClient(WikiRemoteConfig(url=url), actor="a") as client:
        fake.sse = True
        assert await client.call_tool_text("wiki_query", {}) == "hello"
        assert await client.list_tools() == []


async def test_error_mapping(server, monkeypatch):
    _, url = server
    monkeypatch.delenv("WIKITOOLKIT_TOKEN", raising=False)
    with pytest.raises(RemoteWikiError) as error:
        RemoteWikiClient(WikiRemoteConfig(url=url), actor="a")
    assert error.value.code == "token_missing"

    monkeypatch.setenv("WIKITOOLKIT_TOKEN", "bad")
    with pytest.raises(RemoteWikiError) as error:
        async with RemoteWikiClient(WikiRemoteConfig(url=url), actor="a"):
            pass
    assert error.value.code == "unauthorized"


async def test_missing_wiki_maps_to_not_found(server, monkeypatch):
    _, url = server
    monkeypatch.setenv("WIKITOOLKIT_TOKEN", "t0k3n")
    with pytest.raises(RemoteWikiError) as error:
        async with RemoteWikiClient(WikiRemoteConfig(url=f"{url}-missing"), actor="a"):
            pass
    assert error.value.code == "wiki_not_found"


async def test_session_expiry_retries_reads_only(server, monkeypatch):
    fake, url = server
    monkeypatch.setenv("WIKITOOLKIT_TOKEN", "t0k3n")
    async with RemoteWikiClient(WikiRemoteConfig(url=url), actor="a") as client:
        client._session_id = "stale"
        fake.forget = True
        assert "wiki_query" in READ_ONLY_TOOLS
        assert await client.call_tool_text("wiki_query", {}) == "hello"
        client._session_id = "stale"
        before = fake.calls
        with pytest.raises(RemoteWikiError) as error:
            await client.call_tool("wiki_remember", {})
        assert error.value.code == "session_expired"
        assert fake.calls == before


async def test_protocol_and_tool_errors(server, monkeypatch):
    fake, url = server
    monkeypatch.setenv("WIKITOOLKIT_TOKEN", "t0k3n")
    async with RemoteWikiClient(WikiRemoteConfig(url=url), actor="a") as client:
        fake.error = True
        with pytest.raises(RemoteWikiError) as error:
            await client.call_tool("wiki_query", {})
        assert error.value.code == "tool_error"


async def test_timeout_and_unreachable(server, monkeypatch):
    fake, url = server
    monkeypatch.setenv("WIKITOOLKIT_TOKEN", "t0k3n")
    fake.delay = 2
    with pytest.raises(RemoteWikiError) as error:
        async with RemoteWikiClient(WikiRemoteConfig(url=url, timeout=1), actor="a"):
            pass
    assert error.value.code == "timeout"

    with pytest.raises(RemoteWikiError) as error:
        async with RemoteWikiClient(
            WikiRemoteConfig(url="http://127.0.0.1:1/mcp/w", timeout=1), actor="a"
        ):
            pass
    assert error.value.code == "unreachable"


def test_decode_json_and_sse():
    body = b'{"jsonrpc":"2.0","id":1,"result":{"ok":true}}'
    assert _decode_body("application/json", body, "u")["result"]["ok"] is True
    sse = b'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
    assert _decode_body("text/event-stream", sse, "u")["result"]["ok"] is True
    with pytest.raises(RemoteWikiError) as error:
        _decode_body("application/json", b"garbage", "u")
    assert error.value.code == "protocol"
