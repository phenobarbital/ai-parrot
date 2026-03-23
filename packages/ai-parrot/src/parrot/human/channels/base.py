"""Abstract base class for human communication channels."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from ..models import HumanInteraction, HumanResponse


class HumanChannel(ABC):
    """Abstraction over a communication channel with humans.

    Concrete implementations handle channel-specific formatting
    (Telegram inline buttons, Teams adaptive cards, CLI prompts, etc.)
    and callback registration for incoming responses.
    """

    channel_type: str = "base"

    @abstractmethod
    async def send_interaction(
        self,
        interaction: "HumanInteraction",
        recipient: str,
    ) -> bool:
        """Send an interaction request to a human via this channel.

        Returns True if the message was delivered successfully.
        """
        ...

    @abstractmethod
    async def register_response_handler(
        self,
        callback: Callable[["HumanResponse"], Awaitable[None]],
    ) -> None:
        """Register a callback invoked when a human responds."""
        ...

    @abstractmethod
    async def send_notification(
        self,
        recipient: str,
        message: str,
    ) -> None:
        """Send a simple notification message to a human."""
        ...

    @abstractmethod
    async def cancel_interaction(
        self,
        interaction_id: str,
        recipient: str,
    ) -> None:
        """Cancel/withdraw a pending interaction from the channel."""
        ...
