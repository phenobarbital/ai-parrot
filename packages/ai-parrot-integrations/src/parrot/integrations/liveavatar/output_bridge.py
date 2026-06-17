"""Structured-output → AgentChat UI bridge for LiveAvatar Phase C (FEAT-243).

During a voice turn the ai-parrot response bifurcates: plain text is spoken by
the avatar (see ``livekit_agent.agent.LiveAvatarAgent``), while structured
outputs (charts, data, canvas updates, tool calls) are pushed to the **existing**
AgentChat UI WebSocket channel keyed by ``session_id`` — the same conversation
the avatar is speaking (spec section 3, Module 3; Open Question P4).

The bridge calls ``UserSocketManager.broadcast_to_channel`` (verified at
``packages/ai-parrot-server/src/parrot/handlers/user.py:357``). The socket
manager is dependency-injected (duck-typed) so this module stays free of a hard
import on the ai-parrot-server package and is trivially unit-testable.
"""

import logging
from typing import Any

from parrot.integrations.liveavatar.livekit_agent.models import (
    StructuredOutputMessage,
)

__all__ = ["OutputBridge"]


class OutputBridge:
    """Publishes structured ai-parrot outputs to the AgentChat UI WS channel.

    Args:
        socket_manager: A ``UserSocketManager``-like object exposing
            ``async def broadcast_to_channel(channel, message, exclude_ws=None)``.
            Injected rather than imported to keep ``ai-parrot-integrations``
            decoupled from the server package and to allow fakes in tests.
    """

    def __init__(self, socket_manager: Any) -> None:
        self._sockets = socket_manager
        self.logger = logging.getLogger(__name__)

    async def publish(self, msg: StructuredOutputMessage) -> None:
        """Publish a structured output to the channel keyed by ``session_id``.

        Args:
            msg: The structured output to deliver to the AgentChat UI. It is
                broadcast on the channel named after ``msg.session_id`` so the
                avatar speech and the UI render share one conversation.
        """
        await self._sockets.broadcast_to_channel(
            channel=msg.session_id,
            message=msg.model_dump(),
        )
        self.logger.debug(
            "Published structured output type=%s to channel=%s (turn_id=%s)",
            msg.type,
            msg.session_id,
            msg.turn_id,
        )
