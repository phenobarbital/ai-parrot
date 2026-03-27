"""Tests for FilesystemHook — integration with AI-Parrot hooks system."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from parrot.autonomous.hooks.models import FilesystemHookConfig, HookType
from parrot.transport.filesystem.config import FilesystemTransportConfig
from parrot.transport.filesystem.hook import FilesystemHook
from parrot.transport.filesystem.transport import FilesystemTransport


class TestFilesystemHookConfig:
    def test_defaults(self):
        """Default config values are correct."""
        config = FilesystemHookConfig()
        assert config.name == "filesystem_hook"
        assert config.enabled is True
        assert config.command_prefix == ""
        assert config.allowed_agents is None
        assert config.target_type == "agent"

    def test_custom_values(self):
        """Custom config values are accepted."""
        config = FilesystemHookConfig(
            name="custom_hook",
            target_id="MyAgent",
            command_prefix="!",
            allowed_agents=["agent-a", "agent-b"],
        )
        assert config.name == "custom_hook"
        assert config.target_id == "MyAgent"
        assert config.command_prefix == "!"
        assert config.allowed_agents == ["agent-a", "agent-b"]


class TestFilesystemHook:
    @pytest.mark.asyncio
    async def test_hook_type(self):
        """Hook type is FILESYSTEM."""
        config = FilesystemHookConfig(target_id="TestAgent")
        hook = FilesystemHook(config=config)
        assert hook.hook_type == HookType.FILESYSTEM

    @pytest.mark.asyncio
    async def test_start_stop(self, tmp_path):
        """Start creates transport, stop cleans up."""
        config = FilesystemHookConfig(
            target_id="TestAgent",
            transport={"root_dir": str(tmp_path), "use_inotify": False, "poll_interval": 0.05},
        )
        hook = FilesystemHook(config=config)
        await hook.start()
        assert hook._transport is not None
        assert hook._listen_task is not None
        await hook.stop()
        assert hook._transport is None
        assert hook._listen_task is None

    @pytest.mark.asyncio
    async def test_dispatch_emits_event(self, tmp_path):
        """Messages from inbox are dispatched as HookEvents."""
        config = FilesystemHookConfig(
            target_id="TestAgent",
            transport={"root_dir": str(tmp_path), "use_inotify": False, "poll_interval": 0.05},
        )
        hook = FilesystemHook(config=config)
        callback = AsyncMock()
        hook.set_callback(callback)

        await hook.start()
        # Send a message to the hook's transport inbox.
        sender_cfg = FilesystemTransportConfig(
            root_dir=tmp_path, use_inotify=False
        )
        async with FilesystemTransport(
            agent_name="Sender", config=sender_cfg
        ) as sender:
            await sender.send("TestAgent", "test message")

        await asyncio.sleep(0.3)  # Let the listen loop pick it up
        await hook.stop()

        assert callback.called
        event = callback.call_args[0][0]
        assert event.event_type == "filesystem.message"
        assert event.payload["content"] == "test message"
        assert event.payload["from_name"] == "Sender"

    @pytest.mark.asyncio
    async def test_command_prefix_filtering(self, tmp_path):
        """Messages without the command prefix are ignored."""
        config = FilesystemHookConfig(
            target_id="TestAgent",
            command_prefix="!",
            transport={"root_dir": str(tmp_path), "use_inotify": False, "poll_interval": 0.05},
        )
        hook = FilesystemHook(config=config)
        callback = AsyncMock()
        hook.set_callback(callback)

        await hook.start()
        sender_cfg = FilesystemTransportConfig(
            root_dir=tmp_path, use_inotify=False
        )
        async with FilesystemTransport(
            agent_name="Sender", config=sender_cfg
        ) as sender:
            # This should be ignored (no prefix).
            await sender.send("TestAgent", "no prefix")
            # This should be dispatched (has prefix).
            await sender.send("TestAgent", "!help me")

        await asyncio.sleep(0.3)
        await hook.stop()

        assert callback.call_count == 1
        event = callback.call_args[0][0]
        assert event.payload["content"] == "help me"

    @pytest.mark.asyncio
    async def test_allowed_agents_filtering(self, tmp_path):
        """Messages from non-allowed agents are ignored."""
        config = FilesystemHookConfig(
            target_id="TestAgent",
            transport={"root_dir": str(tmp_path), "use_inotify": False, "poll_interval": 0.05},
        )
        hook = FilesystemHook(config=config)
        callback = AsyncMock()
        hook.set_callback(callback)

        await hook.start()

        # Create a sender transport.
        sender_cfg = FilesystemTransportConfig(
            root_dir=tmp_path, use_inotify=False
        )
        sender = FilesystemTransport(agent_name="AllowedSender", config=sender_cfg)
        await sender.start()
        sender_id = sender.agent_id

        # Now reconfigure hook with allowed_agents filter.
        await hook.stop()

        config2 = FilesystemHookConfig(
            target_id="TestAgent",
            allowed_agents=[sender_id],
            transport={"root_dir": str(tmp_path), "use_inotify": False, "poll_interval": 0.05},
        )
        hook2 = FilesystemHook(config=config2)
        callback2 = AsyncMock()
        hook2.set_callback(callback2)
        await hook2.start()

        # Allowed sender sends a message.
        await sender.send("TestAgent", "from allowed")

        # Create a blocked sender.
        blocked = FilesystemTransport(
            agent_name="BlockedSender", config=sender_cfg
        )
        await blocked.start()
        await blocked.send("TestAgent", "from blocked")

        await asyncio.sleep(0.3)
        await hook2.stop()
        await sender.stop()
        await blocked.stop()

        # Only the allowed message should have been dispatched.
        assert callback2.call_count == 1
        event = callback2.call_args[0][0]
        assert event.payload["content"] == "from allowed"

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        """Calling stop without start doesn't error."""
        config = FilesystemHookConfig(target_id="TestAgent")
        hook = FilesystemHook(config=config)
        await hook.stop()  # Should not raise

    @pytest.mark.asyncio
    async def test_hook_extends_basehook(self):
        """FilesystemHook is a BaseHook subclass."""
        from parrot.autonomous.hooks.base import BaseHook
        config = FilesystemHookConfig(target_id="TestAgent")
        hook = FilesystemHook(config=config)
        assert isinstance(hook, BaseHook)
