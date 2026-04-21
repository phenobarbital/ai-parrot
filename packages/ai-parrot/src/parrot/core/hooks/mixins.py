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

    Lifecycle
    ---------
    Declare ``HookableAgent`` BEFORE the bot base in the class bases so
    Python MRO routes ``super().cleanup()`` into the bot base's teardown:

        class MyAgent(HookableAgent, JiraSpecialist):  # correct
            ...

        class MyAgent(JiraSpecialist, HookableAgent):  # WRONG — super().cleanup()
            ...                                        # resolves to object

    When the bot is registered with ``BotManager`` the cleanup chain fires
    automatically on aiohttp ``on_cleanup``.
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

    async def cleanup(self) -> None:
        """Stop hooks and delegate to the next class in MRO.

        Cooperative override — concrete subclasses that mix in
        ``HookableAgent`` MUST list it **before** their bot base in
        the bases declaration so MRO resolves ``super().cleanup()``
        to the bot base's ``cleanup()``:

            class MyAgent(HookableAgent, JiraSpecialist):  # correct
                ...

        Never raises — any failure from ``stop_hooks()`` is logged and
        swallowed so that the bot's resource cleanup still runs.
        Swallowing any error from ``stop_hooks()`` is intentional —
        cleanup must not abort because one hook failed to stop.
        """
        if getattr(self, "_hook_manager", None) is not None:
            try:
                await self.stop_hooks()
            except Exception:  # noqa: BLE001 — teardown must not raise
                self._hooks_logger.exception(
                    "HookableAgent: stop_hooks() failed during cleanup"
                )
        parent = getattr(super(), "cleanup", None)
        if callable(parent):
            await parent()
