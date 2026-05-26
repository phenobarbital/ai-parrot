"""Hybrid tool delegation for Matrix collaborative crew sessions.

``HybridDelegator`` bridges the collaborative session layer with the
Matrix custom event layer (``m.parrot.task`` / ``m.parrot.result``),
enabling an agent to request tool execution from a peer agent that has
privileged access.

Flow:
1. Post a visible "Asking @peer to: ..." message in the room.
2. Send a ``m.parrot.task`` custom event via the AppService.
3. Wait for the matching ``m.parrot.result`` custom event (with timeout).
4. Post the result as a visible reply-to the original request message.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Dict, Optional

from pydantic import BaseModel, Field

from ..events import ParrotEventType, ResultEventContent, TaskEventContent
from .mention import build_pill

if TYPE_CHECKING:
    from ..appservice import MatrixAppService
    from .registry import MatrixCrewRegistry


class DelegationRequest(BaseModel):
    """Represents a request to delegate a task to another agent.

    Args:
        requester_name: Agent name of the delegating agent.
        target_agent: Agent name of the peer who will execute the task.
        task_description: Human-readable description of the delegated task.
        room_id: Matrix room where the delegation happens.
        context: Optional shared context or reference for the task.
    """

    requester_name: str = Field(..., description="Agent name of the delegating agent")
    target_agent: str = Field(..., description="Agent name of the peer agent")
    task_description: str = Field(..., description="Description of the delegated task")
    room_id: str = Field(..., description="Matrix room ID for the delegation")
    context: Optional[str] = Field(default=None, description="Optional shared context")


class HybridDelegator:
    """Orchestrates hybrid tool delegation in a Matrix room.

    Combines visible Matrix messages (for human readability) with custom
    ``m.parrot.task`` / ``m.parrot.result`` events (for agent-to-agent
    communication).

    Args:
        appservice: The shared ``MatrixAppService`` instance.
        registry: ``MatrixCrewRegistry`` for resolving agent cards.
    """

    def __init__(
        self,
        appservice: "MatrixAppService",
        registry: "MatrixCrewRegistry",
    ) -> None:
        self._appservice = appservice
        self._registry = registry
        self._pending: Dict[str, asyncio.Future] = {}
        self.logger = logging.getLogger(__name__)

    async def delegate(
        self,
        request: DelegationRequest,
        timeout: float = 60.0,
    ) -> Optional[str]:
        """Execute a hybrid delegation request.

        Steps:
        1. Resolve the target agent's card from the registry.
        2. Post a visible "Asking @target to: ..." message as the requester.
        3. Send a ``m.parrot.task`` custom event with the task description.
        4. Wait for the matching ``m.parrot.result`` event (with timeout).
        5. Post the result text as a reply-to the visible request message.

        Args:
            request: Delegation request details.
            timeout: Maximum seconds to wait for the result.

        Returns:
            Result text string if received, ``None`` on timeout.
        """
        # 1. Resolve target agent card for pill formatting
        target_card = await self._registry.get(request.target_agent)
        if target_card:
            pill = build_pill(target_card.mxid, target_card.display_name)
        else:
            pill = f"@{request.target_agent}"

        # 2. Post visible message as the requester
        visible_msg = f"Asking {pill} to: {request.task_description}"
        visible_event_id = await self._appservice.send_as_agent(
            request.requester_name,
            request.room_id,
            visible_msg,
        )

        # 3. Send m.parrot.task custom event
        task_id = str(uuid.uuid4())
        task_content = TaskEventContent(
            task_id=task_id,
            content=request.task_description,
            target_agent=request.target_agent,
            context_id=request.context,
        )

        await self._send_custom_event(
            requester_name=request.requester_name,
            room_id=request.room_id,
            event_type=ParrotEventType.TASK,
            content=task_content.model_dump(),
        )

        # 4. Wait for m.parrot.result with timeout
        result = await self._wait_for_result(task_id, timeout)

        # 5. Post result as reply-to the visible request message
        if result is not None:
            await self._appservice.send_reply_as_agent(
                request.target_agent,
                request.room_id,
                result.content,
                visible_event_id,
            )
            return result.content

        self.logger.warning(
            "Delegation timed out waiting for result of task %s", task_id
        )
        return None

    async def on_custom_event(self, event_type: str, content: dict) -> None:
        """Handle an incoming custom event from the AppService.

        Should be connected to ``MatrixAppService`` via
        ``set_custom_event_callback()``. Resolves pending futures when a
        ``m.parrot.result`` event matching a known task_id is received.

        Args:
            event_type: The raw event type string.
            content: The event content dict.
        """
        if event_type == ParrotEventType.RESULT:
            try:
                result = ResultEventContent(**content)
            except Exception as exc:
                self.logger.warning(
                    "Could not parse ResultEventContent: %s", exc
                )
                return

            future = self._pending.get(result.task_id)
            if future and not future.done():
                future.set_result(result)
                self.logger.debug(
                    "Resolved delegation future for task %s", result.task_id
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _send_custom_event(
        self,
        requester_name: str,
        room_id: str,
        event_type: str,
        content: dict,
    ) -> None:
        """Send a custom Matrix event via the AppService as the requester.

        Looks up the requester agent's MXID, obtains the matching intent,
        and sends the custom event to the room.

        Args:
            requester_name: Agent name performing the delegation.
            room_id: Target Matrix room.
            event_type: Custom event type string (e.g. ``m.parrot.task``).
            content: Event content dict.
        """
        try:
            from mautrix.types import EventType as MxEventType, RoomID  # type: ignore

            # Get the requester's MXID from the registered agents map
            mxid = self._appservice._registered_agents.get(requester_name)
            if not mxid:
                self.logger.warning(
                    "Requester '%s' not found in registered agents — skipping custom event",
                    requester_name,
                )
                return

            intent = self._appservice._get_intent(mxid)
            custom_type = MxEventType.find(
                event_type, t_class=MxEventType.Class.MESSAGE
            )
            await intent.send_message_event(
                RoomID(room_id), custom_type, content
            )
        except Exception as exc:
            self.logger.error(
                "Failed to send custom event %s: %s", event_type, exc
            )

    async def _wait_for_result(
        self,
        task_id: str,
        timeout: float,
    ) -> Optional[ResultEventContent]:
        """Wait for a m.parrot.result event matching task_id.

        Args:
            task_id: Task identifier to match.
            timeout: Maximum wait time in seconds.

        Returns:
            Parsed ``ResultEventContent`` if received, ``None`` on timeout.
        """
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[task_id] = future

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self.logger.warning(
                "Timeout waiting for result of task %s", task_id
            )
            return None
        finally:
            self._pending.pop(task_id, None)
