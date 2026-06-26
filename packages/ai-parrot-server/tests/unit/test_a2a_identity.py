"""Unit tests for A2A per-user identity extraction (FEAT-260 / TASK-1643).

Tests:
- _extract_identity returns the canonical id from representative A2A requests.
- All supported metadata field paths are checked (in precedence order).
- Absent identity → None returned; no service-identity fallback.
- process_message threads user_id to _ask_agent (gate seam).
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.a2a.models import Message
from parrot.a2a.server import A2AServer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_server() -> A2AServer:
    """Return an A2AServer wrapping a minimal mock agent."""
    agent = MagicMock()
    agent.name = "TestAgent"
    agent.ask = AsyncMock(return_value="agent-response")
    agent.tool_manager = None
    agent.tools = []
    return A2AServer(agent)


def _make_message(metadata: Optional[Dict[str, Any]] = None) -> Message:
    """Return a minimal A2A Message with the given metadata."""
    return Message.user("hello", metadata=metadata)


# ---------------------------------------------------------------------------
# TestExtractIdentity — all field-path variants
# ---------------------------------------------------------------------------


class TestExtractIdentity:
    def test_extract_from_user_id_field(self):
        """Explicit user_id in metadata is the highest-priority source."""
        server = _make_server()
        msg = _make_message({"user_id": "alice@example.com"})
        assert server._extract_identity(msg) == "alice@example.com"

    def test_extract_from_from_email(self):
        """metadata.from.email is the A2A-spec sender object path."""
        server = _make_server()
        msg = _make_message({"from": {"email": "bob@example.com", "id": "oid-123"}})
        assert server._extract_identity(msg) == "bob@example.com"

    def test_extract_from_from_id_when_email_absent(self):
        """metadata.from.id is used when metadata.from.email is absent."""
        server = _make_server()
        msg = _make_message({"from": {"id": "entra-oid-xyz"}})
        assert server._extract_identity(msg) == "entra-oid-xyz"

    def test_extract_from_sender_field(self):
        """Flat metadata.sender field is the third fallback."""
        server = _make_server()
        msg = _make_message({"sender": "carol@example.com"})
        assert server._extract_identity(msg) == "carol@example.com"

    def test_extract_from_ms_user_email_header(self):
        """Microsoft-injected x-ms-user-email header mirror is last fallback."""
        server = _make_server()
        msg = _make_message({"x-ms-user-email": "dave@example.com"})
        assert server._extract_identity(msg) == "dave@example.com"

    def test_user_id_takes_precedence_over_from(self):
        """user_id precedes metadata.from when both are present."""
        server = _make_server()
        msg = _make_message({
            "user_id": "primary@example.com",
            "from": {"email": "secondary@example.com"},
        })
        assert server._extract_identity(msg) == "primary@example.com"

    def test_missing_identity_returns_none(self):
        """Absent identity → None; no service-identity fallback is inserted."""
        server = _make_server()
        msg = _make_message(metadata={})
        result = server._extract_identity(msg)
        assert result is None

    def test_none_metadata_returns_none(self):
        """metadata=None is handled gracefully → None."""
        server = _make_server()
        msg = _make_message(metadata=None)
        result = server._extract_identity(msg)
        assert result is None

    def test_no_service_identity_injected_on_missing_claim(self):
        """Negative: no 'system', 'service', or default identity is injected."""
        server = _make_server()
        msg = _make_message(metadata={})
        result = server._extract_identity(msg)
        # Must be exactly None — nothing else
        assert result is None
        forbidden = {"system", "service", "default", server.agent.name}
        assert result not in forbidden


# ---------------------------------------------------------------------------
# TestProcessMessageThreadsUserId
# ---------------------------------------------------------------------------


class TestProcessMessageThreadsUserId:
    @pytest.mark.asyncio
    async def test_process_message_threads_user_id_to_ask_agent(self):
        """process_message passes user_id from metadata to _ask_agent."""
        server = _make_server()
        msg = _make_message({"user_id": "alice@example.com"})

        # Patch _ask_agent to capture the kwargs
        captured: dict = {}

        async def fake_ask_agent(question, message, *, user_id=None):
            captured["user_id"] = user_id
            return "ok"

        server._ask_agent = fake_ask_agent  # type: ignore[method-assign]
        await server.process_message(msg)
        assert captured.get("user_id") == "alice@example.com"

    @pytest.mark.asyncio
    async def test_process_message_with_no_identity_does_not_crash(self):
        """Absent identity does not crash process_message (gate is in TASK-1644)."""
        server = _make_server()
        msg = _make_message(metadata={})
        # No identity → user_id=None threaded through; gate is in TASK-1644
        task = await server.process_message(msg)
        # Happy path still completes (no gate installed yet)
        assert task is not None

    @pytest.mark.asyncio
    async def test_ask_agent_receives_user_id_keyword(self):
        """_ask_agent accepts user_id as a keyword-only argument."""
        server = _make_server()
        # Verify the signature accepts the keyword argument without raising
        called_with_user_id: list = []

        async def capturing_ask(question, **kwargs):
            called_with_user_id.append(kwargs.get("user_id"))
            return "response"

        server.agent.ask = capturing_ask
        msg = _make_message({"user_id": "eve@example.com"})
        await server.process_message(msg)
        assert called_with_user_id == ["eve@example.com"]
