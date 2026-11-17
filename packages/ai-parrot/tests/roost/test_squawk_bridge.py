"""Tests for the optional Squawk satellite bridge."""

from __future__ import annotations

import logging
import sys
import types
from typing import Any

import pytest

from parrot.roost import squawk_bridge as sb
from parrot.roost.codec import JsonEnvelopeCodec
from parrot.roost.directory import CapabilityMatch, Locality
from parrot.roost.messages import AgentAddress, LocalEnvelope, RoostMessage
from parrot.roost.performatives import InteractionProtocol, Performative


@pytest.fixture(autouse=True)
def reset_bridge_state() -> None:
    """Keep the process-wide probe and warning state independent between tests."""
    sb.squawk_available.cache_clear()
    sb._WARNED = False


async def test_degrades_without_squawk(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """All bridge operations remain usable when the optional distribution is absent."""
    monkeypatch.setattr(sb.importlib.util, "find_spec", lambda _name: None)

    assert not sb.squawk_available()
    assert isinstance(sb.load_codec(), JsonEnvelopeCodec)
    assert isinstance(sb.new_envelope(correlation_id="c", caller="a"), LocalEnvelope)
    with caplog.at_level(logging.WARNING):
        assert await sb.mount_capabilities(None, []) == []
        assert await sb.mount_capabilities(None, []) == []
    assert sum("satellite not installed" in record.message for record in caplog.records) == 1


async def test_stub_satellite_selects_adapter_envelope_and_mounts(monkeypatch: pytest.MonkeyPatch) -> None:
    """A discoverable satellite selects each lazy integration path."""
    encoded_message: dict[str, Any] = {}

    class StubSerializer:
        """Minimal payload serializer used by the adapter test."""

        def to_payload(self, message: RoostMessage) -> dict[str, Any]:
            encoded_message["message"] = message
            return {"message": message}

        def from_payload(self, payload: dict[str, Any]) -> RoostMessage:
            return payload["message"]

    class StubCallMessage:
        """Capture the keyword contract supplied by ``new_envelope``."""

        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    class StubToolkit:
        """Capture catalog mounts without requiring a real remote connection."""

        def __init__(self, *, remote: str, tool_manager: Any, landing: Any) -> None:
            self.remote = remote
            self.tool_manager = tool_manager
            self.landing = landing

        async def catalog_mount(self, target: str) -> str:
            return f"{self.remote}:{target}"

    codec_module = types.ModuleType("parrot.squawk.schema.codec")
    codec_module.encode = lambda payload: b"stub"
    codec_module.decode = lambda _data: {"message": encoded_message["message"]}
    bus_module = types.ModuleType("parrot.squawk.transport.bus")
    bus_module.BusPayloadSerializer = StubSerializer
    messages_module = types.ModuleType("parrot.squawk.schema.messages")
    messages_module.CallMessage = StubCallMessage
    toolkit_module = types.ModuleType("parrot.squawk.client.toolkit")
    toolkit_module.SquawkRemoteToolkit = StubToolkit

    modules = {
        "parrot.squawk.schema.codec": codec_module,
        "parrot.squawk.transport.bus": bus_module,
        "parrot.squawk.schema.messages": messages_module,
        "parrot.squawk.client.toolkit": toolkit_module,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(sb.importlib.util, "find_spec", lambda name: object() if name == sb.SQUAWK_MODULE else None)

    assert sb.squawk_available()
    codec = sb.load_codec()
    assert isinstance(codec, sb.SquawkCodecAdapter)

    message = _message()
    assert codec.decode(codec.encode(message)) is message
    envelope = sb.new_envelope(correlation_id="corr", caller="caller", token_budget=9)
    assert isinstance(envelope, StubCallMessage)
    assert envelope.cap_id == ""
    assert envelope.args == b""
    assert envelope.budget["tokens"] == 9

    match = CapabilityMatch(agent_name="agent-b", cap_id="docs.search", locality=Locality.REMOTE, cost=1.0)
    assert await sb.mount_capabilities(object(), [match]) == ["agent-b:docs.search"]


def test_resolve_authority_fallbacks_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serialized authority is preserved without a token and missing authority stays fail-closed."""
    monkeypatch.setattr(sb.importlib.util, "find_spec", lambda _name: None)
    context = object()

    assert sb.resolve_authority(_message(permission_context=context)) is context
    assert sb.resolve_authority(_message(permission_context=None)) is None


def test_resolve_authority_prefers_verified_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successfully verified token scope takes precedence over serialized authority."""
    verified_scope = object()

    class StubVerifier:
        """Return a known verified scope for the test token."""

        def parse(self, token: bytes) -> object:
            if token != b"token":
                raise ValueError("invalid token")
            return verified_scope

    biscuit_module = types.ModuleType("parrot.squawk.security.biscuit")
    biscuit_module.BiscuitVerifier = StubVerifier
    monkeypatch.setitem(sys.modules, biscuit_module.__name__, biscuit_module)
    monkeypatch.setattr(sb.importlib.util, "find_spec", lambda name: object() if name == sb.SQUAWK_MODULE else None)

    fallback = object()
    assert sb.resolve_authority(_message(permission_context=object(), auth_token="token")) is verified_scope
    assert sb.resolve_authority(_message(permission_context=fallback, auth_token="invalid")) is fallback


def _message(*, permission_context: Any = None, auth_token: str | None = None) -> RoostMessage:
    """Build the smallest valid Roost message for bridge tests."""
    return RoostMessage(
        performative=Performative.REQUEST,
        protocol=InteractionProtocol.REQUEST,
        conversation_id="conversation",
        sender=AgentAddress(name="agent-a"),
        receivers=[AgentAddress(name="agent-b")],
        envelope=LocalEnvelope(correlation_id="correlation", caller="agent-a"),
        permission_context=permission_context,
        auth_token=auth_token,
    )
