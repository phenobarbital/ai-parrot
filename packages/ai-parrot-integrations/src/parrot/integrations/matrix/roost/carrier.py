"""Matrix carrier for Roost (FEAT-747 M12). One carrier among four; body is mandatory."""
from __future__ import annotations

import dataclasses
import logging
import uuid
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Sequence

from pydantic import BaseModel

from parrot.core.events.lifecycle import TraceContext
from parrot.roost.carriers.base import Carrier, CarrierClosed, Inbound
from parrot.roost.messages import AgentAddress, FailureInfo, LocalEnvelope, RoostMessage
from parrot.roost.performatives import CarrierKind, InteractionProtocol, Performative

from ..events import ParrotEventType, RoostEventContent

if TYPE_CHECKING:
    from ..client import MatrixClientWrapper

logger = logging.getLogger(__name__)

_MAX_EVENT_IDS = 1024
_SHORT_CONTENT = 120


def _is_json_value(value: Any) -> bool:
    """Return True when *value* is a plain JSON value (recursively)."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_json_value(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _is_json_value(v) for k, v in value.items())
    return False


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """Read *name* from a mapping or an attribute container."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


class MatrixCarrier(Carrier):
    """Roost carrier over ``m.parrot.roost`` room events.

    Args:
        client: Connected Matrix client wrapper.
        room_id: Room the carrier speaks in.
        agent_name: Name of the local agent (used for logging and self-echo suppression).
        render: Optional ``RoostMessage -> str`` producing the mandatory human-readable body.
    """

    kind = CarrierKind.MATRIX

    def __init__(
        self,
        client: "MatrixClientWrapper",
        *,
        room_id: str,
        agent_name: str,
        render: Optional[Callable[[RoostMessage], str]] = None,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self._client, self._room_id, self._agent_name = client, room_id, agent_name
        self._render = render or self._default_render
        # subscription_id -> (address, inbound, capabilities, active)
        self._subs: dict[str, tuple[AgentAddress, Inbound, tuple[str, ...], bool]] = {}
        self._event_ids: "OrderedDict[str, str]" = OrderedDict()  # message_id -> Matrix event_id (bounded)
        self._handler_registered = False
        self._closed = False

    def _remember_event(self, message_id: str, event_id: str) -> None:
        self._event_ids[message_id] = event_id
        self._event_ids.move_to_end(message_id)
        while len(self._event_ids) > _MAX_EVENT_IDS:
            self._event_ids.popitem(last=False)

    async def send(self, msg: RoostMessage) -> None:
        """Send *msg* as an ``m.parrot.roost`` event in the carrier's room.

        Raises:
            CarrierClosed: The carrier has been closed.
            ValueError: ``msg.content`` is neither JSON, a model nor a handle.
        """
        if self._closed:
            raise CarrierClosed("MatrixCarrier is closed")
        body = msg.body or self._render(msg)
        content = self.to_content(msg, body=body).model_dump(mode="json")
        if msg.in_reply_to and msg.in_reply_to in self._event_ids:
            content["m.relates_to"] = {"m.in_reply_to": {"event_id": self._event_ids[msg.in_reply_to]}}
        event_id = await self._client.send_event(self._room_id, ParrotEventType.ROOST, content)
        if isinstance(event_id, str):
            self._remember_event(msg.message_id, event_id)

    async def subscribe(self, address: AgentAddress, inbound: Inbound, *, capabilities: Sequence[str] = ()) -> str:
        """Register *inbound* for messages addressed to *address* or matching *capabilities*."""
        sub_id = uuid.uuid4().hex
        self._subs[sub_id] = (address, inbound, tuple(capabilities), True)
        if not self._handler_registered:
            self._client.on_custom_event(ParrotEventType.ROOST, self._on_event)
            self._handler_registered = True
        return sub_id

    async def unsubscribe(self, subscription_id: str) -> bool:
        """Deactivate a subscription (the client has no handler-removal API, so a flag is flipped)."""
        entry = self._subs.get(subscription_id)
        if entry is None or not entry[3]:
            return False
        self._subs[subscription_id] = (entry[0], entry[1], entry[2], False)
        return True

    async def close(self) -> None:
        """Drop every subscription; later events are ignored."""
        self._closed = True
        self._subs.clear()

    async def _on_event(self, event: Any) -> None:
        """Matrix callback: decode a ``m.parrot.roost`` event and fan out to matching subscribers."""
        if self._closed:
            return
        room_id = _get(event, "room_id")
        if room_id is not None and room_id != self._room_id:
            return
        raw = _get(event, "content")
        if raw is None:
            return
        if not isinstance(raw, dict):
            serialize = getattr(raw, "serialize", None)
            raw = serialize() if callable(serialize) else dict(raw)
        event_id = str(_get(event, "event_id", "") or "")
        try:
            msg = self.from_content(raw, event_id=event_id)
        except Exception:  # noqa: BLE001 - a malformed foreign event must not kill the sync loop
            self.logger.warning("Ignoring malformed m.parrot.roost event %s", event_id, exc_info=True)
            return
        if event_id:
            self._remember_event(msg.message_id, event_id)
        for sub_id, (address, inbound, caps, active) in list(self._subs.items()):
            if not active:
                continue
            addressed = msg.is_addressed_to(address.name)
            by_capability = bool(msg.capability_filter) and msg.capability_filter in caps
            if not (addressed or by_capability):
                continue
            try:
                await inbound(msg)
            except Exception:  # noqa: BLE001 - one failing subscriber never blocks the others
                self.logger.exception("Roost inbound handler for %s failed (sub %s)", address.name, sub_id)

    @staticmethod
    def _default_render(msg: RoostMessage) -> str:
        """Render ``[performative] sender → receivers: short content``."""
        targets = ", ".join(r.name for r in msg.receivers) or (msg.capability_filter or "")
        if isinstance(msg.content, BaseModel):
            text = msg.content.model_dump_json()
        else:
            text = str(msg.content) if msg.content is not None else ""
        if len(text) > _SHORT_CONTENT:
            text = text[: _SHORT_CONTENT - 1] + "…"
        return f"[{msg.performative.value}] {msg.sender.name} → {targets}: {text}"

    @staticmethod
    def _envelope_fields(envelope: Any) -> Dict[str, Any]:
        if envelope is None:
            return {}
        if isinstance(envelope, BaseModel):
            data = envelope.model_dump(mode="json")
        else:
            data = {}
            for name in ("envelope_id", "correlation_id", "budget_ms", "token_budget", "caller", "idempotency_key"):
                data[name] = getattr(envelope, name, None)
            trace = getattr(envelope, "trace", None)
            data["trace"] = dataclasses.asdict(trace) if dataclasses.is_dataclass(trace) else None
            return data
        trace = getattr(envelope, "trace", None)
        if dataclasses.is_dataclass(trace):
            data["trace"] = dataclasses.asdict(trace)
        return data

    @staticmethod
    def to_content(msg: RoostMessage, *, body: str) -> RoostEventContent:
        """Build the event content for *msg*.

        Raises:
            ValueError: ``msg.content`` is not a model, JSON value or handle.
        """
        raw = msg.content
        content: Any = None
        content_ref: Optional[str] = None
        if isinstance(raw, BaseModel):
            content = raw.model_dump(mode="json")
        elif _is_json_value(raw):
            content = raw
        else:
            handle = getattr(raw, "handle_id", None)
            if not isinstance(handle, str) or not handle:
                raise ValueError(f"content of type {type(raw).__name__} is neither JSON nor a handle")
            content_ref = handle
        return RoostEventContent(
            body=body,
            performative=msg.performative.value,
            protocol=msg.protocol.value,
            conversation_id=msg.conversation_id,
            message_id=msg.message_id,
            in_reply_to=msg.in_reply_to,
            sender=msg.sender.name,
            receivers=[r.name for r in msg.receivers],
            capability_filter=msg.capability_filter,
            content=content,
            content_ref=content_ref,
            envelope=MatrixCarrier._envelope_fields(msg.envelope),
            failure=msg.failure.model_dump(mode="json") if msg.failure else None,
        )

    @staticmethod
    def from_content(content: Dict[str, Any], *, event_id: str) -> RoostMessage:
        """Rebuild a :class:`RoostMessage` from event *content* (``event_id`` is logged for traceability)."""
        parsed = RoostEventContent.model_validate({k: v for k, v in content.items() if k != "m.relates_to"})
        in_reply_to = parsed.in_reply_to
        if in_reply_to is None:
            relates = content.get("m.relates_to") or {}
            if relates.get("m.in_reply_to", {}).get("event_id"):
                logger.debug("Event %s replies to Matrix event %s", event_id, relates["m.in_reply_to"]["event_id"])
        envelope: Optional[LocalEnvelope] = None
        if parsed.envelope:
            data = dict(parsed.envelope)
            trace = data.get("trace")
            data["trace"] = TraceContext(**trace) if isinstance(trace, dict) else None
            envelope = LocalEnvelope(**data)
        return RoostMessage(
            message_id=parsed.message_id,
            performative=Performative(parsed.performative),
            protocol=InteractionProtocol(parsed.protocol),
            conversation_id=parsed.conversation_id,
            in_reply_to=in_reply_to,
            sender=AgentAddress(name=parsed.sender, carrier=CarrierKind.MATRIX),
            receivers=[AgentAddress(name=n, carrier=CarrierKind.MATRIX) for n in parsed.receivers],
            capability_filter=parsed.capability_filter,
            content=parsed.content if parsed.content is not None else parsed.content_ref,
            body=parsed.body,
            envelope=envelope,
            failure=FailureInfo(**parsed.failure) if parsed.failure else None,
        )
