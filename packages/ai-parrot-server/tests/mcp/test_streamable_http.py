"""Tests for the MCP Streamable HTTP transport (spec rev 2025-03-26).

Covers the Claude.ai-compatibility surface (POST JSON mode, 202 for
notifications, Mcp-Session-Id lifecycle, protocol version negotiation,
Origin validation) and the resumability path: SSE POST responses with
event ids, and GET + Last-Event-ID resume after a client disconnect
mid-call — the "launch an agent flow, reconnect, collect the result"
scenario.

Manual smoke test against a running server (needs the ``mcp`` extra)::

    uv run --extra mcp python - <<'EOF'
    import asyncio
    from mcp.client.streamable_http import streamablehttp_client
    from mcp import ClientSession

    async def main():
        async with streamablehttp_client("http://127.0.0.1:9090/mcp") as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
                print(await session.list_tools())

    asyncio.run(main())
    EOF
"""
import asyncio
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from pydantic import BaseModel, Field

from parrot.mcp.config import AuthMethod, MCPServerConfig
from parrot.mcp.server_base import LATEST_PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS
from parrot.mcp.transports.streamable_http import StreamableHttpMCPServer
from parrot.tools.abstract import AbstractTool


class EchoInput(BaseModel):
    text: str = Field(..., description="Text to echo")


class EchoTool(AbstractTool):
    """Echo input back"""
    name = "echo"
    description = "Echo input back"
    args_schema = EchoInput

    async def _execute(self, text: str) -> str:
        return text


class SlowInput(BaseModel):
    text: str = Field(..., description="Text to echo after a delay")


class SlowTool(AbstractTool):
    """Echo input back after a short delay (simulates a long agent flow)."""
    name = "slow_echo"
    description = "Echo input back after a delay"
    args_schema = SlowInput

    async def _execute(self, text: str) -> str:
        await asyncio.sleep(0.3)
        return text


def make_server(**overrides) -> StreamableHttpMCPServer:
    config = MCPServerConfig(
        name="test-streamable",
        transport="streamable-http",
        **overrides,
    )
    server = StreamableHttpMCPServer(config)
    server.register_tool(EchoTool())
    server.register_tool(SlowTool())
    server._register_routes(server.app.router, config.base_path)
    return server


@pytest.fixture
async def client():
    server = make_server()
    test_client = TestClient(TestServer(server.app))
    await test_client.start_server()
    yield test_client
    await server.stop()
    await test_client.close()


def initialize_body(version: str = "2025-03-26") -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": version,
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"},
        },
    }


async def do_initialize(client: TestClient, version: str = "2025-03-26"):
    resp = await client.post("/mcp", json=initialize_body(version))
    assert resp.status == 200
    session_id = resp.headers.get("Mcp-Session-Id")
    data = await resp.json()
    return session_id, data


async def read_sse_events(resp, count: int, timeout: float = 5.0):
    """Read `count` SSE message events (id + data) from a response."""
    events = []
    current_id = None

    async def _read():
        nonlocal current_id
        while len(events) < count:
            line = (await resp.content.readline()).decode().rstrip("\n")
            if line.startswith("id: "):
                current_id = int(line[4:])
            elif line.startswith("data: "):
                events.append((current_id, json.loads(line[6:])))

    await asyncio.wait_for(_read(), timeout)
    return events


class TestInitializeAndVersions:
    @pytest.mark.parametrize("version", SUPPORTED_PROTOCOL_VERSIONS)
    async def test_initialize_echoes_supported_version(self, client, version):
        session_id, data = await do_initialize(client, version)
        assert session_id, "Mcp-Session-Id header must be issued on initialize"
        assert data["result"]["protocolVersion"] == version

    async def test_initialize_unknown_version_gets_latest(self, client):
        _, data = await do_initialize(client, "1999-01-01")
        assert data["result"]["protocolVersion"] == LATEST_PROTOCOL_VERSION

    async def test_bad_protocol_version_header_rejected(self, client):
        resp = await client.post(
            "/mcp",
            json=initialize_body(),
            headers={"MCP-Protocol-Version": "1999-01-01"},
        )
        assert resp.status == 400

    async def test_info_reports_transport(self, client):
        resp = await client.get("/mcp/info")
        data = await resp.json()
        assert data["transport"] == "streamable-http"


class TestPostSemantics:
    async def test_notification_returns_202(self, client):
        resp = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        assert resp.status == 202
        assert await resp.read() == b""

    async def test_tools_roundtrip_json_mode(self, client):
        session_id, _ = await do_initialize(client)
        headers = {"Mcp-Session-Id": session_id}

        resp = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers=headers,
        )
        assert resp.status == 200
        tools = (await resp.json())["result"]["tools"]
        assert {t["name"] for t in tools} == {"echo", "slow_echo"}

        resp = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"text": "hi"}},
            },
            headers=headers,
        )
        result = (await resp.json())["result"]
        assert result["isError"] is False
        assert any("hi" in c["text"] for c in result["content"])

    async def test_batch_post_returns_array(self, client):
        session_id, _ = await do_initialize(client)
        resp = await client.post(
            "/mcp",
            json=[
                {"jsonrpc": "2.0", "id": 10, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 11, "method": "tools/list"},
            ],
            headers={"Mcp-Session-Id": session_id},
        )
        data = await resp.json()
        assert isinstance(data, list)
        assert {r["id"] for r in data} == {10, 11}

    async def test_unknown_session_returns_404(self, client):
        resp = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers={"Mcp-Session-Id": "no-such-session"},
        )
        assert resp.status == 404

    async def test_missing_session_is_tolerated(self, client):
        # Lenient stateless mode: hand-rolled clients without session ids
        # still get JSON answers.
        resp = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )
        assert resp.status == 200

    async def test_parse_error_returns_400(self, client):
        resp = await client.post(
            "/mcp",
            data=b"{not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400
        assert (await resp.json())["error"]["code"] == -32700


class TestSessionLifecycle:
    async def test_delete_terminates_session(self, client):
        session_id, _ = await do_initialize(client)
        resp = await client.delete(
            "/mcp", headers={"Mcp-Session-Id": session_id}
        )
        assert resp.status == 204

        # Session is gone afterwards
        resp = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers={"Mcp-Session-Id": session_id},
        )
        assert resp.status == 404

    async def test_delete_without_header_returns_400(self, client):
        resp = await client.delete("/mcp")
        assert resp.status == 400

    async def test_delete_unknown_session_returns_404(self, client):
        resp = await client.delete(
            "/mcp", headers={"Mcp-Session-Id": "no-such-session"}
        )
        assert resp.status == 404


class TestGetStream:
    async def test_get_without_sse_accept_returns_405(self, client):
        resp = await client.get("/mcp", headers={"Accept": "application/json"})
        assert resp.status == 405
        assert "POST" in resp.headers.get("Allow", "")

    async def test_get_without_session_returns_400(self, client):
        resp = await client.get(
            "/mcp", headers={"Accept": "text/event-stream"}
        )
        assert resp.status == 400

    async def test_get_unknown_session_returns_404(self, client):
        resp = await client.get(
            "/mcp",
            headers={
                "Accept": "text/event-stream",
                "Mcp-Session-Id": "no-such-session",
            },
        )
        assert resp.status == 404

    async def test_second_concurrent_get_returns_409(self, client):
        session_id, _ = await do_initialize(client)
        headers = {
            "Accept": "text/event-stream",
            "Mcp-Session-Id": session_id,
        }
        first = await client.get("/mcp", headers=headers, timeout=None)
        assert first.status == 200
        second = await client.get("/mcp", headers=headers)
        assert second.status == 409
        first.close()


class TestSsePostResponses:
    async def test_post_with_sse_accept_streams_response(self, client):
        session_id, _ = await do_initialize(client)
        resp = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"text": "sse"}},
            },
            headers={
                "Accept": "application/json, text/event-stream",
                "Mcp-Session-Id": session_id,
            },
        )
        assert resp.status == 200
        assert "text/event-stream" in resp.headers["Content-Type"]
        events = await read_sse_events(resp, 1)
        event_id, message = events[0]
        assert event_id == 1
        assert message["id"] == 5
        assert message["result"]["isError"] is False

    async def test_sse_event_ids_increment(self, client):
        session_id, _ = await do_initialize(client)
        headers = {
            "Accept": "text/event-stream",
            "Mcp-Session-Id": session_id,
        }
        for expected_id, request_id in ((1, 21), (2, 22)):
            resp = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "tools/list",
                },
                headers=headers,
            )
            events = await read_sse_events(resp, 1)
            assert events[0][0] == expected_id
            assert events[0][1]["id"] == request_id


class TestResumability:
    async def test_disconnect_and_resume_collects_result(self, client):
        """Launch a slow call over SSE, drop the connection mid-call, then
        resume via GET + Last-Event-ID and still receive the result."""
        session_id, _ = await do_initialize(client)

        resp = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 42,
                "method": "tools/call",
                "params": {"name": "slow_echo", "arguments": {"text": "flow"}},
            },
            headers={
                "Accept": "text/event-stream",
                "Mcp-Session-Id": session_id,
            },
        )
        assert resp.status == 200
        # Disconnect before the slow tool (0.3s) finishes.
        resp.close()

        # Reconnect and resume from the beginning of the stream.
        get_resp = await client.get(
            "/mcp",
            headers={
                "Accept": "text/event-stream",
                "Mcp-Session-Id": session_id,
                "Last-Event-ID": "0",
            },
            timeout=None,
        )
        assert get_resp.status == 200
        events = await read_sse_events(get_resp, 1)
        event_id, message = events[0]
        assert event_id == 1
        assert message["id"] == 42
        assert any(
            "flow" in c["text"] for c in message["result"]["content"]
        )
        get_resp.close()

    async def test_last_event_id_replays_only_later_events(self, client):
        session_id, _ = await do_initialize(client)
        headers = {
            "Accept": "text/event-stream",
            "Mcp-Session-Id": session_id,
        }
        # Produce two buffered events (ids 1 and 2).
        for request_id in (31, 32):
            resp = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "tools/list",
                },
                headers=headers,
            )
            await read_sse_events(resp, 1)

        get_resp = await client.get(
            "/mcp",
            headers={**headers, "Last-Event-ID": "1"},
            timeout=None,
        )
        events = await read_sse_events(get_resp, 1)
        assert events[0][0] == 2
        assert events[0][1]["id"] == 32
        get_resp.close()

    async def test_event_buffer_is_bounded(self):
        server = make_server(event_buffer_size=2)
        test_client = TestClient(TestServer(server.app))
        await test_client.start_server()
        try:
            session_id, _ = await do_initialize(test_client)
            headers = {
                "Accept": "text/event-stream",
                "Mcp-Session-Id": session_id,
            }
            for request_id in (51, 52, 53):
                resp = await test_client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/list",
                    },
                    headers=headers,
                )
                await read_sse_events(resp, 1)

            session = server._sessions[session_id]
            replay = session.events.events_after(0)
            # Ring buffer of 2: event 1 was evicted.
            assert [e.event_id for e in replay] == [2, 3]
        finally:
            await server.stop()
            await test_client.close()


class TestOriginValidation:
    async def make_client(self, **overrides):
        server = make_server(**overrides)
        test_client = TestClient(TestServer(server.app))
        await test_client.start_server()
        return server, test_client

    async def test_disallowed_origin_rejected(self):
        server, test_client = await self.make_client(
            allowed_origins=["https://claude.ai"]
        )
        try:
            resp = await test_client.post(
                "/mcp",
                json=initialize_body(),
                headers={"Origin": "https://evil.example"},
            )
            assert resp.status == 403
        finally:
            await server.stop()
            await test_client.close()

    async def test_allowed_origin_accepted(self):
        server, test_client = await self.make_client(
            allowed_origins=["https://claude.ai"]
        )
        try:
            resp = await test_client.post(
                "/mcp",
                json=initialize_body(),
                headers={"Origin": "https://claude.ai"},
            )
            assert resp.status == 200
        finally:
            await server.stop()
            await test_client.close()

    async def test_any_origin_allowed_without_allowlist(self, client):
        resp = await client.post(
            "/mcp",
            json=initialize_body(),
            headers={"Origin": "https://anywhere.example"},
        )
        assert resp.status == 200


class TestAuth:
    async def test_api_key_required_when_configured(self):
        server = make_server(auth_method=AuthMethod.API_KEY)
        test_client = TestClient(TestServer(server.app))
        await test_client.start_server()
        try:
            resp = await test_client.post("/mcp", json=initialize_body())
            assert resp.status == 401
        finally:
            await server.stop()
            await test_client.close()
