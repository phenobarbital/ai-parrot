"""Cross-version (v0.3 <-> v1.0.0) compatibility tests for the A2A client and
data model layer (FEAT-272 / TASK-1719).

Scope note: this file stays within the `ai-parrot` package boundary (models
+ client only, no `A2AServer` import). The live client<->server roundtrip
scenarios (full task lifecycle, SSE streaming, version negotiation over HTTP,
push notification CRUD, and the A2A error code table) are covered end-to-end
in `packages/ai-parrot-server/tests/integration/test_a2a_v1_roundtrip.py`,
which can safely import `A2AServer` from the same package it's tested in.
Cross-package imports from `ai-parrot`'s own test tree into
`ai-parrot-server` are avoidable here since every scenario below is
expressible purely in terms of `parrot.a2a.client` + `parrot.a2a.models`, so
this file focuses on that: data compatibility at the model layer, and the
client's own version-detection logic, exercised against synthetic v0.3/v1.0
payloads rather than a live cross-package server fixture.
"""
from unittest.mock import AsyncMock, MagicMock

from parrot.a2a.client import A2AClient
from parrot.a2a.models import (
    AgentCard,
    AgentInterface,
    Message,
    Part,
    Task,
    TaskState,
    TaskStatus,
    Role,
    parse_task_state,
    parse_role,
)


class TestAgentCardCrossVersion:
    """A card built as v1.0 must serialize/deserialize correctly as v0.3,
    and vice versa — the two shapes describe the same agent.
    """

    def test_v1_card_roundtrips_through_v03_wire_format(self):
        card = AgentCard(
            name="Agent", description="D", version="1.0", skills=[],
            supported_interfaces=[
                AgentInterface(url="https://a.com/a2a", protocol_binding="JSONRPC", protocol_version="1.0")
            ],
        )
        v03_wire = card.to_dict(version="0.3")
        reparsed = AgentCard.from_dict(v03_wire)
        assert reparsed.url == "https://a.com/a2a"
        assert reparsed.preferred_transport == "JSONRPC"

    def test_v03_card_roundtrips_through_v1_wire_format(self):
        v03_wire = {
            "name": "Agent", "description": "D", "version": "1.0",
            "url": "https://b.com/a2a", "preferredTransport": "JSONRPC",
            "protocolVersion": "0.3.0",
            "capabilities": {"streaming": True},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": [],
        }
        card = AgentCard.from_dict(v03_wire)
        v1_wire = card.to_dict(version="1.0")
        assert v1_wire["supportedInterfaces"][0]["url"] == "https://b.com/a2a"

        reparsed = AgentCard.from_dict(v1_wire)
        assert reparsed.url == "https://b.com/a2a"


class TestTaskCrossVersion:
    """A Task built once must serialize correctly to BOTH wire formats."""

    def test_task_v1_and_v03_share_semantics(self):
        message = Message.user("hello")
        task = Task(
            id="t1", context_id="c1",
            status=TaskStatus(state=TaskState.COMPLETED),
            history=[message],
        )
        v1 = task.to_dict(version="1.0")
        v03 = task.to_dict(version="0.3")

        assert v1["status"]["state"] == "TASK_STATE_COMPLETED"
        assert v03["status"]["state"] == "completed"
        assert v1["history"][0]["role"] == "ROLE_USER"
        assert v03["history"][0]["role"] == "user"

    def test_client_parses_task_regardless_of_wire_format(self):
        client = A2AClient("http://localhost:8080")

        v1_data = {
            "id": "t1", "contextId": "c1",
            "status": {"state": "TASK_STATE_WORKING"},
            "artifacts": [], "history": [],
        }
        v03_data = {
            "id": "t1", "contextId": "c1",
            "status": {"state": "working"},
            "artifacts": [], "history": [],
        }

        task_v1 = client._parse_task(v1_data)
        task_v03 = client._parse_task(v03_data)

        assert task_v1.status.state == TaskState.WORKING
        assert task_v03.status.state == TaskState.WORKING
        assert task_v1.status.state == task_v03.status.state


class TestEnumCompatEdgeCases:
    """Exhaustive TaskState/Role compat parsing across both formats,
    including the CANCELLED (double-L) / CANCELED (single-L) alias.
    """

    def test_all_task_states_parse_both_formats(self):
        pairs = [
            ("submitted", "TASK_STATE_SUBMITTED", TaskState.SUBMITTED),
            ("working", "TASK_STATE_WORKING", TaskState.WORKING),
            ("completed", "TASK_STATE_COMPLETED", TaskState.COMPLETED),
            ("failed", "TASK_STATE_FAILED", TaskState.FAILED),
            ("cancelled", "TASK_STATE_CANCELED", TaskState.CANCELED),
            ("input_required", "TASK_STATE_INPUT_REQUIRED", TaskState.INPUT_REQUIRED),
            ("rejected", "TASK_STATE_REJECTED", TaskState.REJECTED),
        ]
        for v03_value, v1_value, expected in pairs:
            assert parse_task_state(v03_value) == expected
            assert parse_task_state(v1_value) == expected

    def test_auth_required_only_exists_in_v1(self):
        # AUTH_REQUIRED is new in v1.0 — no v0.3 equivalent existed.
        assert parse_task_state("TASK_STATE_AUTH_REQUIRED") == TaskState.AUTH_REQUIRED

    def test_cancelled_double_l_alias_is_same_member_as_canceled(self):
        assert TaskState.CANCELLED is TaskState.CANCELED
        assert TaskState.CANCELLED.value == "TASK_STATE_CANCELED"

    def test_all_roles_parse_both_formats(self):
        assert parse_role("user") == Role.USER
        assert parse_role("ROLE_USER") == Role.USER
        assert parse_role("agent") == Role.AGENT
        assert parse_role("ROLE_AGENT") == Role.AGENT


class TestPartCrossVersion:
    def test_file_part_roundtrips_v03_to_v1(self):
        part = Part(file_uri="https://x.com/f.pdf", file_media_type="application/pdf")
        v03 = part.to_dict(version="0.3")
        reparsed = Part.from_dict(v03)
        v1 = reparsed.to_dict(version="1.0")
        assert v1["url"] == "https://x.com/f.pdf"
        assert v1["mediaType"] == "application/pdf"

    def test_file_part_roundtrips_v1_to_v03(self):
        part = Part(file_uri="https://y.com/f.pdf")
        v1 = part.to_dict(version="1.0")
        reparsed = Part.from_dict(v1)
        v03 = reparsed.to_dict(version="0.3")
        assert v03["file"]["fileWithUri"] == "https://y.com/f.pdf"


class TestClientVersionDetectionEdgeCases:
    async def test_client_v1_client_v03_server_uses_slash_routes(self):
        """v1.0 client talking to a v0.3-only server: after discover()
        detects the v0.3 shape, `send_message()` must hit the SLASH route
        (a real v0.3-only server has no colon routes registered at all).
        """
        client = A2AClient("http://localhost:8080")
        client._server_version = "0.3"

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = AsyncMock(return_value={
            "id": "t1", "contextId": "c1",
            "status": {"state": "completed"},
            "artifacts": [], "history": [],
        })
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=False)

        client._session = MagicMock()
        client._session.post = MagicMock(return_value=cm)

        await client.send_message("hi")

        called_url = client._session.post.call_args[0][0]
        assert called_url.endswith("/a2a/message/send")
        assert not called_url.endswith(":send")

    async def test_v03_client_v1_server_uses_colon_routes(self):
        """v1.0 client (default) talking to a v1.0 server uses colon routes."""
        client = A2AClient("http://localhost:8080")
        assert client._server_version == "1.0"  # optimistic default

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = AsyncMock(return_value={
            "id": "t1", "contextId": "c1",
            "status": {"state": "TASK_STATE_COMPLETED"},
            "artifacts": [], "history": [],
        })
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=False)

        client._session = MagicMock()
        client._session.post = MagicMock(return_value=cm)

        await client.send_message("hi")

        called_url = client._session.post.call_args[0][0]
        assert called_url.endswith("/a2a/message:send")
