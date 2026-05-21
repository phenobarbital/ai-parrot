"""Abstract base class for human communication channels."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Awaitable, Callable, ClassVar

if TYPE_CHECKING:
    from ..models import HumanInteraction, HumanResponse


# Signature of the cancel callback registered by HumanInteractionManager.
# Channels invoke it as ``await callback(interaction_id, reason)`` where
# ``reason`` is a short marker describing the user action that triggered
# the cancel (e.g. ``"slash_cancel"``, ``"button_cancel"``, ``"session_end"``).
# Returns True when a pending interaction was found and resolved, False
# otherwise.
CancelCallback = Callable[[str, str], Awaitable[bool]]

# Signature of the response callback registered by HumanInteractionManager.
ResponseCallback = Callable[["HumanResponse"], Awaitable[None]]


class HumanChannel(ABC):
    """Abstraction over a communication channel with humans.

    Concrete implementations handle channel-specific formatting
    (Telegram inline buttons, Teams adaptive cards, CLI prompts, etc.)
    and callback registration for incoming responses.

    Lifecycle:
        Concrete channels may need to start/stop background workers
        (e.g. Telegram long-polling, websocket pumps). Override
        :meth:`start` and :meth:`stop`; the base implementations are
        no-ops so simple channels don't need to override anything.

    Note on async ``register_*`` methods:
        Registration is currently a pure assignment in every concrete
        channel — these methods are kept ``async`` deliberately to leave
        room for channels that need to perform a remote handshake at
        registration time (e.g. subscribing to a webhook topic).
    """

    channel_type: ClassVar[str] = "base"

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start background workers / open connections.

        Default implementation is a no-op. Override for channels that
        need to spin up listeners, open sockets, or subscribe to topics.
        """

    async def stop(self) -> None:
        """Stop background workers / close connections.

        Default implementation is a no-op. Override to release resources
        opened in :meth:`start`.
        """

    # ── Outbound ──────────────────────────────────────────────────────────

    @abstractmethod
    async def send_interaction(
        self,
        interaction: HumanInteraction,
        recipient: str,
    ) -> bool:
        """Send an interaction request to a human via this channel.

        Returns:
            ``True`` when the channel successfully delivered the message
            to ``recipient`` (or accepted it for delivery). ``False`` when
            delivery did not happen for any reason (unknown recipient,
            transient API failure, channel not yet ready). Implementations
            should swallow expected exceptions and return ``False``; the
            manager treats ``False`` as "this recipient was not reached"
            and logs it but does not retry.
        """
        ...

    @abstractmethod
    async def send_notification(
        self,
        recipient: str,
        message: str,
    ) -> None:
        """Send a one-way notification message to a human.

        Used by escalation actions (e.g. ``NotifyAction``) to inform a
        human without expecting a response.
        """
        ...

    @abstractmethod
    async def cancel_interaction(
        self,
        interaction_id: str,
        recipient: str,
    ) -> bool:
        """Cancel/withdraw a pending interaction from the channel.

        Returns:
            ``True`` when the channel had state for ``interaction_id``
            (an outgoing message, a pending prompt, a tracked token)
            and successfully removed/marked it. ``False`` when there
            was nothing to cancel or the channel could not reach its
            remote API. Idempotent: calling twice is safe.
        """
        ...

    # ── Inbound (callback registration) ───────────────────────────────────

    @abstractmethod
    async def register_response_handler(
        self,
        callback: ResponseCallback,
    ) -> None:
        """Register a callback invoked when a human responds.

        The callback is :meth:`HumanInteractionManager.receive_response`.
        It takes a :class:`HumanResponse` and returns ``None``.
        """
        ...

    async def register_cancel_handler(
        self,
        callback: CancelCallback,
    ) -> None:
        """Register a callback invoked when the human cancels from the channel.

        The callback is :meth:`HumanInteractionManager.cancel_pending`.
        It takes ``(interaction_id, reason)`` and returns ``True`` when a
        pending interaction was found and cancelled. Channels should pass
        a meaningful ``reason`` (e.g. ``"slash_cancel"``, ``"button_cancel"``)
        so the audit trail captures the user action.

        Default implementation is a no-op; channels that expose a
        user-facing cancel UI (``/cancel`` command, ✕ button) should
        override this and store the callback so they can resolve pending
        interactions via the manager.
        """

    # ── Introspection ─────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return f"<{type(self).__name__} channel_type={self.channel_type!r}>"
