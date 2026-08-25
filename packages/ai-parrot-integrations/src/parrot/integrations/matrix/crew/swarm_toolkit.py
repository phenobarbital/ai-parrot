"""Agent-facing swarm toolkit for the Matrix agent swarm (FEAT-463).

``AgentSwarmToolkit`` is instantiated once per agent by
``MatrixCrewTransport`` and attached to that agent's bot ``ToolManager``.
Its public async methods become LLM-callable tools that let an agent ask
peer agents questions through private tunnels, send feedback, and
discover/post to swarm channels.
"""

import logging
from typing import Any, Dict, List, Optional

from parrot.tools import AbstractToolkit

from ..appservice import MatrixAppService
from . import context as ctx
from .channels import ChannelManager
from .registry import MatrixCrewRegistry
from .tunnel import TunnelRegistry

logger = logging.getLogger(__name__)


class AgentSwarmToolkit(AbstractToolkit):
    """Tools that let this agent talk to peer agents through private Matrix tunnels."""

    def __init__(
        self,
        agent_name: str,
        tunnels: TunnelRegistry,
        registry: MatrixCrewRegistry,
        channels: ChannelManager,
        appservice: MatrixAppService,
        **kwargs: Any,
    ) -> None:
        """Initialize the swarm toolkit for a single agent.

        Args:
            agent_name: Name of the agent this toolkit is attached to.
            tunnels: The shared ``TunnelRegistry``.
            registry: The shared ``MatrixCrewRegistry``.
            channels: The shared ``ChannelManager``.
            appservice: The shared ``MatrixAppService``.
            **kwargs: Forwarded to ``AbstractToolkit.__init__``.
        """
        self._agent_name = agent_name
        self._tunnels = tunnels
        self._registry = registry
        self._channels = channels
        self._as = appservice
        super().__init__(**kwargs)

    async def ask_agent(
        self,
        agent: str,
        question: str,
        expected_schema: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> dict:
        """Ask another agent of the swarm a question through a private tunnel.

        Waits for the peer's structured answer and returns
        ``{answer, confidence, sources, metadata}`` (``metadata.status`` is
        ``"ok"`` on success, or one of ``"timeout"``, ``"error"``,
        ``"schema_error"``, ``"hop_limit"``, ``"unknown_agent"``,
        ``"self_ask_rejected"``). Use ``list_agents`` to discover valid
        agent names first. Do not ask yourself.

        Args:
            agent: Name of the peer agent to ask.
            question: The question text.
            expected_schema: Optional JSON Schema the answer must satisfy.
            timeout: Optional timeout override in seconds.

        Returns:
            The ``AgentAnswer`` envelope as a plain dict, or a
            ``{"status": ...}`` error envelope.
        """
        if agent == self._agent_name:
            return {"status": "self_ask_rejected"}
        if await self._registry.get(agent) is None:
            return {
                "status": "unknown_agent",
                "available": [c.agent_name for c in await self._registry.all_agents()],
            }

        tunnel = await self._tunnels.get_or_create(self._agent_name, agent)
        await self._maybe_echo(agent)
        ans = await tunnel.ask(
            self._agent_name,
            agent,
            question,
            expected_schema=expected_schema,
            timeout=timeout,
            hops=ctx.current_hops.get(),
            origin_session=ctx.current_session.get(),
        )
        return ans.model_dump()

    async def send_feedback(
        self,
        agent: str,
        about_event_id: str,
        rating: int,
        comment: Optional[str] = None,
    ) -> str:
        """Send feedback about a prior answer from another agent.

        Use this after ``ask_agent`` to rate how useful the peer's answer
        was, through the same private tunnel.

        Args:
            agent: Name of the peer agent the feedback is about.
            about_event_id: Event id of the answer being rated.
            rating: Rating from -1 (unhelpful) to 5 (excellent).
            comment: Optional free-text comment.

        Returns:
            The id of the feedback event that was sent.
        """
        tunnel = await self._tunnels.get_or_create(self._agent_name, agent)
        return await tunnel.send_feedback(self._agent_name, agent, about_event_id, rating, comment)

    async def list_agents(self) -> List[dict]:
        """List all agents currently registered in this swarm.

        Use this to discover valid agent names and their current status
        before calling ``ask_agent`` or ``post_to_channel``.

        Returns:
            A list of dicts: ``{agent_name, display_name, status, skills}``.
        """
        cards = await self._registry.all_agents()
        return [
            {
                "agent_name": c.agent_name,
                "display_name": c.display_name,
                "status": c.status,
                "skills": list(c.skills),
            }
            for c in cards
        ]

    async def list_channels(self) -> List[dict]:
        """List the swarm channels visible to this agent.

        Includes all public channels plus any private channels this agent
        is a member of.

        Returns:
            A list of channel dicts as returned by ``ChannelManager.list_channels``.
        """
        channels = self._channels.list_channels()
        return [
            ch
            for ch in channels
            if ch.get("visibility") == "public" or self._channels.is_member(self._agent_name, ch.get("name"))
        ]

    async def post_to_channel(self, channel: str, text: str) -> str:
        """Post a message to a swarm channel as this agent.

        Only allowed when this agent is a declared member of the channel.

        Args:
            channel: Name of the target channel.
            text: Message text to post.

        Returns:
            The id of the sent event, or a ``"forbidden: ..."`` message
            when this agent is not a member of the channel.
        """
        if not self._channels.is_member(self._agent_name, channel):
            return f"forbidden: '{self._agent_name}' is not a member of channel '{channel}'"
        room_id = self._channels.room_for_channel(channel)
        if not room_id:
            return f"forbidden: channel '{channel}' has no known room"
        return await self._as.send_as_agent(self._agent_name, room_id, text)

    async def _maybe_echo(self, target: str) -> None:
        """Post a one-line echo of a tunnel question in the originating channel.

        No-op when ``TunnelConfig.echo_summary_to_channel`` is disabled, or
        when there is no known originating channel/trigger event in the
        current swarm request context.

        Args:
            target: Name of the agent being asked.
        """
        if not self._tunnels.config.echo_summary_to_channel:
            return
        room_id = ctx.current_channel_room.get()
        trigger_event = ctx.current_trigger_event.get()
        if not room_id or not trigger_event:
            return
        message = f"🔒 *{self._agent_name}* asked *{target}* a question"
        await self._as.send_reply_as_agent(self._agent_name, room_id, message, trigger_event)
