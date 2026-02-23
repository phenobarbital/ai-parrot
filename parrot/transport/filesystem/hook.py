"""FilesystemHook — integration with AI-Parrot's autonomous hooks system."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from parrot.autonomous.hooks.base import BaseHook
from parrot.autonomous.hooks.models import FilesystemHookConfig, HookType

from .config import FilesystemTransportConfig
from .transport import FilesystemTransport


class FilesystemHook(BaseHook):
    """Hook connecting agents to FilesystemTransport.

    Listens to the agent's inbox for incoming messages and dispatches
    them as ``HookEvent`` instances via ``on_event()``. Follows the
    ``WhatsAppRedisHook`` pattern exactly.

    Supports ``command_prefix`` and ``allowed_agents`` filtering.

    Args:
        config: FilesystemHookConfig with transport and filtering settings.
        **kwargs: Additional keyword arguments passed to BaseHook.
    """

    hook_type = HookType.FILESYSTEM

    def __init__(self, config: FilesystemHookConfig, **kwargs: Any) -> None:
        super().__init__(
            name=config.name,
            enabled=config.enabled,
            target_type=config.target_type,
            target_id=config.target_id,
            metadata=config.metadata,
            **kwargs,
        )
        self._config = config
        self._transport: Optional[FilesystemTransport] = None
        self._listen_task: Optional[asyncio.Task[None]] = None

        # Pre-process filters.
        self._allowed_agents = (
            set(config.allowed_agents) if config.allowed_agents else None
        )

    async def start(self) -> None:
        """Start the transport and begin listening for messages."""
        transport_config = FilesystemTransportConfig(**self._config.transport)
        agent_name = self._config.target_id or self._config.name
        self._transport = FilesystemTransport(
            agent_name=agent_name,
            config=transport_config,
        )
        await self._transport.start()
        self._listen_task = asyncio.create_task(self._listen_loop())
        self.logger.info(
            "FilesystemHook '%s' started for agent '%s'",
            self.name,
            agent_name,
        )

    async def stop(self) -> None:
        """Stop listening and shut down the transport."""
        if self._listen_task is not None:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        if self._transport is not None:
            await self._transport.stop()
            self._transport = None

        self.logger.info("FilesystemHook '%s' stopped", self.name)

    async def _listen_loop(self) -> None:
        """Main listening loop: poll inbox and dispatch messages."""
        try:
            async for msg in self._transport.messages():
                try:
                    await self._dispatch(msg)
                except Exception as exc:
                    self.logger.error(
                        "Error dispatching filesystem message: %s", exc
                    )
        except asyncio.CancelledError:
            self.logger.debug("Filesystem listener loop cancelled")
        except Exception as exc:
            self.logger.error(
                "Filesystem listener loop error: %s", exc
            )

    async def _dispatch(self, msg: Dict[str, Any]) -> None:
        """Filter and dispatch a message as a HookEvent.

        Args:
            msg: Raw message dict from the inbox.
        """
        from_agent = msg.get("from", "")
        from_name = msg.get("from_name", from_agent)
        content = msg.get("content", "")

        # 1. Filter by allowed_agents.
        if self._allowed_agents and from_agent not in self._allowed_agents:
            self.logger.debug(
                "Ignoring message from non-allowed agent: %s", from_agent
            )
            return

        # 2. Check command_prefix.
        if self._config.command_prefix:
            if not content.startswith(self._config.command_prefix):
                return
            content = content[len(self._config.command_prefix):].strip()

        if not content:
            return

        # 3. Build and emit HookEvent.
        event = self._make_event(
            event_type="filesystem.message",
            payload={
                "from": from_agent,
                "from_name": from_name,
                "content": content,
                "original_content": msg.get("content", ""),
                "msg_id": msg.get("id", ""),
                "msg_type": msg.get("type", "message"),
                "payload": msg.get("payload", {}),
                "reply_to": msg.get("reply_to"),
            },
            task=content,
        )

        self.logger.info(
            "Filesystem message from %s (%s): '%s' -> %s",
            from_name,
            from_agent,
            content[:50],
            self.target_id or "default",
        )

        await self.on_event(event)
