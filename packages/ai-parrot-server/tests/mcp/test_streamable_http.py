"""Tests for the MCP Streamable HTTP transport (spec rev 2025-03-26).

Covers the Claude.ai-compatibility surface (POST JSON mode, 202 for
notifications, Mcp-Session-Id lifecycle, protocol version negotiation,
Origin validation) and the resumability path: SSE POST responses with
stream-scoped event ids, and GET resume after a client disconnect
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
import contextlib
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request
from multidict import CIMultiDict
from parrot.mcp.server_base import LATEST_PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS
from parrot.tools.abstract import AbstractTool
from pydantic import BaseModel, Field

from parrot.mcp.config import AuthMethod, MCPServerConfig
from parrot.mcp.oauth_server import APIKeyStore
from parrot.mcp.transports.streamable_http import (
    StreamableHttpMCPServer,
    parse_event_id,
)


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


@pytest.fixture
async def server_and_client():
    """Both halves, for tests that inspect server state directly."""
    server = make_server()
    test_client = TestClient(TestServer(server.app))
    await test_client.start_server()
    yield server, test_client
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


async def do_initialize(client: TestClient, version: str = "2025-03-26", **kwargs):
    resp = await client.post("/mcp", json=initialize_body(version), **kwargs)
    assert resp.status == 200
    session_id = resp.headers.get("Mcp-Session-Id")
    data = await resp.json()
    return session_id, data


async def read_sse_events(resp, count: int, timeout: float = 5.0):
    """Read `count` SSE message events (id + data) from a response.

    Event ids are stream-scoped strings (``{stream_id}:{sequence}``), not
    plain integers.
    """
    events = []
    current_id = None

    async def _read():
        nonlocal current_id
        while len(events) < count:
            line = (await resp.content.readline()).decode().rstrip("\n")
            if line.startswith("id: "):
                current_id = line[4:]
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

    async def test_batched_initialize_rejected(self, client):
        """The MCP lifecycle forbids batching initialize."""
        resp = await client.post(
            "/mcp",
            json=[
                initialize_body(),
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            ],
        )
        assert resp.status == 400
        assert "batched" in (await resp.json())["error"]["message"]

    async def test_sse_only_client_gets_initialize_over_sse(self, client):
        """A client that accepts only SSE is answered on a stream."""
        resp = await client.post(
            "/mcp",
            json=initialize_body(),
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status == 200
        assert "text/event-stream" in resp.headers["Content-Type"]
        assert resp.headers.get("Mcp-Session-Id")
        events = await read_sse_events(resp, 1)
        assert events[0][1]["result"]["protocolVersion"] == "2025-03-26"

    async def test_unacceptable_accept_returns_406(self, client):
        resp = await client.post(
            "/mcp",
            json=initialize_body(),
            headers={"Accept": "application/xml"},
        )
        assert resp.status == 406


class TestPostSemantics:
    async def test_notification_returns_202(self, client):
        resp = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        assert resp.status == 202
        assert await resp.read() == b""

    async def test_notification_with_an_id_is_still_a_notification(self, client):
        """A notification carrying an id must not 500 the endpoint.

        ``notifications/initialized`` produces no response, so treating it as
        a request left nothing to answer with and raised IndexError.
        """
        session_id, _ = await do_initialize(client)
        resp = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 7,
                "method": "notifications/initialized",
            },
            headers={"Mcp-Session-Id": session_id},
        )
        assert resp.status == 202

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

    async def test_session_id_echoed_on_later_responses(self, client):
        """Clients that re-read the header per response must keep the session."""
        session_id, _ = await do_initialize(client)
        resp = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers={"Mcp-Session-Id": session_id},
        )
        assert resp.headers.get("Mcp-Session-Id") == session_id

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

    async def test_sse_without_session_is_refused(self, client):
        """An SSE-only client cannot stream without first initializing."""
        resp = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status == 400

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

    async def test_delete_awaits_cancellation(self, server_and_client):
        """204 must mean the in-flight work has actually stopped."""
        server, test_client = server_and_client
        session_id, _ = await do_initialize(test_client)
        headers = {
            "Accept": "text/event-stream",
            "Mcp-Session-Id": session_id,
        }
        resp = await test_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 60,
                "method": "tools/call",
                "params": {"name": "slow_echo", "arguments": {"text": "x"}},
            },
            headers=headers,
        )
        assert resp.status == 200
        session = server._sessions[session_id]
        await asyncio.sleep(0.05)
        assert session.tasks, "dispatch task should be tracked"
        tasks = list(session.tasks.values())

        del_resp = await test_client.delete(
            "/mcp", headers={"Mcp-Session-Id": session_id}
        )
        assert del_resp.status == 204
        assert all(t.done() for t in tasks), "204 returned with work still running"
        resp.close()

    async def test_max_sessions_returns_503(self):
        server = make_server(max_sessions=2)
        test_client = TestClient(TestServer(server.app))
        await test_client.start_server()
        try:
            await do_initialize(test_client)
            await do_initialize(test_client)
            resp = await test_client.post("/mcp", json=initialize_body())
            assert resp.status == 503
            assert len(server._sessions) == 2
        finally:
            await server.stop()
            await test_client.close()

    async def test_busy_sessions_are_not_pruned(self, server_and_client):
        """A session with unfinished work must survive its idle TTL."""
        server, test_client = server_and_client
        session_id, _ = await do_initialize(test_client)
        session = server._sessions[session_id]

        never = asyncio.Event()
        task = asyncio.create_task(never.wait())
        session.tasks[99] = task
        session.last_seen -= server._session_ttl * 10  # long past the TTL

        await server._prune_sessions()
        assert session_id in server._sessions

        never.set()
        await task
        session.tasks.pop(99, None)
        await server._prune_sessions()
        assert session_id not in server._sessions

    async def test_cancelled_notification_stops_the_call(self, server_and_client):
        server, test_client = server_and_client
        session_id, _ = await do_initialize(test_client)
        headers = {
            "Accept": "text/event-stream",
            "Mcp-Session-Id": session_id,
        }
        resp = await test_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 61,
                "method": "tools/call",
                "params": {"name": "slow_echo", "arguments": {"text": "x"}},
            },
            headers=headers,
        )
        assert resp.status == 200
        await asyncio.sleep(0.05)
        task = server._sessions[session_id].tasks[61]

        cancel = await test_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"requestId": 61},
            },
            headers={"Mcp-Session-Id": session_id},
        )
        assert cancel.status == 202
        await asyncio.sleep(0.05)
        assert task.cancelled() or task.done()
        resp.close()


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

    async def test_malformed_last_event_id_returns_400(self, client):
        session_id, _ = await do_initialize(client)
        resp = await client.get(
            "/mcp",
            headers={
                "Accept": "text/event-stream",
                "Mcp-Session-Id": session_id,
                "Last-Event-ID": "0",
            },
        )
        assert resp.status == 400

    async def test_unknown_stream_in_last_event_id_returns_404(self, client):
        session_id, _ = await do_initialize(client)
        resp = await client.get(
            "/mcp",
            headers={
                "Accept": "text/event-stream",
                "Mcp-Session-Id": session_id,
                "Last-Event-ID": "no-such-stream:1",
            },
        )
        assert resp.status == 404


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
        stream_id, sequence = parse_event_id(event_id)
        assert stream_id and sequence == 1
        assert message["id"] == 5
        assert message["result"]["isError"] is False

    async def test_each_post_gets_its_own_stream(self, client):
        """Event ids are scoped per stream, so each POST restarts at 1."""
        session_id, _ = await do_initialize(client)
        headers = {
            "Accept": "text/event-stream",
            "Mcp-Session-Id": session_id,
        }
        stream_ids = set()
        for request_id in (21, 22):
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
            stream_id, sequence = parse_event_id(events[0][0])
            assert sequence == 1
            assert events[0][1]["id"] == request_id
            stream_ids.add(stream_id)
        assert len(stream_ids) == 2, "each POST must open a distinct stream"

    async def test_batch_over_sse_shares_one_stream(self, client):
        session_id, _ = await do_initialize(client)
        resp = await client.post(
            "/mcp",
            json=[
                {"jsonrpc": "2.0", "id": 71, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 72, "method": "tools/list"},
            ],
            headers={
                "Accept": "text/event-stream",
                "Mcp-Session-Id": session_id,
            },
        )
        events = await read_sse_events(resp, 2)
        streams = {parse_event_id(eid)[0] for eid, _ in events}
        assert len(streams) == 1
        assert {parse_event_id(eid)[1] for eid, _ in events} == {1, 2}

    async def test_open_get_stream_does_not_steal_post_response(self, client):
        """The response must travel on the stream that carried the request.

        The official SDK opens a GET stream right after initialize, so this
        is the ordinary state, not an edge case.
        """
        session_id, _ = await do_initialize(client)
        headers = {
            "Accept": "text/event-stream",
            "Mcp-Session-Id": session_id,
        }
        get_resp = await client.get("/mcp", headers=headers, timeout=None)
        assert get_resp.status == 200
        await asyncio.sleep(0.1)  # let the GET stream settle into its wait

        post = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 99,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"text": "mine"}},
            },
            headers=headers,
        )
        assert post.status == 200
        events = await read_sse_events(post, 1)
        assert events[0][1]["id"] == 99
        get_resp.close()


class TestResumability:
    async def test_disconnect_and_resume_collects_result(self, client):
        """Launch a slow call over SSE, drop the connection mid-call, then
        reconnect with GET and still receive the result.

        The abandoned POST stream is orphaned when its response unwinds, and
        an orphaned stream is exactly what the session's GET stream adopts.
        """
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

        get_resp = await client.get(
            "/mcp",
            headers={
                "Accept": "text/event-stream",
                "Mcp-Session-Id": session_id,
            },
            timeout=None,
        )
        assert get_resp.status == 200
        events = await read_sse_events(get_resp, 1)
        event_id, message = events[0]
        assert parse_event_id(event_id)[1] == 1
        assert message["id"] == 42
        assert any(
            "flow" in c["text"] for c in message["result"]["content"]
        )
        get_resp.close()

    async def test_last_event_id_replays_only_later_events(self, client):
        """Resuming a stream replays that stream's events after the id."""
        session_id, _ = await do_initialize(client)
        headers = {
            "Accept": "text/event-stream",
            "Mcp-Session-Id": session_id,
        }
        # One POST carrying two requests -> one stream, sequences 1 and 2.
        resp = await client.post(
            "/mcp",
            json=[
                {"jsonrpc": "2.0", "id": 31, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 32, "method": "tools/list"},
            ],
            headers=headers,
        )
        events = await read_sse_events(resp, 2)
        stream_id = parse_event_id(events[0][0])[0]
        first_id = next(
            eid for eid, msg in events if parse_event_id(eid)[1] == 1
        )
        second_msg_id = next(
            msg["id"] for eid, msg in events if parse_event_id(eid)[1] == 2
        )
        resp.close()
        await asyncio.sleep(0.05)

        get_resp = await client.get(
            "/mcp",
            headers={**headers, "Last-Event-ID": first_id},
            timeout=None,
        )
        replayed = await read_sse_events(get_resp, 1)
        assert parse_event_id(replayed[0][0]) == (stream_id, 2)
        assert replayed[0][1]["id"] == second_msg_id
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
            # One stream carrying three requests: the ring drops the oldest.
            resp = await test_client.post(
                "/mcp",
                json=[
                    {"jsonrpc": "2.0", "id": 51, "method": "tools/list"},
                    {"jsonrpc": "2.0", "id": 52, "method": "tools/list"},
                    {"jsonrpc": "2.0", "id": 53, "method": "tools/list"},
                ],
                headers=headers,
            )
            events = await read_sse_events(resp, 3)
            stream_id = parse_event_id(events[0][0])[0]

            buffer = server._sessions[session_id].streams[stream_id]
            assert [e.sequence for e in buffer.events_after(0)] == [2, 3]
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

    async def test_unlisted_origin_rejected_by_default(self, client):
        """No allowlist means localhost only — the spec's mandatory default."""
        resp = await client.post(
            "/mcp",
            json=initialize_body(),
            headers={"Origin": "https://anywhere.example"},
        )
        assert resp.status == 403

    async def test_localhost_origin_always_allowed(self, client):
        resp = await client.post(
            "/mcp",
            json=initialize_body(),
            headers={"Origin": "http://localhost:3000"},
        )
        assert resp.status == 200

    async def test_no_origin_header_allowed(self, client):
        """Server-to-server clients (Claude.ai) send no Origin."""
        resp = await client.post("/mcp", json=initialize_body())
        assert resp.status == 200

    async def test_allow_any_origin_escape_hatch(self):
        server, test_client = await self.make_client(allow_any_origin=True)
        try:
            resp = await test_client.post(
                "/mcp",
                json=initialize_body(),
                headers={"Origin": "https://anywhere.example"},
            )
            assert resp.status == 200
        finally:
            await server.stop()
            await test_client.close()

    async def test_origin_checked_on_get_and_delete(self):
        server, test_client = await self.make_client(
            allowed_origins=["https://claude.ai"]
        )
        try:
            session_id, _ = await do_initialize(
                test_client, headers={"Origin": "https://claude.ai"}
            )
            bad = {"Origin": "https://evil.example", "Mcp-Session-Id": session_id}
            get_resp = await test_client.get(
                "/mcp", headers={**bad, "Accept": "text/event-stream"}
            )
            assert get_resp.status == 403
            del_resp = await test_client.delete("/mcp", headers=bad)
            assert del_resp.status == 403
        finally:
            await server.stop()
            await test_client.close()

    async def test_protocol_header_checked_on_get_and_delete(self, client):
        session_id, _ = await do_initialize(client)
        bad = {
            "MCP-Protocol-Version": "1999-01-01",
            "Mcp-Session-Id": session_id,
        }
        get_resp = await client.get(
            "/mcp", headers={**bad, "Accept": "text/event-stream"}
        )
        assert get_resp.status == 400
        del_resp = await client.delete("/mcp", headers=bad)
        assert del_resp.status == 400


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

    async def test_session_is_bound_to_its_owner(self):
        """A leaked Mcp-Session-Id must not be usable by another principal."""
        store = APIKeyStore()
        alice = store.issue_key("alice").key
        mallory = store.issue_key("mallory").key
        server = make_server(
            auth_method=AuthMethod.API_KEY, api_key_store=store
        )
        test_client = TestClient(TestServer(server.app))
        await test_client.start_server()
        try:
            session_id, _ = await do_initialize(
                test_client, headers={"X-API-Key": alice}
            )
            call = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}

            mine = await test_client.post(
                "/mcp",
                json=call,
                headers={"X-API-Key": alice, "Mcp-Session-Id": session_id},
            )
            assert mine.status == 200

            theirs = await test_client.post(
                "/mcp",
                json=call,
                headers={"X-API-Key": mallory, "Mcp-Session-Id": session_id},
            )
            assert theirs.status == 404

            stolen_delete = await test_client.delete(
                "/mcp",
                headers={"X-API-Key": mallory, "Mcp-Session-Id": session_id},
            )
            assert stolen_delete.status == 404
            assert session_id in server._sessions
        finally:
            await server.stop()
            await test_client.close()


class TestSharedAppMounting:
    """The route set as ``start()`` actually mounts it.

    The other suites register routes directly, which skips exactly the step
    that used to serve the endpoint at ``/mcp/mcp``.
    """

    async def test_mounted_on_parent_app_at_base_path(self):
        parent = web.Application()
        config = MCPServerConfig(
            name="mounted", transport="streamable-http"
        )
        server = StreamableHttpMCPServer(config, parent_app=parent)
        server.register_tool(EchoTool())
        await server.start()

        test_client = TestClient(TestServer(parent))
        await test_client.start_server()
        try:
            resp = await test_client.post("/mcp", json=initialize_body())
            assert resp.status == 200, "endpoint must answer at base_path"
            assert resp.headers.get("Mcp-Session-Id")

            info = await test_client.get("/mcp/info")
            assert info.status == 200

            doubled = await test_client.post("/mcp/mcp", json=initialize_body())
            assert doubled.status == 404, "base_path must not be applied twice"
        finally:
            await server.stop()
            await test_client.close()

    async def test_custom_base_path_is_honoured(self):
        parent = web.Application()
        config = MCPServerConfig(
            name="mounted", transport="streamable-http", base_path="/tools/mcp"
        )
        server = StreamableHttpMCPServer(config, parent_app=parent)
        server.register_tool(EchoTool())
        await server.start()

        test_client = TestClient(TestServer(parent))
        await test_client.start_server()
        try:
            resp = await test_client.post("/tools/mcp", json=initialize_body())
            assert resp.status == 200
        finally:
            await server.stop()
            await test_client.close()


class TestStreamIsolationAndBounds:
    """Follow-ups from the adversarial review of the fixes."""

    async def test_resumed_stream_does_not_replay_other_streams(self, client):
        """A resumed GET carries its own stream and nothing else.

        The spec forbids a resumed stream from replaying messages that
        belong to a different one.
        """
        session_id, _ = await do_initialize(client)
        headers = {
            "Accept": "text/event-stream",
            "Mcp-Session-Id": session_id,
        }
        # Stream A: read its event, then abandon the connection.
        resp_a = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 81, "method": "tools/list"},
            headers=headers,
        )
        events_a = await read_sse_events(resp_a, 1)
        stream_a, _seq = parse_event_id(events_a[0][0])
        resp_a.close()

        # Stream B: launch a slow call and drop it, leaving an undelivered
        # event behind on a *different* stream.
        resp_b = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 82,
                "method": "tools/call",
                "params": {"name": "slow_echo", "arguments": {"text": "b"}},
            },
            headers=headers,
        )
        assert resp_b.status == 200
        resp_b.close()
        await asyncio.sleep(0.5)  # let the slow call finish and buffer

        # Resume stream A from before its only event.
        get_resp = await client.get(
            "/mcp",
            headers={**headers, "Last-Event-ID": f"{stream_a}:0"},
            timeout=None,
        )
        assert get_resp.status == 200
        events = await read_sse_events(get_resp, 1)
        assert {parse_event_id(eid)[0] for eid, _ in events} == {stream_a}
        assert events[0][1]["id"] == 81, "stream B's response must not appear"
        get_resp.close()

    async def test_streams_are_bounded_per_session(self):
        """A session issuing many SSE POSTs must not accumulate buffers."""
        server = make_server(max_streams_per_session=4)
        test_client = TestClient(TestServer(server.app))
        await test_client.start_server()
        try:
            session_id, _ = await do_initialize(test_client)
            headers = {
                "Accept": "text/event-stream",
                "Mcp-Session-Id": session_id,
            }
            for request_id in range(90, 105):
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

            streams = server._sessions[session_id].streams
            assert len(streams) <= 5, (
                f"expected the cap to hold, got {len(streams)} streams"
            )
        finally:
            await server.stop()
            await test_client.close()

    async def test_teardown_abandons_tasks_that_ignore_cancellation(
        self, server_and_client, monkeypatch
    ):
        """DELETE must not hang on a tool that swallows cancellation."""
        import parrot.mcp.transports.streamable_http as module

        monkeypatch.setattr(module, "TEARDOWN_TIMEOUT", 0.2)
        server, test_client = server_and_client
        session_id, _ = await do_initialize(test_client)
        session = server._sessions[session_id]

        release = asyncio.Event()

        async def stubborn():
            # Ignores cancellation until the test lets it go, so the run
            # cannot be left with an uncollectable task.
            while not release.is_set():
                with contextlib.suppress(
                    asyncio.TimeoutError, asyncio.CancelledError
                ):
                    await asyncio.wait_for(release.wait(), timeout=0.05)

        task = asyncio.create_task(stubborn())
        session.tasks[77] = task
        try:
            resp = await asyncio.wait_for(
                test_client.delete(
                    "/mcp", headers={"Mcp-Session-Id": session_id}
                ),
                timeout=5,
            )
            assert resp.status == 204, "DELETE must not hang on a stuck task"
            assert not task.done(), "the task really did ignore cancellation"
        finally:
            release.set()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(task, timeout=2)


class TestPrincipalBinding:
    """`_principal` must not collapse every caller onto None."""

    def _request(self, server, **headers):
        return make_mocked_request(
            "POST", "/mcp", headers=CIMultiDict(headers), app=server.app
        )

    def test_no_auth_has_no_principal(self):
        server = make_server()
        assert server._principal(self._request(server)) is None

    def test_credential_digest_binds_when_auth_attributes_nobody(self):
        """Internal OAuth validates a token but names no user."""
        server = make_server(auth_method=AuthMethod.OAUTH2_INTERNAL)
        alice = server._principal(
            self._request(server, Authorization="Bearer alice-token")
        )
        mallory = server._principal(
            self._request(server, Authorization="Bearer mallory-token")
        )
        assert alice and mallory
        assert alice != mallory, "different tokens must not share a session"
        assert "alice-token" not in alice, "the credential must not be stored"

    def test_user_id_preferred_over_digest(self):
        server = make_server(auth_method=AuthMethod.API_KEY)
        request = self._request(server, **{"X-API-Key": "k"})
        request["mcp_user"] = {"user_id": "alice", "scopes": []}
        assert server._principal(request) == "alice"

    def test_falls_back_through_common_identity_keys(self):
        """navigator-auth session data may not use `user_id`."""
        server = make_server(auth_method=AuthMethod.BEARER)
        request = self._request(server, Authorization="Bearer x")
        request["mcp_user"] = {"email": "alice@example.com"}
        assert server._principal(request) == "alice@example.com"
