"""Channel Manager for Matrix agent swarm channels (FEAT-463).

Materialises declared ``ChannelConfig`` entries as Matrix rooms — creating
them when missing, joining member agents, and publishing ``m.parrot.channel``
room state — and resolves ``room_id <-> ChannelConfig`` for the transport.
Also supports an optional Matrix Space grouping channels and tunnels as
children.
"""
import logging
from typing import Dict, List, Optional

from ..appservice import MatrixAppService
from ..events import ChannelStateContent, ParrotEventType
from .config import ChannelConfig, MatrixCrewConfig

logger = logging.getLogger(__name__)


class ChannelManager:
    """Materialise declared channels as Matrix rooms and resolve room ↔ channel.

    Attributes:
        config: The crew configuration declaring ``channels`` and ``space``.
        appservice: The ``MatrixAppService`` used for all room I/O.
    """

    def __init__(self, config: MatrixCrewConfig, appservice: MatrixAppService) -> None:
        """Initialize the channel manager.

        Args:
            config: The crew configuration declaring ``channels`` and ``space``.
            appservice: The ``MatrixAppService`` used for all room I/O.
        """
        self._config = config
        self._as = appservice
        self._room_by_name: Dict[str, str] = {}
        self._channel_by_room: Dict[str, ChannelConfig] = {}
        self._space_id: Optional[str] = None
        self.logger = logging.getLogger("parrot.matrix.channels")

    async def ensure_channels(self) -> Dict[str, str]:
        """Ensure every declared channel exists as a Matrix room.

        For each ``ChannelConfig``: use ``room_id`` when set, else resolve
        the ``#<name>:<server_name>`` alias, else create a new room. Member
        agents are invited/joined, and ``m.parrot.channel`` state is
        published (or reconciled when the room already existed). When
        ``space.enabled`` is set, a Matrix Space is created/resolved first
        and every channel is linked to it as a child.

        Returns:
            Mapping of channel name to room id.
        """
        if self._config.space.enabled:
            await self.ensure_space()

        for ch in self._config.channels:
            room_id = ch.room_id or await self._as.resolve_alias(self.alias_for(ch.name))
            if room_id is None:
                public = ch.visibility == "public"
                room_id = await self._as.create_room_as_bot(
                    name=ch.name,
                    alias_localpart=ch.name,
                    topic=ch.topic,
                    preset="public_chat" if public else "private_chat",
                    visibility="public" if public else "private",
                    initial_state=[
                        {
                            "type": ParrotEventType.CHANNEL,
                            "state_key": "",
                            "content": self._state(ch).model_dump(),
                        }
                    ],
                )
            else:
                await self._reconcile_state(room_id, ch)

            for agent in ch.agents:
                await self._as.ensure_agent_in_room(agent, room_id)

            self._room_by_name[ch.name] = room_id
            self._channel_by_room[room_id] = ch

            if self._space_id:
                await self.link_to_space(room_id)

        return dict(self._room_by_name)

    def alias_for(self, name: str) -> str:
        """Build the full room alias for a channel name.

        Args:
            name: Channel name (alias localpart).

        Returns:
            The full room alias, e.g. ``#general:parrot.local``.
        """
        return f"#{name}:{self._config.server_name}"

    def channel_for_room(self, room_id: str) -> Optional[ChannelConfig]:
        """Look up a channel's declared configuration by its room id.

        Args:
            room_id: A Matrix room id.

        Returns:
            The matching ``ChannelConfig``, or ``None`` if unknown.
        """
        return self._channel_by_room.get(room_id)

    def room_for_channel(self, name: str) -> Optional[str]:
        """Look up a channel's room id by its declared name.

        Args:
            name: Channel name.

        Returns:
            The room id, or ``None`` if the channel hasn't been materialised.
        """
        return self._room_by_name.get(name)

    def is_member(self, agent_name: str, channel: str) -> bool:
        """Check whether an agent is a declared member of a channel.

        Args:
            agent_name: Agent name to check.
            channel: Channel name.

        Returns:
            ``True`` if the agent is a member of the channel.
        """
        ch = self._config.channel(channel)
        return bool(ch and agent_name in ch.agents)

    def list_channels(self) -> List[dict]:
        """List all declared channels with their resolved room ids.

        Returns:
            A list of dicts: ``{name, visibility, answer_policy, agents, room_id}``.
        """
        return [
            {
                "name": ch.name,
                "visibility": ch.visibility,
                "answer_policy": ch.answer_policy,
                "agents": list(ch.agents),
                "room_id": self._room_by_name.get(ch.name),
            }
            for ch in self._config.channels
        ]

    async def ensure_space(self) -> Optional[str]:
        """Create or resolve the Matrix Space room, when enabled.

        Returns:
            The Space room id, or ``None`` when ``space.enabled`` is ``False``.
        """
        if not self._config.space.enabled:
            return None
        if self._space_id:
            return self._space_id

        space = self._config.space
        if space.room_id:
            self._space_id = space.room_id
            return self._space_id

        room_id = await self._as.create_room_as_bot(
            name=space.name,
            preset="private_chat",
            visibility="private",
            creation_content={"type": "m.space"},
        )
        self._space_id = room_id
        return self._space_id

    async def link_to_space(self, room_id: str) -> None:
        """Link a channel/tunnel room to the Space as a child.

        Writes ``m.space.child`` on the Space room and ``m.space.parent``
        on the child room.

        Args:
            room_id: The child room id to link.
        """
        if not self._space_id:
            return
        via = [self._config.server_name]
        await self._as.set_room_state_as_bot(
            self._space_id, "m.space.child", {"via": via}, state_key=room_id
        )
        await self._as.set_room_state_as_bot(
            room_id, "m.space.parent", {"via": via}, state_key=self._space_id
        )

    def _state(self, ch: ChannelConfig) -> ChannelStateContent:
        """Build the ``m.parrot.channel`` state content for a channel.

        Args:
            ch: The channel configuration.

        Returns:
            The corresponding ``ChannelStateContent``.
        """
        return ChannelStateContent(
            name=ch.name,
            visibility=ch.visibility,
            answer_policy=ch.answer_policy,
            agents=list(ch.agents),
        )

    async def _reconcile_state(self, room_id: str, ch: ChannelConfig) -> None:
        """Ensure a pre-existing room's ``m.parrot.channel`` state matches config.

        Args:
            room_id: The pre-existing room id.
            ch: The desired channel configuration.
        """
        desired = self._state(ch).model_dump()
        existing = await self._as.get_room_state_as_bot(room_id, ParrotEventType.CHANNEL)
        if existing != desired:
            if existing is not None:
                self.logger.warning(
                    "Reconciling channel '%s' state in room %s: existing state differs",
                    ch.name,
                    room_id,
                )
            await self._as.set_room_state_as_bot(room_id, ParrotEventType.CHANNEL, desired)
