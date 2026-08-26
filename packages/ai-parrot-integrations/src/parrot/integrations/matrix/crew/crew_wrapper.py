"""Per-agent message handler for the Matrix multi-agent crew.

Each ``MatrixCrewAgentWrapper`` handles messages directed at a specific agent:
typing indicators, BotManager resolution, response sending (with optional
streaming / chunking), and coordinator status notifications.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import List, Optional, TYPE_CHECKING

from ..events import ParrotEventType, ResultEventContent, TaskEventContent
from . import context as ctx

if TYPE_CHECKING:
    from ..appservice import MatrixAppService
    from .config import MatrixCrewAgentEntry
    from .coordinator import MatrixCoordinator
    from .registry import MatrixCrewRegistry


class MatrixCrewAgentWrapper:
    """Per-agent handler for incoming Matrix crew messages.

    Processes messages directed at a specific agent:
    1. Updates registry status to ``busy``.
    2. Sends a typing indicator (background task, cancelled on completion).
    3. Resolves the agent via ``BotManager.get_bot(chatbot_id)``.
    4. Calls ``agent.ask(body)`` to get a response.
    5. Sends the response as the agent's virtual MXID.
    6. Updates registry status back to ``ready``.

    Args:
        agent_name: Internal agent name (key in the crew config).
        config: ``MatrixCrewAgentEntry`` for this agent.
        appservice: Shared ``MatrixAppService`` managing virtual users.
        registry: Shared ``MatrixCrewRegistry``.
        coordinator: Shared ``MatrixCoordinator`` for status-board updates.
        server_name: Matrix server domain (e.g. ``"example.com"``).
        streaming: Whether to use edit-based streaming.
        max_message_length: Chunk responses longer than this.
    """

    def __init__(
        self,
        agent_name: str,
        config: "MatrixCrewAgentEntry",
        appservice: "MatrixAppService",
        registry: "MatrixCrewRegistry",
        coordinator: "MatrixCoordinator",
        server_name: str,
        streaming: bool = True,
        max_message_length: int = 4096,
    ) -> None:
        self._agent_name = agent_name
        self._config = config
        self._appservice = appservice
        self._registry = registry
        self._coordinator = coordinator
        self._server_name = server_name
        self._streaming = streaming
        self._max_message_length = max_message_length
        self._mxid = f"@{config.mxid_localpart}:{server_name}"
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def handle_message(
        self,
        room_id: str,
        sender: str,
        body: str,
        event_id: str,
    ) -> None:
        """Process an incoming message directed at this agent.

        Args:
            room_id: Matrix room ID where the message was sent.
            sender: Full MXID of the message sender.
            body: Plain-text message body.
            event_id: Matrix event ID of the incoming message.
        """
        self.logger.info(
            "Agent '%s' handling message in %s from %s",
            self._agent_name,
            room_id,
            sender,
        )

        # 1 — update status → busy
        task_preview = body[:50]
        await self._registry.update_status(
            self._agent_name, "busy", task_preview
        )

        # 2 — notify coordinator
        await self._coordinator.on_status_change(self._agent_name)

        # 3 — start typing indicator in background
        typing_task: Optional[asyncio.Task] = None
        if hasattr(self._appservice, "_get_intent"):
            typing_task = asyncio.create_task(
                self._send_typing(room_id),
                name=f"typing_{self._agent_name}",
            )

        # Swarm request context (FEAT-463): a human-triggered message starts
        # a fresh hop chain, and carries the originating room/event so
        # AgentSwarmToolkit.ask_agent can post its optional echo line.
        hops_token = ctx.current_hops.set(0)
        session_token = ctx.current_session.set(None)
        room_token = ctx.current_channel_room.set(room_id)
        trigger_token = ctx.current_trigger_event.set(event_id)

        try:
            # 4 — resolve agent from BotManager
            from parrot.manager import BotManager  # type: ignore

            agent = await BotManager.get_bot(self._config.chatbot_id)
            if agent is None:
                raise RuntimeError(
                    f"Agent '{self._config.chatbot_id}' not found in BotManager"
                )

            # 5 — get response
            response: str = await agent.ask(body)

            # 6 — send response as virtual MXID
            await self._send_response(room_id, response)

        except Exception as exc:
            self.logger.error(
                "Error handling message for agent '%s': %s",
                self._agent_name,
                exc,
                exc_info=True,
            )
            # Send error notice to room
            try:
                await self._appservice.send_as_agent(
                    self._agent_name,
                    room_id,
                    f"[Error] I encountered an issue: {exc}",
                )
            except Exception:
                pass
        finally:
            # 7 — cancel typing task
            if typing_task and not typing_task.done():
                typing_task.cancel()
                try:
                    await typing_task
                except asyncio.CancelledError:
                    pass

            # 8 — update status → ready
            await self._registry.update_status(self._agent_name, "ready")

            # 9 — notify coordinator
            await self._coordinator.on_status_change(self._agent_name)

            # 10 — reset swarm request context
            ctx.current_hops.reset(hops_token)
            ctx.current_session.reset(session_token)
            ctx.current_channel_room.reset(room_token)
            ctx.current_trigger_event.reset(trigger_token)

    async def handle_task(self, task: TaskEventContent, room_id: str) -> None:
        """Answer an inbound ``m.parrot.task`` and emit ``m.parrot.result``.

        Runs this agent with a structured-output prompt built from the
        task content (and ``expected_schema`` when present), then replies
        as this agent with an ``m.parrot.result`` event carrying the same
        ``correlation_id`` (falling back to ``task_id`` for legacy
        callers, e.g. ``HybridDelegator``). Never raises — any failure or
        timeout is reported as a ``success=False`` result.

        Args:
            task: The inbound task content.
            room_id: The (tunnel) room to reply in.
        """
        corr = task.correlation_id or task.task_id
        meta = {
            "correlation_id": corr,
            "origin_session": task.origin_session,
            "hops": task.hops,
        }
        timeout = float(task.metadata.get("timeout", 120.0))

        # Swarm request context (FEAT-463): propagate the hop count and
        # originating session so a peer's own `ask_agent` tool calls (a
        # potential A→B→A chain) are rejected once `max_hops` is reached.
        hops_token = ctx.current_hops.set(task.hops)
        session_token = ctx.current_session.set(task.origin_session)

        await self._registry.update_status(self._agent_name, "busy", task.content[:50])
        try:
            from parrot.manager import BotManager  # type: ignore

            agent = await BotManager.get_bot(self._config.chatbot_id)
            if agent is None:
                raise RuntimeError(
                    f"Agent '{self._config.chatbot_id}' not found in BotManager"
                )
            response_obj = await asyncio.wait_for(
                agent.ask(self._build_task_prompt(task)), timeout
            )
            # AbstractBot.ask() returns an AIMessage, not a str — extract
            # the text the same way session.py's _call_agent_with_timeout /
            # _synthesize_phase do.
            if hasattr(response_obj, "to_text"):
                text = response_obj.to_text
            elif hasattr(response_obj, "content"):
                text = str(response_obj.content)
            else:
                text = str(response_obj)
            result = ResultEventContent(
                task_id=task.task_id, content=text, success=True, metadata=meta
            )
        except Exception as exc:  # noqa: BLE001 — never propagate into the AppService loop
            self.logger.error(
                "handle_task failed for %s: %s", self._agent_name, exc
            )
            result = ResultEventContent(
                task_id=task.task_id,
                content="",
                success=False,
                error=str(exc),
                metadata=meta,
            )
        finally:
            await self._registry.update_status(self._agent_name, "ready")
            ctx.current_hops.reset(hops_token)
            ctx.current_session.reset(session_token)

        await self._appservice.send_custom_event_as_agent(
            self._agent_name, room_id, ParrotEventType.RESULT, result.model_dump()
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    _JSON_INSTRUCTION = (
        'Reply ONLY with a JSON object: '
        '{"answer": <your answer>, "confidence": <0..1>, "sources": [<strings>]}.'
    )

    def _build_task_prompt(self, task: TaskEventContent) -> str:
        """Build the structured-output prompt for an inbound tunnel task.

        Args:
            task: The inbound task content.

        Returns:
            A prompt instructing the agent to reply with a JSON object,
            optionally constrained by ``task.expected_schema``.
        """
        requester = task.metadata.get("requester", "another agent")
        parts = [
            f"A peer agent ({requester}) asks you: {task.content}",
            self._JSON_INSTRUCTION,
        ]
        if task.expected_schema:
            parts.append(
                'The value of "answer" MUST conform to this JSON Schema:\n'
                + json.dumps(task.expected_schema)
            )
        return "\n\n".join(parts)

    async def _send_response(self, room_id: str, response: str) -> None:
        """Send the agent response, chunking if necessary.

        If ``streaming`` is enabled and the appservice supports intent-based
        streaming, uses edit-based streaming.  Otherwise, chunks long
        responses and sends sequentially.

        Args:
            room_id: Target Matrix room.
            response: Full response text to send.
        """
        if self._streaming:
            # Attempt streaming via agent's virtual MXID intent
            try:
                intent = self._appservice._get_intent(self._mxid)
                # Send initial placeholder then edit with full response
                from mautrix.types import RoomID  # type: ignore
                event_id = await intent.send_text(RoomID(room_id), "...")
                await intent.send_message_event(
                    RoomID(room_id),
                    "m.room.message",
                    {
                        "msgtype": "m.text",
                        "body": f"* {response}",
                        "m.new_content": {"msgtype": "m.text", "body": response},
                        "m.relates_to": {
                            "rel_type": "m.replace",
                            "event_id": str(event_id),
                        },
                    },
                )
                return
            except Exception as exc:
                self.logger.debug(
                    "Streaming failed, falling back to chunked send: %s", exc
                )

        # Non-streaming: chunk and send
        chunks = self._chunk_text(response, self._max_message_length)
        for chunk in chunks:
            await self._appservice.send_as_agent(
                self._agent_name, room_id, chunk
            )

    async def _send_typing(self, room_id: str) -> None:
        """Background coroutine that sends typing indicators every 10 s.

        Sends ``m.typing`` via the agent's virtual MXID intent with a 15-second
        timeout, then waits 10 seconds before repeating.  On cancellation,
        sends a final indicator to clear the typing state.

        Args:
            room_id: Matrix room ID to send typing indicator in.
        """
        try:
            intent = self._appservice._get_intent(self._mxid)
            from mautrix.types import RoomID  # type: ignore
            while True:
                try:
                    await intent.set_typing(RoomID(room_id), timeout=15000)
                except Exception:
                    pass
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            try:
                intent = self._appservice._get_intent(self._mxid)
                from mautrix.types import RoomID  # type: ignore
                await intent.set_typing(RoomID(room_id), typing=False)
            except Exception:
                pass

    @staticmethod
    def _chunk_text(text: str, max_length: int) -> List[str]:
        """Split text into chunks at paragraph or sentence boundaries.

        Prefers splitting on double-newline (paragraph boundary), then
        single-newline, then by character count.

        Args:
            text: The full response text to split.
            max_length: Maximum characters per chunk.

        Returns:
            List of text chunks, each at most ``max_length`` characters.
        """
        if len(text) <= max_length:
            return [text]

        chunks: List[str] = []
        remaining = text

        while len(remaining) > max_length:
            # Try paragraph break
            split_at = remaining.rfind("\n\n", 0, max_length)
            if split_at == -1:
                # Try line break
                split_at = remaining.rfind("\n", 0, max_length)
            if split_at == -1:
                # Try sentence boundary
                split_at = remaining.rfind(". ", 0, max_length)
                if split_at != -1:
                    split_at += 1  # include the period
            if split_at <= 0:
                # Hard split
                split_at = max_length

            chunks.append(remaining[:split_at].strip())
            remaining = remaining[split_at:].strip()

        if remaining:
            chunks.append(remaining)

        return chunks
