"""HookableAgent mixin — adds hook support to any agent or handler."""
import logging

from .base import BaseHook
from .manager import HookManager
from .models import HookEvent


class HookableAgent:
    """Mixin that adds hook support to any agent or integration handler.

    Provides a ``HookManager`` instance and convenience methods for
    attaching, starting, stopping hooks and handling hook events.

    Usage:
        class MyTelegramBot(TelegramAgentWrapper, HookableAgent):
            def __init__(self, ...):
                super().__init__(...)
                self._init_hooks()

            async def handle_hook_event(self, event: HookEvent) -> None:
                # Custom routing logic
                await self.process_message(event.task or str(event.payload))
    """

    def _init_hooks(self) -> None:
        """Initialize the hook manager. Call in ``__init__``."""
        self._hook_manager: HookManager = HookManager()
        self._hook_manager.set_event_callback(self.handle_hook_event)
        self._hooks_logger = logging.getLogger(
            f"{self.__class__.__module__}.{self.__class__.__name__}.hooks"
        )

    @property
    def hook_manager(self) -> HookManager:
        """Access the underlying HookManager.

        Raises:
            RuntimeError: If ``_init_hooks()`` has not been called.
        """
        if not hasattr(self, "_hook_manager"):
            raise RuntimeError(
                f"{self.__class__.__name__}: call _init_hooks() before "
                "using hook_manager"
            )
        return self._hook_manager

    def attach_hook(self, hook: BaseHook) -> str:
        """Register a hook and return its hook_id.

        Args:
            hook: A BaseHook instance to register.

        Returns:
            The hook's unique identifier.
        """
        return self.hook_manager.register(hook)

    async def start_hooks(self) -> None:
        """Start all registered hooks."""
        await self.hook_manager.start_all()

    async def stop_hooks(self) -> None:
        """Stop all registered hooks."""
        await self.hook_manager.stop_all()

    async def handle_hook_event(self, event: HookEvent) -> None:
        """Handle an incoming hook event.

        Override in subclass for custom routing logic.
        The default implementation logs the event.

        Args:
            event: The HookEvent emitted by a hook.
        """
        logger = getattr(self, "_hooks_logger", None) or logging.getLogger(
            __name__
        )
        logger.info(
            "Hook event received: hook_type=%s event_type=%s hook_id=%s",
            event.hook_type.value,
            event.event_type,
            event.hook_id,
        )
