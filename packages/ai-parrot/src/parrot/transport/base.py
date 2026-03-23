"""Abstract base class for all multi-agent transports."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional


class AbstractTransport(ABC):
    """Abstract base for all multi-agent transports.

    Defines the common interface for agent-to-agent communication.
    Concrete implementations (e.g. ``FilesystemTransport``,
    ``TelegramCrewTransport``) must implement all abstract methods.

    Supports async context manager for lifecycle management::

        async with MyTransport(...) as t:
            await t.send("agent-b", "hello")
    """

    @abstractmethod
    async def start(self) -> None:
        """Start the transport (register presence, begin listening)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the transport (deregister, clean up resources)."""
        ...

    @abstractmethod
    async def send(
        self,
        to: str,
        content: str,
        msg_type: str = "message",
        payload: Optional[Dict[str, Any]] = None,
        reply_to: Optional[str] = None,
    ) -> str:
        """Send a point-to-point message to another agent.

        Args:
            to: Target agent ID or name.
            content: Message content.
            msg_type: Message type identifier.
            payload: Optional structured payload.
            reply_to: Optional message ID this is replying to.

        Returns:
            The message ID of the sent message.
        """
        ...

    @abstractmethod
    async def broadcast(
        self,
        content: str,
        channel: str = "general",
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Broadcast a message to a channel.

        Args:
            content: Message content.
            channel: Target channel name.
            payload: Optional structured payload.
        """
        ...

    @abstractmethod
    async def messages(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Yield incoming point-to-point messages.

        Yields:
            Message dicts with at least ``from``, ``content``, ``msg_id`` keys.
        """
        ...  # pragma: no cover

    @abstractmethod
    async def list_agents(self) -> List[Dict[str, Any]]:
        """List all currently active agents.

        Returns:
            List of agent info dicts with at least ``agent_id`` and ``name``.
        """
        ...

    @abstractmethod
    async def reserve(
        self,
        paths: List[str],
        reason: str = "",
    ) -> bool:
        """Acquire cooperative resource reservations.

        Args:
            paths: List of resource paths to reserve.
            reason: Human-readable reason for the reservation.

        Returns:
            True if all reservations acquired, False if any conflict.
        """
        ...

    @abstractmethod
    async def release(
        self,
        paths: Optional[List[str]] = None,
    ) -> None:
        """Release resource reservations.

        Args:
            paths: Specific paths to release. If None, release all.
        """
        ...

    @abstractmethod
    async def set_status(
        self,
        status: str,
        message: str = "",
    ) -> None:
        """Update this agent's status in the registry.

        Args:
            status: Status string (e.g. "idle", "busy", "working").
            message: Optional human-readable status message.
        """
        ...

    async def __aenter__(self) -> "AbstractTransport":
        """Start the transport and return self."""
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Stop the transport on context exit."""
        await self.stop()
