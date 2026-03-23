"""HookManager — registry and lifecycle coordinator for all hooks."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from navconfig.logging import logging

from .base import BaseHook

if TYPE_CHECKING:
    from parrot.core.events.evb import EventBus


class HookManager:
    """Manages registration, startup, and shutdown of all external hooks.

    The manager injects a callback into each hook so that fired events
    flow into the orchestrator's execution pipeline.

    Optionally, an :class:`EventBus` can be attached via
    :meth:`set_event_bus` to enable distributed dual-emit: every hook
    event is forwarded to both the direct callback *and* the bus on
    channel ``hooks.<hook_type>.<event_type>``.
    """

    def __init__(self) -> None:
        self._hooks: Dict[str, BaseHook] = {}
        self._callback: Optional[Callable] = None
        self._event_bus: Optional["EventBus"] = None
        self.logger = logging.getLogger("parrot.hooks.manager")

    def set_event_callback(self, callback) -> None:
        """Set the async callback that all hooks will invoke on events.

        Typically ``AutonomousOrchestrator._handle_hook_event``.
        """
        self._callback = callback
        dispatch = self._build_dispatch()
        for hook in self._hooks.values():
            hook.set_callback(dispatch)

    def set_event_bus(self, bus: "EventBus") -> None:
        """Attach an :class:`EventBus` for distributed event publishing.

        When set, every hook event is emitted to both the registered
        callback *and* the bus on channel
        ``hooks.<hook_type>.<event_type>``.  If no bus is set, the
        existing callback-only behaviour is preserved unchanged.

        Args:
            bus: An :class:`~parrot.core.events.evb.EventBus` instance.
        """
        self._event_bus = bus
        dispatch = self._build_dispatch()
        for hook in self._hooks.values():
            hook.set_callback(dispatch)
        self.logger.info("HookManager: EventBus attached — dual-emit enabled")

    def _build_dispatch(self) -> Optional[Callable]:
        """Return the effective per-hook callback.

        * No bus → return the raw user callback unchanged.
        * Bus set → return an ``_dual_emit`` wrapper that calls the
          callback *and* emits to the bus.  Either the callback or the
          bus may be absent individually without raising.

        Closure strategy
        ----------------
        ``bus`` is captured at build time (it is invariant once set).
        The user callback is read from ``self._callback`` **at dispatch
        time** — not captured — so hooks built before
        ``set_event_callback()`` is called still see the correct
        callback without needing re-injection.  This eliminates the
        ordering-hazard window where events fired between
        ``set_event_bus()`` and ``set_event_callback()`` would silently
        drop the callback.

        Both sync and async callbacks are supported via
        ``asyncio.iscoroutinefunction()`` inspection.
        """
        bus = self._event_bus

        if bus is None:
            return self._callback

        async def _dual_emit(event) -> None:
            # Read callback at call time — avoids stale-closure issue when
            # set_event_callback() is called after this dispatch was built.
            cb = self._callback
            if cb is not None:
                if asyncio.iscoroutinefunction(cb):
                    await cb(event)
                else:
                    cb(event)
            try:
                await bus.emit(
                    f"hooks.{event.hook_type.value}.{event.event_type}",
                    event.model_dump(),
                )
            except Exception as exc:
                self.logger.warning(
                    "HookManager: EventBus emit failed for %s.%s: %s",
                    event.hook_type.value,
                    event.event_type,
                    exc,
                )

        return _dual_emit

    def register(self, hook: BaseHook) -> str:
        """Register a hook and return its hook_id.

        If a callback is already set, it is injected into the hook
        immediately so it is ready before ``start_all()`` is called.
        """
        if hook.hook_id in self._hooks:
            self.logger.warning(
                f"Hook '{hook.hook_id}' already registered, replacing"
            )
        self._hooks[hook.hook_id] = hook
        dispatch = self._build_dispatch()
        if dispatch is not None:
            hook.set_callback(dispatch)
        self.logger.info(f"Registered hook: {hook!r}")
        return hook.hook_id

    def unregister(self, hook_id: str) -> Optional[BaseHook]:
        """Unregister a hook by ID. Returns the removed hook or None."""
        hook = self._hooks.pop(hook_id, None)
        if hook:
            self.logger.info(f"Unregistered hook: {hook!r}")
        return hook

    def get_hook(self, hook_id: str) -> Optional[BaseHook]:
        """Retrieve a registered hook by ID."""
        return self._hooks.get(hook_id)

    async def start_all(self) -> None:
        """Start all enabled hooks."""
        started = 0
        for hook in self._hooks.values():
            if not hook.enabled:
                self.logger.debug(f"Skipping disabled hook: {hook.name}")
                continue
            try:
                await hook.start()
                started += 1
                self.logger.info(f"Started hook: {hook!r}")
            except Exception as exc:
                self.logger.error(
                    f"Failed to start hook '{hook.name}': {exc}",
                    exc_info=True,
                )
        self.logger.info(
            f"HookManager started {started}/{len(self._hooks)} hooks"
        )

    async def stop_all(self) -> None:
        """Stop all running hooks."""
        stopped = 0
        for hook in self._hooks.values():
            if not hook.enabled:
                continue
            try:
                await hook.stop()
                stopped += 1
                self.logger.debug(f"Stopped hook: {hook!r}")
            except Exception as exc:
                self.logger.error(
                    f"Failed to stop hook '{hook.name}': {exc}",
                    exc_info=True,
                )
        self.logger.info(
            f"HookManager stopped {stopped} hooks"
        )

    def setup_routes(self, app: Any) -> None:
        """Delegate route setup to HTTP-based hooks."""
        for hook in self._hooks.values():
            if hook.enabled:
                hook.setup_routes(app)

    @property
    def hooks(self) -> List[BaseHook]:
        """List all registered hooks."""
        return list(self._hooks.values())

    @property
    def stats(self) -> Dict[str, Any]:
        """Return summary statistics."""
        return {
            "total": len(self._hooks),
            "enabled": sum(1 for h in self._hooks.values() if h.enabled),
            "by_type": self._count_by_type(),
        }

    def _count_by_type(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for hook in self._hooks.values():
            key = hook.hook_type.value
            counts[key] = counts.get(key, 0) + 1
        return counts
