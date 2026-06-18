"""Unit tests for FullModeRoomObserver (TASK-1596).

Verifies:
- Instantiation with a FullModeSessionHandle.
- connect() handles missing livekit_url gracefully (Q-room-token gate).
- disconnect() is idempotent.
- _on_data() ignores non-agent-response topics.
- _on_data() handles malformed JSON without crashing.
- _on_data() forwards events to OutputBridge when connected.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.liveavatar.fullmode_observer import FullModeRoomObserver
from parrot.integrations.liveavatar.models import FullModeSessionHandle


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handle() -> FullModeSessionHandle:
    """FullModeSessionHandle with livekit_url set."""
    return FullModeSessionHandle(
        session_id="s1",
        liveavatar_session_id="la1",
        session_token="tok",
        ws_url="",
        agent_name="agent",
        livekit_url="wss://test.livekit.cloud",
        livekit_client_token="eyJ...",
    )


@pytest.fixture
def handle_no_url() -> FullModeSessionHandle:
    """FullModeSessionHandle WITHOUT livekit_url (Q-room-token gate scenario)."""
    return FullModeSessionHandle(
        session_id="s1",
        liveavatar_session_id="la1",
        session_token="tok",
        ws_url="",
        agent_name="agent",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFullModeRoomObserverInstantiation:
    """Tests for FullModeRoomObserver construction."""

    def test_instantiates_with_handle(self, handle: FullModeSessionHandle) -> None:
        """FullModeRoomObserver can be instantiated with a FullModeSessionHandle."""
        observer = FullModeRoomObserver(handle)
        assert observer._handle is handle
        assert observer._bridge is None
        assert observer._connected is False

    def test_instantiates_with_output_bridge(
        self, handle: FullModeSessionHandle
    ) -> None:
        """FullModeRoomObserver accepts an optional OutputBridge."""
        fake_bridge = MagicMock()
        observer = FullModeRoomObserver(handle, output_bridge=fake_bridge)
        assert observer._bridge is fake_bridge

    def test_connected_property_false_by_default(
        self, handle: FullModeSessionHandle
    ) -> None:
        """connected property returns False before connect() is called."""
        observer = FullModeRoomObserver(handle)
        assert observer.connected is False


class TestConnect:
    """Tests for FullModeRoomObserver.connect()."""

    async def test_connect_no_livekit_url_does_not_crash(
        self, handle_no_url: FullModeSessionHandle
    ) -> None:
        """connect() logs a warning and returns when livekit_url is empty."""
        observer = FullModeRoomObserver(handle_no_url)
        # Must not raise
        await observer.connect()
        # Observer must NOT be marked as connected
        assert observer._connected is False

    async def test_connect_with_url_stays_in_stub_mode(
        self, handle: FullModeSessionHandle
    ) -> None:
        """connect() with a URL stays in stub mode (Q-room-token not resolved)."""
        observer = FullModeRoomObserver(handle)
        await observer.connect()
        # Stub mode: not connected until Q-room-token is resolved
        assert observer._connected is False


class TestDisconnect:
    """Tests for FullModeRoomObserver.disconnect()."""

    async def test_disconnect_idempotent_when_not_connected(
        self, handle: FullModeSessionHandle
    ) -> None:
        """disconnect() is safe to call multiple times."""
        observer = FullModeRoomObserver(handle)
        await observer.disconnect()
        await observer.disconnect()
        assert observer._connected is False

    async def test_disconnect_resets_connected_flag(
        self, handle: FullModeSessionHandle
    ) -> None:
        """disconnect() sets _connected to False."""
        observer = FullModeRoomObserver(handle)
        observer._connected = True  # simulate connected state
        await observer.disconnect()
        assert observer._connected is False

    async def test_disconnect_handles_room_error(
        self, handle: FullModeSessionHandle
    ) -> None:
        """disconnect() handles room.disconnect() errors gracefully."""
        observer = FullModeRoomObserver(handle)
        # Inject a fake room that raises on use
        observer._room = MagicMock()
        observer._connected = True

        # Must not raise
        await observer.disconnect()
        assert observer._connected is False
        assert observer._room is None


class TestOnData:
    """Tests for FullModeRoomObserver._on_data()."""

    async def test_ignores_non_agent_response_topic(
        self, handle: FullModeSessionHandle
    ) -> None:
        """_on_data ignores messages on topics other than 'agent-response'."""
        observer = FullModeRoomObserver(handle)
        # Should not raise and should not forward anything
        await observer._on_data(b'{"event_type": "test"}', "other-topic")

    async def test_handles_malformed_json(
        self, handle: FullModeSessionHandle
    ) -> None:
        """_on_data handles malformed JSON without crashing."""
        observer = FullModeRoomObserver(handle)
        await observer._on_data(b"not-json", "agent-response")

    async def test_handles_empty_bytes(
        self, handle: FullModeSessionHandle
    ) -> None:
        """_on_data handles empty bytes without crashing."""
        observer = FullModeRoomObserver(handle)
        await observer._on_data(b"", "agent-response")

    async def test_processes_valid_event(
        self, handle: FullModeSessionHandle
    ) -> None:
        """_on_data processes a valid agent-response event (no bridge → only logging)."""
        observer = FullModeRoomObserver(handle)
        event_data = b'{"event_type": "avatar.speak_started", "session_id": "la1", "text": ""}'
        # Must not raise even without a bridge
        await observer._on_data(event_data, "agent-response")

    async def test_forwards_to_output_bridge(
        self, handle: FullModeSessionHandle
    ) -> None:
        """_on_data forwards valid events to OutputBridge when available."""
        import sys
        import types

        # Inject fake StructuredOutputMessage
        fake_msg_cls = MagicMock()
        fake_msg_cls.return_value = MagicMock()

        fake_models_mod = types.ModuleType(
            "parrot.integrations.liveavatar.livekit_agent.models"
        )
        fake_models_mod.StructuredOutputMessage = fake_msg_cls  # type: ignore[attr-defined]

        fake_bridge = MagicMock()
        fake_bridge.publish = AsyncMock()

        observer = FullModeRoomObserver(handle, output_bridge=fake_bridge)

        saved = sys.modules.get("parrot.integrations.liveavatar.livekit_agent.models")
        sys.modules[
            "parrot.integrations.liveavatar.livekit_agent.models"
        ] = fake_models_mod

        try:
            event_data = b'{"event_type": "user.transcription", "session_id": "la1", "text": "hello"}'
            await observer._on_data(event_data, "agent-response")
        finally:
            if saved is None:
                sys.modules.pop(
                    "parrot.integrations.liveavatar.livekit_agent.models", None
                )
            else:
                sys.modules[
                    "parrot.integrations.liveavatar.livekit_agent.models"
                ] = saved

        fake_bridge.publish.assert_awaited_once()

    async def test_on_data_does_not_raise_on_bridge_error(
        self, handle: FullModeSessionHandle
    ) -> None:
        """_on_data swallows OutputBridge publish errors gracefully."""
        import sys
        import types

        fake_msg_cls = MagicMock()
        fake_msg_cls.return_value = MagicMock()

        fake_models_mod = types.ModuleType(
            "parrot.integrations.liveavatar.livekit_agent.models"
        )
        fake_models_mod.StructuredOutputMessage = fake_msg_cls  # type: ignore[attr-defined]

        fake_bridge = MagicMock()
        fake_bridge.publish = AsyncMock(side_effect=RuntimeError("bridge error"))

        observer = FullModeRoomObserver(handle, output_bridge=fake_bridge)

        saved = sys.modules.get("parrot.integrations.liveavatar.livekit_agent.models")
        sys.modules[
            "parrot.integrations.liveavatar.livekit_agent.models"
        ] = fake_models_mod

        try:
            event_data = b'{"event_type": "avatar.transcription", "session_id": "la1"}'
            # Must not raise even when OutputBridge fails
            await observer._on_data(event_data, "agent-response")
        finally:
            if saved is None:
                sys.modules.pop(
                    "parrot.integrations.liveavatar.livekit_agent.models", None
                )
            else:
                sys.modules[
                    "parrot.integrations.liveavatar.livekit_agent.models"
                ] = saved
