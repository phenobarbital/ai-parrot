"""Tests for MatrixHook and MatrixHookConfig."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from parrot.autonomous.hooks.base import BaseHook
from parrot.autonomous.hooks.models import (
    HookEvent,
    HookType,
    MatrixHookConfig,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def matrix_config():
    """Basic MatrixHookConfig for testing."""
    return MatrixHookConfig(
        name="test_matrix",
        enabled=True,
        target_type="agent",
        target_id="TestAgent",
        homeserver="http://localhost:8008",
        bot_mxid="@parrot-bot:parrot.local",
        access_token="syt_test_token",
        command_prefix="!ask",
        allowed_users=["@jesus:parrot.local"],
        room_routing={
            "!sales:parrot.local": "SalesAgent",
            "!finance:parrot.local": "FinanceCrew",
        },
    )


@pytest.fixture
def matrix_config_no_prefix():
    """MatrixHookConfig without command prefix."""
    return MatrixHookConfig(
        name="test_matrix_no_prefix",
        target_type="agent",
        target_id="DefaultAgent",
        homeserver="http://localhost:8008",
        bot_mxid="@parrot-bot:parrot.local",
        access_token="syt_test_token",
        command_prefix="",
    )


def _make_mock_event(
    sender: str,
    body: str,
    room_id: str = "!test:parrot.local",
    event_id: str = "$test_event_id",
):
    """Create a mock mautrix message event."""
    event = MagicMock()
    event.sender = sender
    event.room_id = room_id
    event.event_id = event_id
    event.type = "m.room.message"
    event.content = MagicMock()
    event.content.body = body
    event.content.relates_to = None
    return event


# ---------------------------------------------------------------------------
# MatrixHookConfig tests
# ---------------------------------------------------------------------------


class TestMatrixHookConfig:
    """Tests for MatrixHookConfig Pydantic model."""

    def test_defaults(self):
        """Default values are sane."""
        config = MatrixHookConfig()
        assert config.name == "matrix_hook"
        assert config.enabled is True
        assert config.target_type == "agent"
        assert config.homeserver == "http://localhost:8008"
        assert config.command_prefix == "!ask"
        assert config.auto_reply is True
        assert config.device_id == "PARROT"

    def test_allowed_users_normalization(self):
        """Whitespace is stripped from MXIDs."""
        config = MatrixHookConfig(
            allowed_users=["  @user:server  ", "@other:server "]
        )
        assert config.allowed_users == ["@user:server", "@other:server"]

    def test_room_routing(self):
        """Room routing dict is preserved."""
        routing = {"!room1:server": "Agent1", "!room2:server": "Agent2"}
        config = MatrixHookConfig(room_routing=routing)
        assert config.room_routing == routing

    def test_custom_values(self, matrix_config):
        """Custom values are assigned correctly."""
        assert matrix_config.name == "test_matrix"
        assert matrix_config.bot_mxid == "@parrot-bot:parrot.local"
        assert matrix_config.command_prefix == "!ask"
        assert len(matrix_config.allowed_users) == 1
        assert len(matrix_config.room_routing) == 2


# ---------------------------------------------------------------------------
# HookType tests
# ---------------------------------------------------------------------------


class TestMatrixHookType:
    """Verify MATRIX is in the HookType enum."""

    def test_matrix_hook_type_exists(self):
        assert HookType.MATRIX == "matrix"
        assert HookType.MATRIX.value == "matrix"


# ---------------------------------------------------------------------------
# MatrixHook tests (mautrix mocked)
# ---------------------------------------------------------------------------


class TestMatrixHook:
    """Tests for the MatrixHook BaseHook subclass."""

    def _make_hook(self, config):
        """Import and instantiate MatrixHook."""
        from parrot.autonomous.hooks.matrix import MatrixHook
        return MatrixHook(config)

    def test_hook_type(self, matrix_config):
        """Hook type is MATRIX."""
        hook = self._make_hook(matrix_config)
        assert hook.hook_type == HookType.MATRIX

    def test_inherits_base_hook(self, matrix_config):
        """MatrixHook is a BaseHook subclass."""
        hook = self._make_hook(matrix_config)
        assert isinstance(hook, BaseHook)

    def test_repr(self, matrix_config):
        """Repr includes name and status."""
        hook = self._make_hook(matrix_config)
        assert "test_matrix" in repr(hook)
        assert "enabled" in repr(hook)

    def test_target_from_config(self, matrix_config):
        """Target type/id from config are set."""
        hook = self._make_hook(matrix_config)
        assert hook.target_type == "agent"
        assert hook.target_id == "TestAgent"

    @pytest.mark.asyncio
    async def test_message_filtering_wrong_user(self, matrix_config):
        """Messages from non-allowed users are ignored."""
        hook = self._make_hook(matrix_config)
        received = []

        async def on_event(event):
            received.append(event)

        hook.set_callback(on_event)

        # Simulate message from unauthorized user
        event = _make_mock_event("@stranger:parrot.local", "!ask hello")
        await hook._on_room_message(event)

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_message_filtering_missing_prefix(self, matrix_config):
        """Messages without the command prefix are ignored."""
        hook = self._make_hook(matrix_config)
        received = []

        async def on_event(event):
            received.append(event)

        hook.set_callback(on_event)

        # Allowed user, but no command prefix
        event = _make_mock_event("@jesus:parrot.local", "hello world")
        await hook._on_room_message(event)

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_message_accepted(self, matrix_config):
        """Valid message is accepted and emits HookEvent."""
        hook = self._make_hook(matrix_config)
        received = []

        async def on_event(event):
            received.append(event)

        hook.set_callback(on_event)

        event = _make_mock_event(
            "@jesus:parrot.local",
            "!ask What is AI?",
            room_id="!test:parrot.local",
        )
        await hook._on_room_message(event)

        assert len(received) == 1
        hook_event = received[0]
        assert isinstance(hook_event, HookEvent)
        assert hook_event.event_type == "matrix.message"
        assert hook_event.payload["content"] == "What is AI?"
        assert hook_event.payload["sender"] == "@jesus:parrot.local"
        assert hook_event.payload["session_id"].startswith("matrix_")

    @pytest.mark.asyncio
    async def test_room_routing(self, matrix_config):
        """Room routing overrides the default target_id."""
        hook = self._make_hook(matrix_config)
        received = []

        async def on_event(event):
            received.append(event)

        hook.set_callback(on_event)

        event = _make_mock_event(
            "@jesus:parrot.local",
            "!ask revenue report",
            room_id="!sales:parrot.local",
        )
        await hook._on_room_message(event)

        assert len(received) == 1
        assert received[0].target_id == "SalesAgent"

    @pytest.mark.asyncio
    async def test_own_messages_ignored(self, matrix_config):
        """Bot's own messages are not processed."""
        hook = self._make_hook(matrix_config)
        received = []

        async def on_event(event):
            received.append(event)

        hook.set_callback(on_event)

        event = _make_mock_event(
            "@parrot-bot:parrot.local",
            "!ask test",
        )
        await hook._on_room_message(event)

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_no_prefix_mode(self, matrix_config_no_prefix):
        """Without command prefix, all messages are processed."""
        hook = self._make_hook(matrix_config_no_prefix)
        received = []

        async def on_event(event):
            received.append(event)

        hook.set_callback(on_event)

        event = _make_mock_event(
            "@someone:parrot.local",
            "hello world",
        )
        await hook._on_room_message(event)

        assert len(received) == 1
        assert received[0].payload["content"] == "hello world"

    @pytest.mark.asyncio
    async def test_send_reply_without_wrapper(self, matrix_config):
        """send_reply returns False when client not connected."""
        hook = self._make_hook(matrix_config)
        result = await hook.send_reply("!room:server", "test")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_reply_disabled(self, matrix_config):
        """send_reply returns False when auto_reply is disabled."""
        matrix_config.auto_reply = False
        hook = self._make_hook(matrix_config)
        result = await hook.send_reply("!room:server", "test")
        assert result is False


# ---------------------------------------------------------------------------
# Lazy import test
# ---------------------------------------------------------------------------


class TestLazyImport:
    """Test that MatrixHook can be imported from hooks package."""

    def test_import_config(self):
        from parrot.autonomous.hooks import MatrixHookConfig
        assert MatrixHookConfig is not None

    def test_hook_type_enum(self):
        from parrot.autonomous.hooks import HookType
        assert hasattr(HookType, "MATRIX")
