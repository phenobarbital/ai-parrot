"""End-to-end integration tests for the A2A Protocol v1.0.0 stack
(FEAT-272 / TASK-1719).

Exercises the full v1.0.0 protocol stack over a real HTTP connection
(aiohttp `TestServer`), covering:

    - v1.0 roundtrip: full task lifecycle (create -> working -> completed)
      with SCREAMING_SNAKE_CASE enum serialization end-to-end.
    - v0.3 client + v1.0 server backward compatibility (no `A2A-Version`
      header -> v0.3 wire format, unchanged from pre-FEAT-272 behavior).
    - v1.0 SSE streaming event format.
    - Version negotiation: an unsupported `A2A-Version` value returns
      `VersionNotSupportedError` (-32009).
    - Push notification config CRUD roundtrip (Create -> List -> Get ->
      Delete) via both the REST binding and the JSON-RPC binding.
    - The full A2A error code table (-32001..-32009): the five codes that
      have a real triggering operation today (-32001, -32002, -32003,
      -32007, -32009) are exercised end-to-end over HTTP; the remaining
      four (-32004, -32005, -32006, -32008) have NO wired operation in this
      spec (extensions/content-negotiation/gRPC are explicitly out of scope
      per the spec's Non-Goals) — those are verified directly against the
      `A2A_ERRORS` table instead of inventing new endpoints outside this
      task's file list (test files only).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from parrot.a2a.models import AgentCapabilities, A2A_ERRORS
from parrot.a2a.server import A2AServer
from parrot.a2a.client import A2AClient


def _mock_agent(name: str = "TestAgent") -> MagicMock:
    # `spec=` restricts the mock to these attributes only, so
    # `hasattr(agent, "ask_stream")` is False (plain MagicMock() would
    # auto-create ANY attribute, including "ask_stream", forcing
    # A2AServer into the ask_stream code path instead of the intended
    # non-streaming fallback used by these tests).
    agent = MagicMock(spec=["name", "description", "ask", "tool_manager", "tools", "tags"])
    agent.name = name
    agent.description = "Test agent"
    agent.ask = AsyncMock(return_value="Hello from agent")
    agent.tool_manager = None
    agent.tools = []
    agent.tags = []
    return agent


@pytest.fixture
async def live_agent():
    """A running A2AServer (with push notifications enabled) + connected client."""
    agent = _mock_agent()
    server = A2AServer(
        agent,
        capabilities=AgentCapabilities(streaming=True, push_notifications=True),
    )
    app = web.Application()
    server.setup(app, url="http://testserver/a2a")

    test_server = TestServer(app)
    await test_server.start_server()

    base_url = str(test_server.make_url("")).rstrip("/")
    client = A2AClient(base_url)
    await client.connect()

    try:
        yield server, client
    finally:
        await client.disconnect()
        await test_server.close()


@pytest.fixture
async def live_agent_no_push():
    """A running A2AServer with push notifications DISABLED."""
    agent = _mock_agent("NoPushAgent")
    server = A2AServer(agent, capabilities=AgentCapabilities(streaming=True, push_notifications=False))
    app = web.Application()
    server.setup(app, url="http://testserver/a2a")

    test_server = TestServer(app)
    await test_server.start_server()

    base_url = str(test_server.make_url("")).rstrip("/")
    client = A2AClient(base_url)
    await client.connect()

    try:
        yield server, client
    finally:
        await client.disconnect()
        await test_server.close()


class TestV1Roundtrip:
    async def test_discover_uses_v1_card(self, live_agent):
        _server, client = live_agent
        assert client._server_version == "1.0"
        assert client.agent_card.url is not None

    async def test_full_lifecycle_send_message(self, live_agent):
        _server, client = live_agent
        task = await client.send_message("Hello there")
        assert task.status.state.value == "TASK_STATE_COMPLETED"
        assert task.artifacts
        assert task.artifacts[0].parts[0].text == "Hello from agent"

    async def test_get_task_after_send(self, live_agent):
        _server, client = live_agent
        sent = await client.send_message("Hello there")
        fetched = await client.get_task(sent.id)
        assert fetched.id == sent.id
        assert fetched.status.state.value == "TASK_STATE_COMPLETED"

    async def test_list_tasks(self, live_agent):
        _server, client = live_agent
        await client.send_message("First")
        await client.send_message("Second")
        tasks = await client.list_tasks()
        assert len(tasks) >= 2


class TestV03BackwardCompat:
    async def test_v03_client_talks_to_v1_server(self, live_agent):
        """A genuine v0.3 client — a plain `aiohttp.ClientSession` that never
        sends `A2A-Version` at all (unlike `A2AClient`, which defaults to
        sending it) — gets v0.3-formatted responses from the SAME
        v1.0-capable server, proving backward compatibility end-to-end.
        """
        import aiohttp

        _server, v1_client = live_agent
        base_url = v1_client.base_url

        async with aiohttp.ClientSession() as raw_session:
            async with raw_session.get(f"{base_url}/.well-known/agent.json") as resp:
                data = await resp.json()
            assert "url" in data
            assert "supportedInterfaces" not in data

            async with raw_session.post(
                f"{base_url}/a2a/message/send",
                json={"message": {"role": "user", "parts": [{"text": "hi"}]}},
            ) as resp:
                assert resp.status == 200
                task_data = await resp.json()
            assert task_data["status"]["state"] == "completed"


class TestV1Streaming:
    async def test_streaming_v1_events(self, live_agent):
        _server, client = live_agent
        chunks = []
        async for chunk in client.stream_message("Stream this"):
            chunks.append(chunk)
        assert "".join(chunks)  # agent has no ask_stream -> fallback path


class TestVersionNegotiationIntegration:
    async def test_unsupported_version_returns_400_and_dash32009(self, live_agent):
        _server, client = live_agent
        async with client._session.post(
            f"{client.base_url}/a2a/message:send",
            headers={"A2A-Version": "99.0"},
            json={"message": {"role": "user", "parts": [{"text": "hi"}]}},
        ) as resp:
            assert resp.status == 400
            data = await resp.json()
        assert data["error"]["code"] == -32009


class TestPushNotificationCrudRoundtrip:
    async def test_rest_crud_roundtrip(self, live_agent):
        _server, client = live_agent
        task = await client.send_message("hi")

        created = await client.create_push_config(task.id, "https://example.com/hook")
        assert created.id

        listed = await client.list_push_configs(task.id)
        assert len(listed) == 1
        assert listed[0].id == created.id

        fetched = await client.get_push_config(task.id, created.id)
        assert fetched is not None
        assert fetched.url == "https://example.com/hook"

        deleted = await client.delete_push_config(task.id, created.id)
        assert deleted is True

        after_delete = await client.get_push_config(task.id, created.id)
        assert after_delete is None

    async def test_jsonrpc_crud_roundtrip(self, live_agent):
        _server, client = live_agent
        task = await client.send_message("hi")

        create_result = await client.rpc_call(
            "CreateTaskPushNotificationConfig",
            {"config": {"taskId": task.id, "url": "https://example.com/hook2"}},
        )
        config_id = create_result["id"]

        list_result = await client.rpc_call(
            "ListTaskPushNotificationConfigs", {"taskId": task.id}
        )
        assert len(list_result["configs"]) == 1

        get_result = await client.rpc_call(
            "GetTaskPushNotificationConfig", {"taskId": task.id, "configId": config_id}
        )
        assert get_result["id"] == config_id

        delete_result = await client.rpc_call(
            "DeleteTaskPushNotificationConfig", {"taskId": task.id, "configId": config_id}
        )
        assert delete_result["deleted"] is True

    async def test_push_not_supported_when_disabled(self, live_agent_no_push):
        _server, client = live_agent_no_push
        task = await client.send_message("hi")

        async with client._session.post(
            f"{client.base_url}/a2a/tasks/{task.id}/pushNotificationConfigs",
            json={"url": "https://example.com/hook"},
        ) as resp:
            assert resp.status == 400
            data = await resp.json()
        assert data["error"]["code"] == -32003


class TestA2AErrorCodeTable:
    """Verifies all 9 A2A v1.0.0 error codes (-32001..-32009).

    Codes with a real, currently-wired operation (-32001, -32002, -32003,
    -32007, -32009) are triggered end-to-end over HTTP. The remaining four
    (-32004, -32005, -32006, -32008) have no operation that raises them in
    this spec (extensions/content-negotiation/gRPC are explicitly deferred
    per the spec's Non-Goals) — verified directly against the table.
    """

    async def test_task_not_found_dash32001(self, live_agent):
        _server, client = live_agent
        async with client._session.get(
            f"{client.base_url}/a2a/tasks/nonexistent",
            headers={"A2A-Version": "1.0"},
        ) as resp:
            assert resp.status == 404
            data = await resp.json()
        assert data["error"]["code"] == -32001

    async def test_task_not_cancelable_dash32002(self, live_agent):
        _server, client = live_agent
        task = await client.send_message("hi")  # completes synchronously
        async with client._session.post(
            f"{client.base_url}/a2a/tasks/{task.id}:cancel",
            headers={"A2A-Version": "1.0"},
        ) as resp:
            assert resp.status == 400
            data = await resp.json()
        assert data["error"]["code"] == -32002

    async def test_push_not_supported_dash32003(self, live_agent_no_push):
        _server, client = live_agent_no_push
        task = await client.send_message("hi")
        async with client._session.post(
            f"{client.base_url}/a2a/tasks/{task.id}/pushNotificationConfigs",
            json={"url": "https://example.com/hook"},
        ) as resp:
            data = await resp.json()
        assert data["error"]["code"] == -32003

    async def test_extended_agent_card_not_configured_dash32007(self, live_agent):
        _server, client = live_agent
        async with client._session.post(
            f"{client.base_url}/a2a/rpc",
            json={"jsonrpc": "2.0", "id": 1, "method": "GetExtendedAgentCard", "params": {}},
        ) as resp:
            data = await resp.json()
        assert data["error"]["code"] == -32007

    async def test_version_not_supported_dash32009(self, live_agent):
        _server, client = live_agent
        async with client._session.get(
            f"{client.base_url}/.well-known/agent-card.json",
            headers={"A2A-Version": "7.0"},
        ) as resp:
            assert resp.status == 400
            data = await resp.json()
        assert data["error"]["code"] == -32009

    def test_error_table_completeness_for_unwired_codes(self):
        """-32004, -32005, -32006, -32008 have no wired operation in this
        spec; verify the table itself carries the correct code/status.
        """
        assert A2A_ERRORS["UnsupportedOperationError"] == (-32004, 400)
        assert A2A_ERRORS["ContentTypeNotSupportedError"] == (-32005, 400)
        assert A2A_ERRORS["InvalidAgentResponseError"] == (-32006, 500)
        assert A2A_ERRORS["ExtensionSupportRequiredError"] == (-32008, 400)

    def test_error_table_full_coverage(self):
        """All 9 A2A v1.0.0 error codes are present in the table."""
        expected_codes = {-32001, -32002, -32003, -32004, -32005, -32006, -32007, -32008, -32009}
        actual_codes = {code for code, _status in A2A_ERRORS.values()}
        assert actual_codes == expected_codes
