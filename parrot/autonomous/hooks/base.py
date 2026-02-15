"""Abstract base class for all external hooks."""
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import Any, Optional
import uuid

from navconfig.logging import logging

from .models import HookEvent, HookType


class BaseHook(ABC):
    """Abstract base for all external hooks in AutonomousOrchestrator.

    Concrete hooks must implement ``start()`` and ``stop()``.
    When an external event fires, the hook calls ``on_event()`` which
    delegates to the registered callback (set by ``HookManager``).

    For HTTP-based hooks (Jira, Upload, SharePoint), override
    ``setup_routes(app)`` to register aiohttp handlers.
    """

    hook_type: HookType = HookType.SCHEDULER  # Override in subclass

    def __init__(
        self,
        *,
        name: str = "",
        hook_id: Optional[str] = None,
        enabled: bool = True,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ):
        self.hook_id = hook_id or uuid.uuid4().hex[:12]
        self.name = name or self.__class__.__name__
        self.enabled = enabled
        self.target_type = target_type
        self.target_id = target_id
        self.metadata = metadata or {}
        self._callback: Optional[Callable[[HookEvent], Coroutine[Any, Any, None]]] = None
        self.logger = logging.getLogger(f"parrot.hooks.{self.name}")

    def set_callback(
        self,
        callback: Callable[[HookEvent], Coroutine[Any, Any, None]],
    ) -> None:
        """Set the async callback invoked when an event fires."""
        self._callback = callback

    async def on_event(self, event_data: HookEvent) -> None:
        """Emit a HookEvent to the orchestrator via the registered callback."""
        if self._callback is None:
            self.logger.warning(
                f"Hook '{self.name}' fired but no callback is registered"
            )
            return
        try:
            await self._callback(event_data)
        except Exception as exc:
            self.logger.error(
                f"Hook '{self.name}' callback error: {exc}"
            )

    def _make_event(
        self,
        event_type: str,
        payload: dict | None = None,
        *,
        task: str | None = None,
    ) -> HookEvent:
        """Helper to build a HookEvent with common fields pre-filled."""
        return HookEvent(
            hook_id=self.hook_id,
            hook_type=self.hook_type,
            event_type=event_type,
            payload=payload or {},
            metadata=self.metadata,
            target_type=self.target_type,
            target_id=self.target_id,
            task=task,
        )

    @abstractmethod
    async def start(self) -> None:
        """Start listening for external events."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop listening and release resources."""

    def setup_routes(self, app: Any) -> None:
        """Register aiohttp routes. Override in HTTP-based hooks."""

    def __repr__(self) -> str:
        status = "enabled" if self.enabled else "disabled"
        return f"<{self.__class__.__name__} id={self.hook_id} name={self.name} {status}>"
