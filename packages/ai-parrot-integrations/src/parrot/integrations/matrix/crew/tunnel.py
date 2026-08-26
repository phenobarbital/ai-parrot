"""Private agent-to-agent tunnels for the Matrix agent swarm (FEAT-463).

A *tunnel* is a lazily created, private 2-member Matrix room shared by an
unordered pair of agents, carrying ``m.parrot.task`` / ``m.parrot.result`` /
``m.parrot.feedback`` events. ``AgentTunnel.ask()`` sends a task and awaits
the matching result via a correlation-future — the same pattern used by
``MatrixA2ATransport.wait_for_result`` (``a2a_transport.py``), keyed by
``correlation_id`` instead of ``task_id``. Idle tunnels are tombstoned by a
periodic sweeper after ``ttl_minutes`` (``0`` = keep forever).
"""
import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..appservice import MatrixAppService
from ..events import (
    AgentAnswer,
    FeedbackEventContent,
    ParrotEventType,
    ResultEventContent,
    TaskEventContent,
    TunnelStateContent,
)
from .channels import ChannelManager
from .config import TunnelConfig

logger = logging.getLogger(__name__)


class AgentTunnel:
    """A private, lazily created 2-agent tunnel room.

    Attributes:
        last_used: Timestamp of the last successful ``ask()`` completion or
            tunnel creation; used by the TTL sweeper to detect idle tunnels.
    """

    def __init__(
        self,
        room_id: str,
        agents: Tuple[str, str],
        registry: "TunnelRegistry",
    ) -> None:
        """Initialize the tunnel.

        Args:
            room_id: The private room id backing this tunnel.
            agents: The unordered pair of agent names, sorted.
            registry: The owning ``TunnelRegistry``.
        """
        self._room_id = room_id
        self._agents = agents
        self._registry = registry
        self.last_used: datetime = datetime.now(timezone.utc)

    @property
    def room_id(self) -> str:
        """The private room id backing this tunnel."""
        return self._room_id

    @property
    def agents(self) -> Tuple[str, str]:
        """The unordered pair of agent names, sorted."""
        return self._agents

    async def ask(
        self,
        requester: str,
        target: str,
        question: str,
        *,
        expected_schema: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        hops: int = 0,
        origin_session: Optional[str] = None,
    ) -> AgentAnswer:
        """Ask ``target`` a question through this tunnel and await the answer.

        Args:
            requester: Name of the asking agent.
            target: Name of the target agent.
            question: The question text.
            expected_schema: Optional JSON Schema the answer must satisfy.
            timeout: Optional timeout override (seconds); defaults to
                ``TunnelConfig.default_timeout``.
            hops: Number of hops already taken before this call.
            origin_session: Optional originating collaborative session id.

        Returns:
            An ``AgentAnswer`` envelope. On failure, ``answer`` is ``None``
            and ``metadata["status"]`` is one of ``hop_limit``, ``timeout``,
            ``error``, or ``schema_error``; on success it is ``ok``.
        """
        cfg = self._registry.config
        if hops + 1 > cfg.max_hops:
            return AgentAnswer(answer=None, metadata={"status": "hop_limit", "hops": hops})

        task = TaskEventContent(
            task_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            content=question,
            target_agent=target,
            hops=hops + 1,
            origin_session=origin_session,
            expected_schema=expected_schema,
            metadata={"requester": requester},
        )
        fut = self._registry.register_future(task.correlation_id)
        try:
            await self._registry.appservice.send_custom_event_as_agent(
                requester, self.room_id, ParrotEventType.TASK, task.model_dump()
            )
        except Exception as exc:
            # Never leak the registered future when the send itself fails
            # (as opposed to the wait below timing out).
            self._registry.discard_future(task.correlation_id)
            return AgentAnswer(
                answer=None,
                metadata={
                    "status": "error",
                    "error": str(exc),
                    "correlation_id": task.correlation_id,
                },
            )
        try:
            result: ResultEventContent = await asyncio.wait_for(
                fut, timeout or cfg.default_timeout
            )
        except asyncio.TimeoutError:
            self._registry.discard_future(task.correlation_id)
            return AgentAnswer(
                answer=None,
                metadata={"status": "timeout", "correlation_id": task.correlation_id},
            )

        self.last_used = datetime.now(timezone.utc)

        if not result.success:
            return AgentAnswer(answer=None, metadata={"status": "error", "error": result.error})

        answer = AgentAnswer.from_text(result.content)
        try:
            answer.validate_against(expected_schema)
        except ValueError as exc:
            answer.metadata.update(status="schema_error", error=str(exc))
        else:
            answer.metadata.setdefault("status", "ok")
        answer.metadata.update(
            correlation_id=task.correlation_id,
            result_event_id=result.metadata.get("event_id"),
        )
        return answer

    async def send_feedback(
        self,
        requester: str,
        target: str,
        about_event_id: str,
        rating: int,
        comment: Optional[str] = None,
    ) -> str:
        """Send feedback about a prior tunnel exchange.

        Args:
            requester: Name of the agent sending feedback.
            target: Name of the agent the feedback is about.
            about_event_id: Event id the feedback refers to.
            rating: Rating in ``[-1, 5]``.
            comment: Optional free-text comment.

        Returns:
            The id of the feedback event that was sent.
        """
        content = FeedbackEventContent(
            correlation_id=str(uuid.uuid4()),
            about_event_id=about_event_id,
            from_agent=requester,
            to_agent=target,
            rating=rating,
            comment=comment,
        )
        event_id = await self._registry.appservice.send_custom_event_as_agent(
            requester, self.room_id, ParrotEventType.FEEDBACK, content.model_dump()
        )
        return event_id


class TunnelRegistry:
    """Registry of private agent-to-agent tunnels.

    Lazily creates and caches one tunnel room per unordered agent pair,
    routes inbound ``m.parrot.{task,result,feedback}`` custom events, and
    sweeps idle tunnels according to ``TunnelConfig.ttl_minutes``.
    """

    def __init__(
        self,
        config: TunnelConfig,
        appservice: MatrixAppService,
        channels: ChannelManager,
        wrappers: Dict[str, Any],
        server_name: str,
    ) -> None:
        """Initialize the tunnel registry.

        Args:
            config: Tunnel configuration (TTL, hop limit, timeout, ...).
            appservice: The ``MatrixAppService`` used for all room I/O.
            channels: The ``ChannelManager`` (used to link tunnels into the
                optional Space).
            wrappers: Mapping of agent name to ``MatrixCrewAgentWrapper``
                (typed ``Any`` to avoid a circular import; the wrapper's
                ``handle_task`` is added in TASK-2482).
            server_name: The homeserver's server name.
        """
        self._config = config
        self._as = appservice
        self._channels = channels
        self._wrappers = wrappers
        self._server_name = server_name
        self._tunnels: Dict[Tuple[str, str], AgentTunnel] = {}
        self._room_to_key: Dict[str, Tuple[str, str]] = {}
        self._locks: Dict[Tuple[str, str], asyncio.Lock] = {}
        self._futures: Dict[str, asyncio.Future] = {}
        self._feedback: Dict[str, List[FeedbackEventContent]] = {}
        self._sweeper_task: Optional[asyncio.Task] = None
        self.logger = logging.getLogger("parrot.matrix.tunnel")

    @property
    def config(self) -> TunnelConfig:
        """The tunnel configuration."""
        return self._config

    @property
    def appservice(self) -> MatrixAppService:
        """The ``MatrixAppService`` used for all room I/O."""
        return self._as

    async def get_or_create(self, agent_a: str, agent_b: str) -> AgentTunnel:
        """Get the existing tunnel for a pair of agents, or create it.

        The pair key is symmetric — ``("a", "b")`` and ``("b", "a")``
        resolve to the same tunnel.

        Args:
            agent_a: First agent name.
            agent_b: Second agent name.

        Returns:
            The (possibly newly created) ``AgentTunnel``.
        """
        key = tuple(sorted((agent_a, agent_b)))
        if key in self._tunnels:
            return self._tunnels[key]

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            if key in self._tunnels:
                return self._tunnels[key]

            agent_mxids = self._as.list_agents()
            invitees = [agent_mxids[a] for a in key if a in agent_mxids]

            state = TunnelStateContent(
                agents=list(key),
                created_at=datetime.now(timezone.utc),
                ttl_minutes=self._config.ttl_minutes,
            )
            room_id = await self._as.create_room_as_bot(
                name=f"tunnel:{key[0]}<->{key[1]}",
                is_direct=True,
                preset="trusted_private_chat",
                visibility="private",
                invitees=invitees,
                initial_state=[
                    {
                        "type": ParrotEventType.TUNNEL,
                        "state_key": "",
                        "content": state.model_dump(mode="json"),
                    }
                ],
            )
            for agent in key:
                await self._as.ensure_agent_in_room(agent, room_id)

            tunnel = AgentTunnel(room_id, key, self)
            self._tunnels[key] = tunnel
            self._room_to_key[room_id] = key

            if getattr(self._channels, "_space_id", None):
                await self._channels.link_to_space(room_id)

            return tunnel

    def register_future(self, correlation_id: str) -> asyncio.Future:
        """Register a pending result future for a correlation id.

        Args:
            correlation_id: The correlation id of the outstanding task.

        Returns:
            The newly created future, to be awaited by the caller.
        """
        fut = asyncio.get_running_loop().create_future()
        self._futures[correlation_id] = fut
        return fut

    def discard_future(self, correlation_id: str) -> None:
        """Drop a pending result future (e.g. after a timeout).

        Args:
            correlation_id: The correlation id of the future to discard.
        """
        self._futures.pop(correlation_id, None)

    def is_tunnel_room(self, room_id: str) -> bool:
        """Check whether a room id is a known tunnel room.

        Args:
            room_id: The Matrix room id.

        Returns:
            ``True`` if the room is a registered tunnel room.
        """
        return room_id in self._room_to_key

    def feedback_for(self, room_id: str) -> List[FeedbackEventContent]:
        """List feedback received in a tunnel room.

        Args:
            room_id: The tunnel room id.

        Returns:
            A list of ``FeedbackEventContent`` received in that room.
        """
        return list(self._feedback.get(room_id, []))

    def list_tunnels(self) -> List[dict]:
        """List all active tunnels (for the ``!tunnels`` coordinator command).

        Returns:
            A list of dicts: ``{agents, room_id, last_used}``.
        """
        return [
            {
                "agents": list(key),
                "room_id": tunnel.room_id,
                "last_used": tunnel.last_used.isoformat(),
            }
            for key, tunnel in self._tunnels.items()
        ]

    async def on_custom_event(
        self,
        event_type: str,
        content: dict,
        room_id: str,
        sender: str,
    ) -> None:
        """Route an inbound ``m.parrot.{task,result,feedback}`` event.

        Args:
            event_type: The Matrix event type string.
            content: The event content dict.
            room_id: The room the event was received in.
            sender: The MXID of the event sender.
        """
        if event_type == ParrotEventType.RESULT:
            try:
                result = ResultEventContent(**content)
            except Exception:
                self.logger.warning("Malformed m.parrot.result in %s: %s", room_id, content)
                return
            correlation_id = result.metadata.get("correlation_id") or result.task_id
            fut = self._futures.pop(correlation_id, None)
            if fut and not fut.done():
                fut.set_result(result)
            return

        if event_type == ParrotEventType.FEEDBACK:
            try:
                feedback = FeedbackEventContent(**content)
            except Exception:
                self.logger.warning("Malformed m.parrot.feedback in %s: %s", room_id, content)
                return
            self._feedback.setdefault(room_id, []).append(feedback)
            return

        if event_type == ParrotEventType.TASK:
            if not self.is_tunnel_room(room_id):
                return
            try:
                task = TaskEventContent(**content)
            except Exception:
                self.logger.warning("Malformed m.parrot.task in %s: %s", room_id, content)
                return
            wrapper = self._wrappers.get(task.target_agent) if task.target_agent else None
            handler = getattr(wrapper, "handle_task", None)
            if handler is None:
                self.logger.warning(
                    "No handle_task available for target agent '%s' in tunnel %s",
                    task.target_agent,
                    room_id,
                )
                return
            await handler(task, room_id)
            return

    async def start_sweeper(self) -> None:
        """Start the periodic idle-tunnel sweeper.

        No-op when ``TunnelConfig.ttl_minutes == 0`` (tunnels kept forever).
        """
        if self._config.ttl_minutes == 0:
            return

        interval = min(60.0, self._config.ttl_minutes * 60 / 4)

        async def _loop() -> None:
            while True:
                await asyncio.sleep(interval)
                try:
                    await self._sweep_once()
                except Exception:
                    self.logger.exception("Tunnel sweeper iteration failed")

        self._sweeper_task = asyncio.get_running_loop().create_task(_loop())

    async def stop(self) -> None:
        """Stop the periodic sweeper, if running."""
        if self._sweeper_task:
            self._sweeper_task.cancel()
            self._sweeper_task = None

    async def _sweep_once(self) -> int:
        """Tombstone tunnels idle for longer than ``ttl_minutes``.

        Returns:
            The number of tunnels swept (both agents left + tombstoned).
        """
        if self._config.ttl_minutes == 0:
            return 0

        now = datetime.now(timezone.utc)
        ttl = timedelta(minutes=self._config.ttl_minutes)
        expired = [key for key, t in self._tunnels.items() if (now - t.last_used) > ttl]

        count = 0
        for key in expired:
            tunnel = self._tunnels.get(key)
            if tunnel is None:
                continue
            try:
                for agent in key:
                    await self._as.leave_as_agent(agent, tunnel.room_id)
                await self._as.set_room_state_as_bot(
                    tunnel.room_id,
                    "m.room.tombstone",
                    {"body": "tunnel expired", "replacement_room": ""},
                )
                self._tunnels.pop(key, None)
                self._room_to_key.pop(tunnel.room_id, None)
                count += 1
            except Exception:
                self.logger.exception("Failed to sweep tunnel %s", key)
        return count
