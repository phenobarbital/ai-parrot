"""HookManager — registry and lifecycle coordinator for all hooks."""
from typing import Any, Dict, List, Optional

from navconfig.logging import logging

from .base import BaseHook
from .models import HookEvent


class HookManager:
    """Manages registration, startup, and shutdown of all external hooks.

    The manager injects a callback into each hook so that fired events
    flow into the orchestrator's execution pipeline.
    """

    def __init__(self) -> None:
        self._hooks: Dict[str, BaseHook] = {}
        self._callback = None
        self.logger = logging.getLogger("parrot.hooks.manager")

    def set_event_callback(self, callback) -> None:
        """Set the async callback that all hooks will invoke on events.

        Typically ``AutonomousOrchestrator._handle_hook_event``.
        """
        self._callback = callback
        # Inject into already-registered hooks
        for hook in self._hooks.values():
            hook.set_callback(callback)

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
        if self._callback:
            hook.set_callback(self._callback)
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
