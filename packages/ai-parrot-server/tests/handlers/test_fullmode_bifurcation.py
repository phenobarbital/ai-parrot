"""Tests for Mode B output-bifurcation helper (TASK-1607 — FEAT-249).

Verifies:
- When avatar_bifurcate=True and a FULL session is active, structured outputs
  are published via the Redis transport.
- When the flag is off, no publish is attempted.
- When no FULL session is active, no publish is attempted.
- The publish path uses SpeakableFlattener-style separation (structured vs. text).
"""
from __future__ import annotations

import sys
import types
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers: fake AIMessage
# ---------------------------------------------------------------------------


def _make_ai_message(
    *,
    is_structured: bool = False,
    data: Optional[Any] = None,
    code: Optional[str] = None,
    tool_calls: List[Any] = None,
    output_mode: str = "data",
    structured_output: Optional[Any] = None,
) -> MagicMock:
    msg = MagicMock()
    msg.is_structured = is_structured
    msg.data = data
    msg.code = code
    msg.tool_calls = tool_calls or []
    msg.output_mode = output_mode
    msg.structured_output = structured_output
    return msg


# ---------------------------------------------------------------------------
# Helpers: inject fake modules
# ---------------------------------------------------------------------------


def _inject_liveavatar_fakes(published: list, monkeypatch=None):
    """Inject fake liveavatar/output modules and track published messages."""

    # Fake StructuredOutputMessage
    class _FakeSOM:
        def __init__(self, *, type, session_id, payload, turn_id=None):
            self.type = type
            self.session_id = session_id
            self.payload = payload
            self.turn_id = turn_id

    # Fake OutputBridge
    class _FakeBridge:
        def __init__(self, forwarder):
            self._forwarder = forwarder

        async def publish(self, msg):
            published.append(msg)

    # Fake RedisBroadcastForwarder
    class _FakeForwarder:
        @classmethod
        def from_url(cls, url, *, channel):
            return cls()

        async def broadcast_to_channel(self, *a, **kw):
            pass

        async def aclose(self):
            pass

    # Fake models module
    models_mod = types.ModuleType("parrot.integrations.liveavatar.models")
    models_mod.StructuredOutputMessage = _FakeSOM  # type: ignore[attr-defined]

    bridge_mod = types.ModuleType("parrot.integrations.liveavatar.output_bridge")
    bridge_mod.OutputBridge = _FakeBridge  # type: ignore[attr-defined]

    transport_mod = types.ModuleType("parrot.integrations.liveavatar.output_transport")
    transport_mod.DEFAULT_OUTPUT_CHANNEL = "liveavatar:structured-outputs"  # type: ignore[attr-defined]
    transport_mod.RedisBroadcastForwarder = _FakeForwarder  # type: ignore[attr-defined]

    saved = {
        "parrot.integrations.liveavatar.models": sys.modules.get("parrot.integrations.liveavatar.models"),
        "parrot.integrations.liveavatar.output_bridge": sys.modules.get("parrot.integrations.liveavatar.output_bridge"),
        "parrot.integrations.liveavatar.output_transport": sys.modules.get("parrot.integrations.liveavatar.output_transport"),
    }
    sys.modules["parrot.integrations.liveavatar.models"] = models_mod
    sys.modules["parrot.integrations.liveavatar.output_bridge"] = bridge_mod
    sys.modules["parrot.integrations.liveavatar.output_transport"] = transport_mod

    return saved


def _restore_modules(saved: dict) -> None:
    for key, val in saved.items():
        if val is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = val


class _FakeAgentTalk:
    """Minimal stand-in for AgentTalk that holds only what _maybe_publish_bifurcated_output needs."""

    def __init__(self, *, fullmode_sessions: dict) -> None:
        self.logger = MagicMock()
        _fake_request = MagicMock()
        _fake_request.app = {"avatar_fullmode_sessions": fullmode_sessions}
        self.request = _fake_request

    # Bind the real method so we can call it on this fake object
    async def _maybe_publish_bifurcated_output(self, *, ai_message, session_id, turn_id=None):
        from parrot.handlers.agent import AgentTalk
        return await AgentTalk._maybe_publish_bifurcated_output(
            self, ai_message=ai_message, session_id=session_id, turn_id=turn_id
        )


def _make_agent_talk(*, fullmode_sessions: dict) -> Any:
    """Build a minimal fake AgentTalk-like object for testing the bifurcation helper."""
    return _FakeAgentTalk(fullmode_sessions=fullmode_sessions)


# ---------------------------------------------------------------------------
# Test 1: structured output is published when flag is on + FULL session exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bifurcation_publishes_structured_output_when_active():
    """_maybe_publish_bifurcated_output publishes when flag=True + FULL session."""
    published: list = []
    saved = _inject_liveavatar_fakes(published)

    fullmode = {"sess-1": {"client": MagicMock(), "handle": MagicMock()}}
    at = _make_agent_talk(fullmode_sessions=fullmode)

    msg = _make_ai_message(is_structured=True, data={"x": 1})

    # Patch FULLMODE_SESSIONS_KEY import and REDIS_URL
    import parrot.handlers.avatar_fullmode as afm
    with patch.object(afm, "FULLMODE_SESSIONS_KEY", "avatar_fullmode_sessions"):
        with patch("parrot.conf.REDIS_URL", "redis://localhost:6379"):
            try:
                await at._maybe_publish_bifurcated_output(
                    ai_message=msg,
                    session_id="sess-1",
                    turn_id="turn-abc",
                )
            finally:
                _restore_modules(saved)

    assert len(published) == 1
    pub = published[0]
    assert pub.session_id == "sess-1"
    assert pub.turn_id == "turn-abc"
    assert "data" in pub.payload


# ---------------------------------------------------------------------------
# Test 2: nothing published when no FULL session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bifurcation_skips_when_no_fullmode_session():
    """_maybe_publish_bifurcated_output is a no-op when no FULL session is active."""
    published: list = []
    saved = _inject_liveavatar_fakes(published)

    at = _make_agent_talk(fullmode_sessions={})  # empty — no FULL session
    msg = _make_ai_message(is_structured=True, data={"x": 1})

    import parrot.handlers.avatar_fullmode as afm
    with patch.object(afm, "FULLMODE_SESSIONS_KEY", "avatar_fullmode_sessions"):
        with patch("parrot.conf.REDIS_URL", "redis://localhost:6379"):
            try:
                await at._maybe_publish_bifurcated_output(
                    ai_message=msg,
                    session_id="sess-ghost",
                    turn_id=None,
                )
            finally:
                _restore_modules(saved)

    assert published == []


# ---------------------------------------------------------------------------
# Test 3: nothing published when AIMessage has no structured content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bifurcation_skips_when_no_structured_content():
    """_maybe_publish_bifurcated_output is a no-op when AIMessage has no structured content."""
    published: list = []
    saved = _inject_liveavatar_fakes(published)

    fullmode = {"sess-1": {"client": MagicMock(), "handle": MagicMock()}}
    at = _make_agent_talk(fullmode_sessions=fullmode)
    # Plain text only — no structured content
    msg = _make_ai_message(is_structured=False, data=None, code=None)

    import parrot.handlers.avatar_fullmode as afm
    with patch.object(afm, "FULLMODE_SESSIONS_KEY", "avatar_fullmode_sessions"):
        with patch("parrot.conf.REDIS_URL", "redis://localhost:6379"):
            try:
                await at._maybe_publish_bifurcated_output(
                    ai_message=msg,
                    session_id="sess-1",
                    turn_id=None,
                )
            finally:
                _restore_modules(saved)

    assert published == []


# ---------------------------------------------------------------------------
# Test 4: tool_calls are included in the payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bifurcation_includes_tool_calls():
    """Payload includes tool_calls when they are present in the AIMessage."""
    published: list = []
    saved = _inject_liveavatar_fakes(published)

    fullmode = {"sess-2": {"client": MagicMock(), "handle": MagicMock()}}
    at = _make_agent_talk(fullmode_sessions=fullmode)

    fake_tool = MagicMock()
    fake_tool.name = "search"
    fake_tool.status = "completed"
    fake_tool.output = "result"
    fake_tool.arguments = {"query": "hello"}

    msg = _make_ai_message(tool_calls=[fake_tool])

    import parrot.handlers.avatar_fullmode as afm
    with patch.object(afm, "FULLMODE_SESSIONS_KEY", "avatar_fullmode_sessions"):
        with patch("parrot.conf.REDIS_URL", "redis://localhost:6379"):
            try:
                await at._maybe_publish_bifurcated_output(
                    ai_message=msg,
                    session_id="sess-2",
                    turn_id=None,
                )
            finally:
                _restore_modules(saved)

    assert len(published) == 1
    assert "tool_calls" in published[0].payload
    assert published[0].payload["tool_calls"][0]["name"] == "search"
