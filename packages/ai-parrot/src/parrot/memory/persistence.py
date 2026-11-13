"""Turn persistence vocabulary: topics, presentation model, publisher (FEAT-886).

The bot hands the RAW turn plus a :class:`TurnPresentation` to an optional
:class:`TurnPublisher`; ChatStorage subscribes on the other side of the bus.
This module holds no bus lifecycle — see ``parrot.storage.turn_bus``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover - typing only; keeps parrot.memory import-cycle free
    from parrot.core.events.lifecycle.events.memory import TurnCompletedEvent
    from parrot.models.responses import AIMessage

TURN_COMPLETED_TOPIC: str = "conversation.turn.completed"
CONVERSATION_DELETED_TOPIC: str = "conversation.deleted"


class TurnPresentation(BaseModel):
    """Presentation and usage fields the bot derives from the round's ``AIMessage``."""

    output: Any = None
    output_mode: Optional[str] = None
    data: Any = None
    code: Optional[str] = None
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    response_time_ms: Optional[int] = None
    tenant: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    cost_usd: Optional[float] = None

    @classmethod
    def from_ai_message(
        cls,
        response: "AIMessage",
        *,
        output_mode: Optional[str],
        response_time_ms: Optional[int],
        tenant: Optional[str],
    ) -> "TurnPresentation":
        """Build from a round's ``AIMessage``. Never raises on a missing attribute; absent → ``None``.

        Args:
            response: The round's final ``AIMessage``.
            output_mode: The resolved output mode (string value), if any.
            response_time_ms: The bot's own elapsed time for the round.
            tenant: The bound request tenant (``current_tenant.get()``).

        Returns:
            A populated presentation; every field the message lacks is ``None`` / ``[]``.
        """
        text = getattr(response, "response", None)
        raw_output = getattr(response, "output", None)
        output = text or (str(raw_output) if raw_output is not None else None)
        code = getattr(response, "code", None)
        sources: List[Dict[str, Any]] = []
        for doc in getattr(response, "source_documents", None) or []:
            if isinstance(doc, dict):
                sources.append(doc)
            elif hasattr(doc, "to_dict"):
                sources.append(doc.to_dict())
        usage_obj = getattr(response, "usage", None)
        usage: Optional[Dict[str, Any]] = None
        cost: Optional[float] = None
        if usage_obj is not None:
            usage = usage_obj.model_dump() if hasattr(usage_obj, "model_dump") else None
            cost = getattr(usage_obj, "estimated_cost", None)
        return cls(
            output=output,
            output_mode=output_mode,
            data=getattr(response, "data", None),
            code=str(code) if code else None,
            sources=sources,
            response_time_ms=response_time_ms,
            tenant=tenant,
            model=getattr(response, "model", None),
            provider=getattr(response, "provider", None),
            usage=usage,
            cost_usd=cost,
        )


@runtime_checkable
class TurnPublisher(Protocol):
    """Hands one completed turn to the turn bus."""

    async def publish(self, event: "TurnCompletedEvent") -> None:
        """Hand the event to the bus. Raises only when the outbox rejects the write."""
        ...


class BusTurnPublisher:
    """``TurnPublisher`` over a ``navigator_eventbus.EventBus``."""

    def __init__(self, bus: Any) -> None:
        """Wrap ``bus`` (an ``EventBus``; duck-typed on ``emit``)."""
        self._bus = bus

    async def publish(self, event: "TurnCompletedEvent") -> None:
        """Emit one envelope on :data:`TURN_COMPLETED_TOPIC` with ``event_id == turn_id``.

        Args:
            event: The completed-turn event; ``event.turn["turn_id"]`` becomes the envelope id.

        Raises:
            KeyError: If the turn dict carries no ``turn_id``.
            Exception: Whatever the bus raises when the outbox rejects the write — never swallowed.
        """
        await self._bus.emit(
            TURN_COMPLETED_TOPIC,
            event.to_dict(),
            event_id=event.turn["turn_id"],
            source=event.agent_name or None,
        )
