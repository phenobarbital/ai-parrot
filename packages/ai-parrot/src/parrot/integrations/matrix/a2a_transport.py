"""Matrix A2A Transport — agent-to-agent communication over Matrix.

Uses custom m.parrot.* events to implement A2A protocol semantics
on top of Matrix rooms, enabling federated agent communication
with persistent history.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional

from navconfig.logging import logging

from .client import MatrixClientWrapper
from .events import (
    AgentCardEventContent,
    ParrotEventType,
    ResultEventContent,
    StatusEventContent,
    TaskEventContent,
)


class MatrixA2ATransport:
    """A2A transport layer using Matrix as the message bus.

    Enables agent-to-agent communication by mapping A2A concepts
    onto Matrix rooms and custom events:

    - Agent discovery → m.parrot.agent_card state events
    - Task submission → m.parrot.task message events
    - Task results → m.parrot.result message events
    - Status updates → m.parrot.status message events

    Each agent can publish its card in a room and other agents
    discover it by reading room state. Federation comes for free
    from Matrix.
    """

    def __init__(
        self,
        wrapper: MatrixClientWrapper,
    ) -> None:
        self._wrapper = wrapper
        self._pending_results: Dict[str, asyncio.Future] = {}
        self._listening = False
        self.logger = logging.getLogger("parrot.matrix.a2a_transport")

    # ------------------------------------------------------------------
    # Agent Card (Discovery)
    # ------------------------------------------------------------------

    async def publish_card(
        self,
        room_id: str,
        card_data: Dict[str, Any],
        *,
        state_key: str = "",
    ) -> str:
        """Publish an agent's A2A card as room state.

        Args:
            room_id: Room to publish in.
            card_data: AgentCard.to_dict() output or AgentCardEventContent dict.
            state_key: State key (default: empty for the room's primary agent).

        Returns:
            Event ID of the state event.
        """
        # Validate via Pydantic if raw dict
        content = AgentCardEventContent(**card_data)
        event_id = await self._wrapper.set_room_state(
            room_id,
            ParrotEventType.AGENT_CARD,
            content.model_dump(),
            state_key=state_key,
        )
        self.logger.info(
            f"Published agent card '{content.name}' in {room_id}"
        )
        return event_id

    async def discover_card(
        self,
        room_id: str,
        state_key: str = "",
    ) -> Optional[AgentCardEventContent]:
        """Read an agent's card from room state.

        Args:
            room_id: Room to query.
            state_key: State key of the card.

        Returns:
            Parsed AgentCardEventContent or None if not found.
        """
        data = await self._wrapper.get_room_state_event(
            room_id,
            ParrotEventType.AGENT_CARD,
            state_key=state_key,
        )
        if data:
            return AgentCardEventContent(**data)
        return None

    # ------------------------------------------------------------------
    # Task Submission
    # ------------------------------------------------------------------

    async def send_task(
        self,
        room_id: str,
        content: str,
        *,
        task_id: Optional[str] = None,
        context_id: Optional[str] = None,
        target_agent: Optional[str] = None,
        skill_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send a task to an agent room via m.parrot.task.

        Args:
            room_id: Target room (the agent's "inbox").
            content: Task prompt text.
            task_id: Optional task ID (auto-generated if None).
            context_id: Optional context for multi-turn.
            target_agent: Routing hint for which agent should handle.
            skill_id: Specific skill to invoke.
            metadata: Additional metadata.

        Returns:
            The task_id.
        """
        tid = task_id or str(uuid.uuid4())
        cid = context_id or str(uuid.uuid4())

        task_content = TaskEventContent(
            task_id=tid,
            context_id=cid,
            content=content,
            target_agent=target_agent,
            skill_id=skill_id,
            metadata=metadata or {},
        )

        await self._wrapper.send_event(
            room_id,
            ParrotEventType.TASK,
            task_content.model_dump(),
        )
        self.logger.info(
            f"Sent task {tid} to {room_id}: '{content[:50]}...'"
        )
        return tid

    # ------------------------------------------------------------------
    # Result Handling
    # ------------------------------------------------------------------

    async def send_result(
        self,
        room_id: str,
        task_id: str,
        content: str,
        *,
        context_id: Optional[str] = None,
        artifacts: Optional[List[Dict[str, Any]]] = None,
        success: bool = True,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send a task result via m.parrot.result.

        Args:
            room_id: Room where the task was submitted.
            task_id: ID of the completed task.
            content: Result text.
            context_id: Context ID from the task.
            artifacts: Optional list of artifact dicts.
            success: Whether the task succeeded.
            error: Error message if failed.
            metadata: Additional metadata.

        Returns:
            Event ID of the result event.
        """
        result_content = ResultEventContent(
            task_id=task_id,
            context_id=context_id,
            content=content,
            artifacts=artifacts or [],
            success=success,
            error=error,
            metadata=metadata or {},
        )

        event_id = await self._wrapper.send_event(
            room_id,
            ParrotEventType.RESULT,
            result_content.model_dump(),
        )
        self.logger.info(
            f"Sent result for task {task_id} in {room_id} "
            f"(success={success})"
        )
        return event_id

    async def send_status(
        self,
        room_id: str,
        task_id: str,
        state: str,
        *,
        message: Optional[str] = None,
        progress: Optional[float] = None,
    ) -> str:
        """Send a status update via m.parrot.status.

        Args:
            room_id: Room containing the task.
            task_id: Task being updated.
            state: Status string (working, failed, input_required).
            message: Human-readable status message.
            progress: Optional progress value (0.0 - 1.0).

        Returns:
            Event ID of the status event.
        """
        status_content = StatusEventContent(
            task_id=task_id,
            state=state,
            message=message,
            progress=progress,
        )

        event_id = await self._wrapper.send_event(
            room_id,
            ParrotEventType.STATUS,
            status_content.model_dump(),
        )
        return event_id

    # ------------------------------------------------------------------
    # Wait for Result (blocking)
    # ------------------------------------------------------------------

    async def wait_for_result(
        self,
        room_id: str,
        task_id: str,
        *,
        timeout: float = 60.0,
    ) -> Optional[ResultEventContent]:
        """Wait for a m.parrot.result event matching the task_id.

        Args:
            room_id: Room to listen in.
            task_id: Task ID to wait for.
            timeout: Maximum time to wait in seconds.

        Returns:
            Parsed ResultEventContent or None on timeout.
        """
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_results[task_id] = future

        # Register listener if not already
        if not self._listening:
            self._wrapper.on_custom_event(
                ParrotEventType.RESULT,
                self._on_result_event,
            )
            self._listening = True

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self.logger.warning(
                f"Timeout waiting for result of task {task_id}"
            )
            return None
        finally:
            self._pending_results.pop(task_id, None)

    async def _on_result_event(self, event: Any) -> None:
        """Internal handler for incoming m.parrot.result events."""
        try:
            content = event.content
            if hasattr(content, "serialize"):
                data = content.serialize()
            elif isinstance(content, dict):
                data = content
            else:
                data = dict(content) if content else {}

            task_id = data.get("task_id")
            if task_id and task_id in self._pending_results:
                result = ResultEventContent(**data)
                future = self._pending_results[task_id]
                if not future.done():
                    future.set_result(result)
        except Exception as exc:
            self.logger.error(
                f"Error processing result event: {exc}",
                exc_info=True,
            )
