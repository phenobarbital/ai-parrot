"""Unit tests for HookManager EventBus dual-emit (TASK-272)."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from parrot.core.hooks.manager import HookManager
from parrot.core.hooks.models import HookEvent, HookType


def _make_event(hook_type=HookType.SCHEDULER, event_type="tick") -> HookEvent:
    return HookEvent(
        hook_id="test-hook",
        hook_type=hook_type,
        event_type=event_type,
        data={"value": 42},
    )


def _make_hook(hook_id="h1"):
    hook = MagicMock()
    hook.hook_id = hook_id
    hook.enabled = True
    hook.hook_type = HookType.SCHEDULER
    hook.name = hook_id
    hook._callback = None

    def set_cb(cb):
        hook._callback = cb

    hook.set_callback.side_effect = set_cb
    return hook


class TestSetEventBus:
    def test_set_event_bus_stores_bus(self):
        mgr = HookManager()
        bus = MagicMock()
        mgr.set_event_bus(bus)
        assert mgr._event_bus is bus

    def test_set_event_bus_updates_existing_hooks(self):
        mgr = HookManager()
        hook = _make_hook()
        mgr._hooks["h1"] = hook
        bus = MagicMock()
        mgr.set_event_bus(bus)
        hook.set_callback.assert_called()

    def test_without_bus_build_dispatch_returns_callback(self):
        mgr = HookManager()
        cb = AsyncMock()
        mgr._callback = cb
        dispatch = mgr._build_dispatch()
        assert dispatch is cb

    def test_without_callback_or_bus_build_dispatch_returns_none(self):
        mgr = HookManager()
        assert mgr._build_dispatch() is None


class TestDualEmit:
    @pytest.mark.asyncio
    async def test_dual_emit_calls_callback_and_bus(self):
        mgr = HookManager()
        cb = AsyncMock()
        bus = MagicMock()
        bus.emit = AsyncMock(return_value=1)
        mgr._callback = cb
        mgr._event_bus = bus

        dispatch = mgr._build_dispatch()
        event = _make_event(HookType.SCHEDULER, "tick")
        await dispatch(event)

        cb.assert_awaited_once_with(event)
        bus.emit.assert_awaited_once_with(
            "hooks.scheduler.tick",
            event.model_dump(),
        )

    @pytest.mark.asyncio
    async def test_dual_emit_channel_uses_hook_type_and_event_type(self):
        mgr = HookManager()
        mgr._callback = AsyncMock()
        bus = MagicMock()
        bus.emit = AsyncMock(return_value=1)
        mgr._event_bus = bus

        dispatch = mgr._build_dispatch()
        event = _make_event(HookType.POSTGRES_LISTEN, "row_inserted")
        await dispatch(event)

        bus.emit.assert_awaited_once_with(
            "hooks.postgres_listen.row_inserted",
            event.model_dump(),
        )

    @pytest.mark.asyncio
    async def test_no_bus_only_callback_called(self):
        mgr = HookManager()
        cb = AsyncMock()
        mgr._callback = cb

        dispatch = mgr._build_dispatch()
        event = _make_event()
        await dispatch(event)

        cb.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_bus_only_no_callback(self):
        mgr = HookManager()
        bus = MagicMock()
        bus.emit = AsyncMock(return_value=1)
        mgr._event_bus = bus

        dispatch = mgr._build_dispatch()
        event = _make_event()
        await dispatch(event)

        bus.emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bus_emit_failure_does_not_raise(self):
        mgr = HookManager()
        cb = AsyncMock()
        mgr._callback = cb
        bus = MagicMock()
        bus.emit = AsyncMock(side_effect=RuntimeError("redis down"))
        mgr._event_bus = bus

        dispatch = mgr._build_dispatch()
        event = _make_event()
        await dispatch(event)

        cb.assert_awaited_once_with(event)


class TestRegisterWithBus:
    def test_new_hook_registered_after_bus_set_gets_dual_emit(self):
        mgr = HookManager()
        cb = AsyncMock()
        bus = MagicMock()
        mgr.set_event_callback(cb)
        mgr.set_event_bus(bus)

        hook = _make_hook("h2")
        mgr.register(hook)

        hook.set_callback.assert_called()
        injected = hook._callback
        assert injected is not cb

    def test_set_event_callback_after_bus_uses_dual_emit(self):
        mgr = HookManager()
        bus = MagicMock()
        bus.emit = AsyncMock()
        mgr.set_event_bus(bus)

        cb = AsyncMock()
        mgr.set_event_callback(cb)

        dispatch = mgr._build_dispatch()
        assert dispatch is not cb

    @pytest.mark.asyncio
    async def test_stale_closure_hook_sees_callback_set_after_registration(self):
        """Hooks registered between set_event_bus and set_event_callback still
        invoke the callback because _dual_emit reads self._callback at dispatch
        time rather than capturing it at closure-creation time."""
        mgr = HookManager()
        bus = MagicMock()
        bus.emit = AsyncMock(return_value=1)
        mgr.set_event_bus(bus)

        # Register hook BEFORE the callback is set — this is the hazard window.
        hook = _make_hook("stale-window")
        mgr.register(hook)

        # Now set the callback (after registration).
        cb = AsyncMock()
        mgr.set_event_callback(cb)

        # Fire an event through the dispatch that was injected at register time.
        injected_dispatch = hook._callback
        assert injected_dispatch is not None
        event = _make_event()
        await injected_dispatch(event)

        # Dynamic self._callback reference ensures cb is still called.
        cb.assert_awaited_once_with(event)
        bus.emit.assert_awaited_once()


class TestSyncCallback:
    @pytest.mark.asyncio
    async def test_sync_callback_called_without_error(self):
        """A plain synchronous callable registered as the callback should be
        invoked correctly without raising (iscoroutinefunction guard)."""
        mgr = HookManager()
        bus = MagicMock()
        bus.emit = AsyncMock(return_value=1)
        mgr._event_bus = bus

        calls = []
        def sync_cb(event):
            calls.append(event)

        mgr._callback = sync_cb

        dispatch = mgr._build_dispatch()
        event = _make_event()
        await dispatch(event)

        assert len(calls) == 1
        assert calls[0] is event
        bus.emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_callback_still_awaited(self):
        """Async callbacks continue to be awaited correctly after the guard."""
        mgr = HookManager()
        bus = MagicMock()
        bus.emit = AsyncMock(return_value=1)
        mgr._event_bus = bus

        cb = AsyncMock()
        mgr._callback = cb

        dispatch = mgr._build_dispatch()
        event = _make_event()
        await dispatch(event)

        cb.assert_awaited_once_with(event)
