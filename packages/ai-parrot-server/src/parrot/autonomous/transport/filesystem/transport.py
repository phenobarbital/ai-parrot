"""FilesystemTransport — top-level orchestrator for filesystem-based multi-agent communication."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

from ..base import AbstractTransport
from .channel import ChannelManager
from .config import FilesystemTransportConfig
from .feed import ActivityFeed
from .inbox import InboxManager
from .registry import AgentRegistry
from .reservation import ReservationManager

logger = logging.getLogger(__name__)


class FilesystemTransport(AbstractTransport):
    """Multi-agent transport over the local filesystem.

    Composes ``AgentRegistry``, ``InboxManager``, ``ActivityFeed``,
    ``ChannelManager``, and ``ReservationManager`` into a unified API.
    Manages the agent lifecycle (presence registration, heartbeat loop)
    and exposes the public interface for messaging, broadcasting,
    discovery, and resource reservations.

    Args:
        agent_name: Human-readable name for this agent.
        config: Transport configuration.
        agent_id: Optional explicit agent ID. Generated if not provided.
        role: Agent role string (e.g. "agent", "coordinator").
    """

    def __init__(
        self,
        agent_name: str,
        config: Optional[FilesystemTransportConfig] = None,
        agent_id: Optional[str] = None,
        role: str = "agent",
    ) -> None:
        self._config = config or FilesystemTransportConfig()
        self._name = agent_name
        self._agent_id = agent_id or f"{agent_name.lower()}-{uuid.uuid4().hex[:8]}"
        self._role = role
        self._pid = os.getpid()
        self._hostname = socket.gethostname()
        self._cwd = os.getcwd()

        root = self._config.root_dir
        self._registry = AgentRegistry(root / "registry", self._config)
        self._inbox = InboxManager(root / "inbox", self._agent_id, self._config)
        self._feed = ActivityFeed(root / "feed.jsonl", self._config)
        self._channels = ChannelManager(root / "channels", self._config)
        self._reservations = ReservationManager(root / "reservations", self._agent_id)

        self._presence_task: Optional[asyncio.Task[None]] = None
        self._started = False

    @property
    def agent_id(self) -> str:
        """The unique agent ID for this transport instance."""
        return self._agent_id

    @property
    def agent_name(self) -> str:
        """The human-readable agent name."""
        return self._name

    async def start(self) -> None:
        """Start the transport: register presence, begin heartbeat loop."""
        if self._started:
            return
        self._config.root_dir.mkdir(parents=True, exist_ok=True)
        self._inbox.setup()

        await self._registry.join(
            agent_id=self._agent_id,
            name=self._name,
            pid=self._pid,
            hostname=self._hostname,
            cwd=self._cwd,
            role=self._role,
        )
        await self._feed.emit("agent_joined", {
            "agent_id": self._agent_id,
            "name": self._name,
        })

        self._presence_task = asyncio.create_task(self._presence_loop())
        self._started = True
        logger.info("FilesystemTransport started: %s (%s)", self._name, self._agent_id)

    async def stop(self) -> None:
        """Stop the transport: cancel heartbeat, release reservations, deregister."""
        if not self._started:
            return
        self._started = False

        if self._presence_task is not None:
            self._presence_task.cancel()
            try:
                await self._presence_task
            except asyncio.CancelledError:
                pass
            self._presence_task = None

        self._inbox.stop_watcher()
        await self._reservations.release_all()
        await self._registry.leave(self._agent_id)
        await self._feed.emit("agent_left", {
            "agent_id": self._agent_id,
            "name": self._name,
        })
        logger.info("FilesystemTransport stopped: %s (%s)", self._name, self._agent_id)

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
            to: Target agent name or ID.
            content: Message content.
            msg_type: Message type identifier.
            payload: Optional structured payload.
            reply_to: Optional message ID this replies to.

        Returns:
            The generated message ID.

        Raises:
            ValueError: If the target agent is not found in the registry.
        """
        target = await self._registry.resolve(to)
        if target is None:
            raise ValueError(f"Agent {to!r} not found in registry")
        target_id = target["agent_id"]

        msg_id = await self._inbox.deliver(
            from_agent=self._agent_id,
            from_name=self._name,
            to_agent=target_id,
            content=content,
            msg_type=msg_type,
            payload=payload,
            reply_to=reply_to,
        )
        await self._feed.emit("message_sent", {
            "from": self._agent_id,
            "to": target_id,
            "msg_id": msg_id,
        })
        return msg_id

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
        await self._channels.publish(
            channel=channel,
            from_agent=self._agent_id,
            from_name=self._name,
            content=content,
            payload=payload,
        )
        await self._feed.emit("broadcast", {
            "from": self._agent_id,
            "channel": channel,
        })

    async def messages(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Yield incoming point-to-point messages from this agent's inbox.

        Yields:
            Message dicts in chronological order.
        """
        async for msg in self._inbox.poll():
            yield msg

    async def channel_messages(
        self,
        channel: str = "general",
        since_offset: int = 0,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Yield messages from a broadcast channel.

        Args:
            channel: Channel name.
            since_offset: 0-based offset to start from.

        Yields:
            Channel message dicts.
        """
        async for msg in self._channels.poll(channel, since_offset=since_offset):
            yield msg

    async def list_agents(self) -> List[Dict[str, Any]]:
        """List all currently active agents.

        Returns:
            List of agent info dicts.
        """
        return await self._registry.list_active()

    async def whois(self, name_or_id: str) -> Optional[Dict[str, Any]]:
        """Look up an agent by name or ID.

        Args:
            name_or_id: Agent name or ID.

        Returns:
            Agent info dict, or None if not found.
        """
        return await self._registry.resolve(name_or_id)

    async def reserve(
        self,
        paths: List[str],
        reason: str = "",
    ) -> bool:
        """Acquire cooperative resource reservations.

        Args:
            paths: List of resource paths to reserve.
            reason: Human-readable reason.

        Returns:
            True if all reservations acquired, False if conflict.
        """
        ok = await self._reservations.acquire(paths, reason=reason)
        if ok:
            await self._feed.emit("reservation_acquired", {
                "agent_id": self._agent_id,
                "paths": paths,
            })
        return ok

    async def release(
        self,
        paths: Optional[List[str]] = None,
    ) -> None:
        """Release resource reservations.

        Args:
            paths: Specific paths to release. If None, release all.
        """
        if paths is None:
            await self._reservations.release_all()
        else:
            await self._reservations.release(paths)
        await self._feed.emit("reservation_released", {
            "agent_id": self._agent_id,
            "paths": paths,
        })

    async def set_status(
        self,
        status: str,
        message: str = "",
    ) -> None:
        """Update this agent's status in the registry.

        Args:
            status: Status string (e.g. "idle", "busy").
            message: Optional status message.
        """
        await self._registry.heartbeat(
            self._agent_id,
            status=status,
            message=message,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _presence_loop(self) -> None:
        """Background loop for heartbeat and stale agent garbage collection."""
        while True:
            try:
                await asyncio.sleep(self._config.presence_interval)
                await self._registry.heartbeat(self._agent_id)
                await self._registry.gc_stale()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Presence loop error: %s", exc)
