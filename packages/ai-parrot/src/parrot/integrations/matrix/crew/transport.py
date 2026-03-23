"""Matrix crew transport orchestrator.

Top-level lifecycle manager for a Matrix multi-agent crew.
Manages the ``MatrixAppService``, coordinator, registry, and per-agent wrappers.
Supports the async context-manager protocol for clean lifecycle management.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

from .config import MatrixCrewConfig, MatrixCrewAgentEntry
from .coordinator import MatrixCoordinator
from .crew_wrapper import MatrixCrewAgentWrapper
from .mention import parse_mention
from .registry import MatrixAgentCard, MatrixCrewRegistry


class MatrixCrewTransport:
    """Top-level orchestrator for a Matrix multi-agent crew.

    Manages the ``MatrixAppService``, coordinator, registry, and per-agent
    wrappers.  Supports ``async with`` for lifecycle management.

    Usage::

        transport = MatrixCrewTransport.from_yaml("matrix_crew.yaml")
        async with transport:
            # Crew is running — blocks until context exits
            ...

    Args:
        config: Validated ``MatrixCrewConfig`` instance.
    """

    def __init__(self, config: MatrixCrewConfig) -> None:
        self._config = config
        self._appservice: Optional[object] = None  # MatrixAppService
        self._coordinator: Optional[MatrixCoordinator] = None
        self._registry = MatrixCrewRegistry()
        self._wrappers: Dict[str, MatrixCrewAgentWrapper] = {}
        self._room_to_agent: Dict[str, str] = {}  # dedicated room → agent name
        self._agent_mxids: set[str] = set()  # all virtual MXIDs (for self-filter)
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, path: str) -> "MatrixCrewTransport":
        """Load crew configuration from a YAML file.

        Args:
            path: Path to the YAML configuration file.

        Returns:
            A new ``MatrixCrewTransport`` instance.
        """
        config = MatrixCrewConfig.from_yaml(path)
        return cls(config)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialize and start all crew components.

        Sequence:
        1. Create ``MatrixAppService`` from config.
        2. Register virtual users (one per agent).
        3. Build room-to-agent map.
        4. Create ``MatrixCrewAgentWrapper`` for each agent.
        5. Register agents in the registry (``MatrixAgentCard``).
        6. Join agents to ``general_room_id`` + dedicated rooms.
        7. Create and start the coordinator (pins status board).
        8. Register event callback on the AppService.
        9. Start the AppService HTTP listener.
        """
        from ..appservice import MatrixAppService
        from ..models import MatrixAppServiceConfig

        self.logger.info("Starting Matrix crew transport …")

        # 1 — Build AppService config from crew config
        as_config = MatrixAppServiceConfig(
            as_token=self._config.as_token,
            hs_token=self._config.hs_token,
            homeserver=self._config.homeserver_url,
            server_name=self._config.server_name,
            listen_port=self._config.appservice_port,
            bot_localpart=self._config.bot_mxid.split(":")[0].lstrip("@"),
            agent_mxid_map={
                name: entry.mxid_localpart
                for name, entry in self._config.agents.items()
            },
            auto_join_rooms=[self._config.general_room_id],
        )

        self._appservice = MatrixAppService(as_config)

        # 2 — Register virtual users and collect MXIDs
        await self._appservice.start()  # start AS first (need intent API)

        for agent_name, entry in self._config.agents.items():
            mxid = await self._appservice.register_agent(
                agent_name, entry.display_name
            )
            self._agent_mxids.add(mxid)
            self.logger.info("Registered virtual user %s for agent '%s'", mxid, agent_name)

        # Add coordinator bot MXID to the filter set
        self._agent_mxids.add(self._config.bot_mxid)

        # 3 — Build room → agent map
        for agent_name, entry in self._config.agents.items():
            if entry.dedicated_room_id:
                self._room_to_agent[entry.dedicated_room_id] = agent_name

        # 4 — Create agent wrappers
        for agent_name, entry in self._config.agents.items():
            wrapper = MatrixCrewAgentWrapper(
                agent_name=agent_name,
                config=entry,
                appservice=self._appservice,
                registry=self._registry,
                coordinator=None,  # patched after coordinator creation below
                server_name=self._config.server_name,
                streaming=self._config.streaming,
                max_message_length=self._config.max_message_length,
            )
            self._wrappers[agent_name] = wrapper

        # 5 — Register agents in registry
        for agent_name, entry in self._config.agents.items():
            mxid = f"@{entry.mxid_localpart}:{self._config.server_name}"
            card = MatrixAgentCard(
                agent_name=agent_name,
                display_name=entry.display_name,
                mxid=mxid,
                skills=entry.skills,
            )
            await self._registry.register(card)

        # 6 — Join agents to rooms
        for agent_name, entry in self._config.agents.items():
            # General room
            try:
                await self._appservice.ensure_agent_in_room(
                    agent_name, self._config.general_room_id
                )
            except Exception as exc:
                self.logger.warning(
                    "Could not join agent '%s' to general room: %s",
                    agent_name, exc,
                )
            # Dedicated room
            if entry.dedicated_room_id:
                try:
                    await self._appservice.ensure_agent_in_room(
                        agent_name, entry.dedicated_room_id
                    )
                except Exception as exc:
                    self.logger.warning(
                        "Could not join agent '%s' to dedicated room %s: %s",
                        agent_name, entry.dedicated_room_id, exc,
                    )

        # 7 — Create and start coordinator
        # Coordinator uses the bot intent (coordinator bot) as the client proxy
        coordinator_client = _AppServiceBotClient(
            appservice=self._appservice,
            room_id=self._config.general_room_id,
        )
        self._coordinator = MatrixCoordinator(
            client=coordinator_client,
            registry=self._registry,
            general_room_id=self._config.general_room_id,
        )

        # Patch wrappers with coordinator reference now that it's created
        for wrapper in self._wrappers.values():
            wrapper._coordinator = self._coordinator

        if self._config.pinned_registry:
            await self._coordinator.start()

        # 8 — Register event callback
        self._appservice.set_event_callback(self.on_room_message)

        self.logger.info("Matrix crew transport started — %d agents online", len(self._wrappers))

    async def stop(self) -> None:
        """Graceful shutdown: stop coordinator, unregister agents, stop AS."""
        self.logger.info("Stopping Matrix crew transport …")

        if self._coordinator:
            await self._coordinator.stop()

        # Unregister agents from registry
        for agent_name in list(self._wrappers.keys()):
            await self._registry.unregister(agent_name)

        if self._appservice:
            await self._appservice.stop()

        self.logger.info("Matrix crew transport stopped")

    # ------------------------------------------------------------------
    # Message routing
    # ------------------------------------------------------------------

    async def on_room_message(
        self,
        room_id: str,
        sender: str,
        body: str,
        event_id,
    ) -> None:
        """Route an incoming Matrix room message to the correct agent wrapper.

        Routing priority:
        1. Ignore messages from virtual agent MXIDs or the coordinator bot.
        2. Dedicated room → route to the owning agent.
        3. ``@mention`` in body → route to the mentioned agent.
        4. ``unaddressed_agent`` configured → route to the default agent.
        5. Otherwise → ignore.

        Args:
            room_id: Matrix room ID.
            sender: Sender's full MXID.
            body: Plain-text message body.
            event_id: Matrix event ID.
        """
        # 1 — Ignore self (virtual agent MXIDs + coordinator)
        if sender in self._agent_mxids:
            return

        event_id_str = str(event_id) if event_id else ""

        # 2 — Dedicated room routing
        if room_id in self._room_to_agent:
            agent_name = self._room_to_agent[room_id]
            wrapper = self._wrappers.get(agent_name)
            if wrapper:
                self.logger.debug(
                    "Routing to dedicated-room agent '%s'", agent_name
                )
                await wrapper.handle_message(room_id, sender, body, event_id_str)
                return

        # 3 — @mention routing
        localpart = parse_mention(body, self._config.server_name)
        if localpart:
            # Find the wrapper whose mxid_localpart matches
            for agent_name, entry in self._config.agents.items():
                if entry.mxid_localpart == localpart:
                    wrapper = self._wrappers.get(agent_name)
                    if wrapper:
                        self.logger.debug(
                            "Routing @%s mention to agent '%s'",
                            localpart, agent_name,
                        )
                        await wrapper.handle_message(
                            room_id, sender, body, event_id_str
                        )
                        return

        # 4 — Default / unaddressed agent
        if self._config.unaddressed_agent:
            wrapper = self._wrappers.get(self._config.unaddressed_agent)
            if wrapper:
                self.logger.debug(
                    "Routing to default agent '%s'",
                    self._config.unaddressed_agent,
                )
                await wrapper.handle_message(room_id, sender, body, event_id_str)
                return

        # 5 — Ignore
        self.logger.debug(
            "No routing match for message in %s from %s", room_id, sender
        )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "MatrixCrewTransport":
        """Start the crew on context entry."""
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        """Stop the crew on context exit."""
        await self.stop()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _AppServiceBotClient:
    """Thin adapter that exposes ``send_text`` / ``edit_message`` /
    ``set_room_state`` using the bot intent from ``MatrixAppService``.

    This allows ``MatrixCoordinator`` to use the coordinator bot's identity
    without needing a full ``MatrixClientWrapper``.
    """

    def __init__(self, appservice, room_id: str) -> None:
        self._appservice = appservice
        self._default_room_id = room_id

    async def send_text(self, room_id: str, text: str) -> str:
        """Send text as the coordinator bot.

        Args:
            room_id: Target room.
            text: Message text.

        Returns:
            Event ID string.
        """
        return await self._appservice.send_as_bot(room_id, text)

    async def edit_message(
        self, room_id: str, event_id: str, new_text: str
    ) -> str:
        """Edit a message as the coordinator bot.

        Args:
            room_id: Room containing the message.
            event_id: Event ID to edit.
            new_text: New message text.

        Returns:
            Event ID of the edit event.
        """
        from mautrix.types import (  # type: ignore
            EventID,
            MessageType,
            RoomID,
            TextMessageEventContent,
        )

        content = TextMessageEventContent(
            msgtype=MessageType.TEXT,
            body=f"* {new_text}",
        )
        content.set_edit(EventID(event_id))

        intent = self._appservice.bot_intent
        ev_id = await intent.send_message(RoomID(room_id), content)
        return str(ev_id)

    async def set_room_state(
        self, room_id: str, event_type: str, content: dict
    ) -> None:
        """Set a room state event via the bot intent.

        Args:
            room_id: Target room.
            event_type: State event type string.
            content: Event content dict.
        """
        from mautrix.types import EventType, RoomID  # type: ignore

        evt_type = EventType.find(
            event_type, t_class=EventType.Class.STATE
        )
        await self._appservice.bot_intent.send_state_event(
            RoomID(room_id), evt_type, content
        )
