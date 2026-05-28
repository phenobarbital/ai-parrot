"""Abstract base class for all external hooks."""
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import Any, Optional
from typing import Protocol, runtime_checkable
import logging
import uuid

from navconfig.logging import logging  # noqa: F811

from .models import HookEvent, HookType

_registry_logger = logging.getLogger("parrot.hooks.registry")


@runtime_checkable
class MessagingHook(Protocol):
    """Interface for messaging-channel hooks (e.g. matrix, telegram).

    Satellite packages implement this protocol and register themselves
    with :class:`HookRegistry`.  The core ``AutonomousOrchestrator``
    can then discover and start messaging hooks without a direct
    compile-time dependency on any channel SDK.
    """

    async def start(self) -> None:
        """Start listening for external events."""
        ...

    async def stop(self) -> None:
        """Stop listening and release resources."""
        ...

    async def on_message(self, message: Any) -> None:
        """Handle an incoming message from the channel."""
        ...


class HookRegistry:
    """Registry for external hook implementations.

    Satellite packages (e.g. ai-parrot-integrations) call
    :meth:`register` at module import time so that the core can
    discover them without a static dependency::

        # packages/ai-parrot-integrations/src/parrot/integrations/matrix/hook.py
        HookRegistry.register("matrix", MatrixHook)

    The registry works gracefully when *no* hooks are registered
    (e.g. when only the core package is installed).
    """

    _hooks: dict[str, type] = {}

    @classmethod
    def register(cls, name: str, hook_cls: type) -> None:
        """Register a hook implementation under ``name``.

        Args:
            name: Channel identifier, e.g. ``"matrix"``, ``"telegram"``.
            hook_cls: Concrete class that implements :class:`MessagingHook`.
        """
        if name in cls._hooks:
            _registry_logger.warning(
                "HookRegistry: '%s' already registered — replacing with %s",
                name,
                hook_cls.__name__,
            )
        cls._hooks[name] = hook_cls
        _registry_logger.debug(
            "HookRegistry: registered '%s' -> %s", name, hook_cls.__name__
        )

    @classmethod
    def get(cls, name: str) -> type | None:
        """Return the registered hook class for ``name``, or ``None``.

        Args:
            name: Channel identifier.

        Returns:
            The hook class, or ``None`` if not registered.
        """
        return cls._hooks.get(name)

    @classmethod
    def available(cls) -> list[str]:
        """Return a list of registered hook names.

        Returns:
            Sorted list of channel identifiers.
        """
        return sorted(cls._hooks.keys())


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
