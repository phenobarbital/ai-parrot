"""Tests for the external hooks system."""
import asyncio
import os
import tempfile

import pytest
import pytest_asyncio

from parrot.autonomous.hooks.base import BaseHook
from parrot.autonomous.hooks.manager import HookManager
from parrot.autonomous.hooks.models import (
    HookEvent,
    HookType,
    SchedulerHookConfig,
    FileWatchdogHookConfig,
)
from parrot.autonomous.hooks.scheduler import SchedulerHook
from parrot.autonomous.hooks.file_watchdog import FileWatchdogHook


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class DummyHook(BaseHook):
    """Minimal concrete hook for testing the abstract base."""

    hook_type = HookType.SCHEDULER

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


@pytest.fixture
def dummy_hook():
    return DummyHook(name="test_dummy", target_type="agent", target_id="TestAgent")


@pytest.fixture
def hook_manager():
    return HookManager()


# ---------------------------------------------------------------------------
# BaseHook tests
# ---------------------------------------------------------------------------


class TestBaseHook:
    """Tests for BaseHook lifecycle and callback."""

    def test_repr(self, dummy_hook):
        assert "DummyHook" in repr(dummy_hook)
        assert "enabled" in repr(dummy_hook)

    def test_hook_id_generated(self, dummy_hook):
        assert dummy_hook.hook_id is not None
        assert len(dummy_hook.hook_id) == 12

    @pytest.mark.asyncio
    async def test_start_stop(self, dummy_hook):
        await dummy_hook.start()
        assert dummy_hook.started is True

        await dummy_hook.stop()
        assert dummy_hook.stopped is True

    @pytest.mark.asyncio
    async def test_on_event_no_callback(self, dummy_hook):
        """on_event with no callback should not raise."""
        event = dummy_hook._make_event("test_event", {"key": "value"})
        await dummy_hook.on_event(event)

    @pytest.mark.asyncio
    async def test_on_event_with_callback(self, dummy_hook):
        received = []

        async def callback(event: HookEvent):
            received.append(event)

        dummy_hook.set_callback(callback)
        event = dummy_hook._make_event("test_event", {"key": "value"})
        await dummy_hook.on_event(event)

        assert len(received) == 1
        assert received[0].event_type == "test_event"
        assert received[0].payload == {"key": "value"}
        assert received[0].hook_type == HookType.SCHEDULER

    def test_make_event(self, dummy_hook):
        event = dummy_hook._make_event(
            "test_event", {"data": 42}, task="Do something"
        )
        assert event.hook_id == dummy_hook.hook_id
        assert event.event_type == "test_event"
        assert event.payload == {"data": 42}
        assert event.task == "Do something"
        assert event.target_type == "agent"
        assert event.target_id == "TestAgent"


# ---------------------------------------------------------------------------
# HookManager tests
# ---------------------------------------------------------------------------


class TestHookManager:
    """Tests for HookManager registration and lifecycle."""

    def test_register(self, hook_manager, dummy_hook):
        hook_id = hook_manager.register(dummy_hook)
        assert hook_id == dummy_hook.hook_id
        assert hook_manager.get_hook(hook_id) is dummy_hook

    def test_unregister(self, hook_manager, dummy_hook):
        hook_id = hook_manager.register(dummy_hook)
        removed = hook_manager.unregister(hook_id)
        assert removed is dummy_hook
        assert hook_manager.get_hook(hook_id) is None

    def test_unregister_missing(self, hook_manager):
        result = hook_manager.unregister("nonexistent")
        assert result is None

    def test_stats(self, hook_manager, dummy_hook):
        hook_manager.register(dummy_hook)
        stats = hook_manager.stats
        assert stats["total"] == 1
        assert stats["enabled"] == 1
        assert "scheduler" in stats["by_type"]

    def test_hooks_list(self, hook_manager, dummy_hook):
        hook_manager.register(dummy_hook)
        assert len(hook_manager.hooks) == 1
        assert hook_manager.hooks[0] is dummy_hook

    @pytest.mark.asyncio
    async def test_start_all(self, hook_manager, dummy_hook):
        hook_manager.register(dummy_hook)
        await hook_manager.start_all()
        assert dummy_hook.started is True

    @pytest.mark.asyncio
    async def test_stop_all(self, hook_manager, dummy_hook):
        hook_manager.register(dummy_hook)
        dummy_hook.enabled = True
        dummy_hook.started = True
        await hook_manager.stop_all()
        assert dummy_hook.stopped is True

    @pytest.mark.asyncio
    async def test_skip_disabled_hooks(self, hook_manager):
        hook = DummyHook(name="disabled", enabled=False)
        hook_manager.register(hook)
        await hook_manager.start_all()
        assert hook.started is False

    @pytest.mark.asyncio
    async def test_callback_injection(self, hook_manager, dummy_hook):
        received = []

        async def callback(event):
            received.append(event)

        hook_manager.set_event_callback(callback)
        hook_manager.register(dummy_hook)

        # The callback should have been injected
        event = dummy_hook._make_event("test", {})
        await dummy_hook.on_event(event)
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_callback_injected_on_register(self, hook_manager):
        """Callback set before register should be injected into new hooks."""
        received = []

        async def callback(event):
            received.append(event)

        hook_manager.set_event_callback(callback)
        hook = DummyHook(name="late_register")
        hook_manager.register(hook)

        event = hook._make_event("registered", {})
        await hook.on_event(event)
        assert len(received) == 1


# ---------------------------------------------------------------------------
# SchedulerHook tests
# ---------------------------------------------------------------------------


class TestSchedulerHook:
    """Tests for the APScheduler-based hook."""

    def test_create_from_config(self):
        config = SchedulerHookConfig(
            name="test_sched",
            interval_seconds=30,
            target_type="agent",
            target_id="MyAgent",
        )
        hook = SchedulerHook(config)
        assert hook.name == "test_sched"
        assert hook.hook_type == HookType.SCHEDULER

    @pytest.mark.asyncio
    async def test_scheduler_fires(self):
        """SchedulerHook with short interval should fire quickly."""
        config = SchedulerHookConfig(
            name="fast_sched",
            interval_seconds=1,
            target_type="agent",
            target_id="TestAgent",
            prompt_template="Hello!",
        )
        hook = SchedulerHook(config)
        received = []

        async def callback(event):
            received.append(event)

        hook.set_callback(callback)
        await hook.start()

        # Wait for at least one fire
        await asyncio.sleep(1.5)
        await hook.stop()

        assert len(received) >= 1
        assert received[0].event_type == "heartbeat"
        assert received[0].payload["prompt_template"] == "Hello!"

    @pytest.mark.asyncio
    async def test_scheduler_no_trigger(self):
        """SchedulerHook with no cron/interval should start without error."""
        config = SchedulerHookConfig(
            name="empty_sched",
            target_type="agent",
            target_id="TestAgent",
        )
        hook = SchedulerHook(config)
        await hook.start()
        await hook.stop()


# ---------------------------------------------------------------------------
# FileWatchdogHook tests
# ---------------------------------------------------------------------------


class TestFileWatchdogHook:
    """Tests for the filesystem watchdog hook."""

    @pytest.mark.asyncio
    async def test_file_created_event(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FileWatchdogHookConfig(
                name="test_fs",
                directory=tmpdir,
                patterns=["*"],
                events=["created"],
                target_type="agent",
                target_id="FileAgent",
            )
            hook = FileWatchdogHook(config)
            received = []

            async def callback(event):
                received.append(event)

            hook.set_callback(callback)
            await hook.start()

            # Create a file to trigger an event
            test_file = os.path.join(tmpdir, "test_file.txt")
            with open(test_file, "w") as f:
                f.write("hello")

            # Give watchdog time to detect the change
            await asyncio.sleep(2)
            await hook.stop()

            # Watchdog should have detected the file creation
            assert len(received) >= 1
            assert "file.created" in received[0].event_type

    @pytest.mark.asyncio
    async def test_file_watchdog_nonexistent_dir(self):
        config = FileWatchdogHookConfig(
            name="bad_dir",
            directory="/nonexistent/dir/that/does/not/exist",
            target_type="agent",
            target_id="TestAgent",
        )
        hook = FileWatchdogHook(config)
        with pytest.raises((PermissionError, FileNotFoundError, OSError)):
            await hook.start()


# ---------------------------------------------------------------------------
# HookEvent model tests
# ---------------------------------------------------------------------------


class TestHookEvent:
    """Tests for the HookEvent Pydantic model."""

    def test_create_event(self):
        event = HookEvent(
            hook_id="abc123",
            hook_type=HookType.SCHEDULER,
            event_type="heartbeat",
            payload={"prompt_template": "Hello"},
        )
        assert event.hook_id == "abc123"
        assert event.timestamp is not None
        assert event.metadata == {}

    def test_event_with_routing(self):
        event = HookEvent(
            hook_id="xyz",
            hook_type=HookType.POSTGRES_LISTEN,
            event_type="pg.notification",
            payload={"channel": "test"},
            target_type="crew",
            target_id="ResearchCrew",
            task="Process notification",
        )
        assert event.target_type == "crew"
        assert event.task == "Process notification"
