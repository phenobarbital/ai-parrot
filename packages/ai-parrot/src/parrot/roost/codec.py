"""Envelope codecs (FEAT-747 M9, resolved Q2). Sync, bytes-safe."""

from __future__ import annotations

import importlib
import json
import logging
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from parrot.core.events.lifecycle import TraceContext

from .messages import AgentAddress, FailureInfo, LocalEnvelope, RoostMessage

logger = logging.getLogger(__name__)


class UnencodableContent(ValueError):
    """Content is neither a Pydantic model, a JSON value nor a handle id — move it to a handle first."""


@runtime_checkable
class EnvelopeCodec(Protocol):
    """Synchronous codec for a Roost message and its envelope."""

    content_type: str

    def encode(self, msg: RoostMessage) -> bytes:
        """Encode *msg* as bytes."""
        ...

    def decode(self, data: bytes) -> RoostMessage:
        """Decode *data* into a Roost message."""
        ...


class JsonEnvelopeCodec:
    """Roost's fallback codec (dev, tests, satellite-less deployments)."""

    content_type = "application/json"

    def encode(self, msg: RoostMessage) -> bytes:
        """Encode a message and the structural envelope fields as JSON bytes.

        Raises:
            UnencodableContent: The message content is not JSON-compatible.
        """
        envelope = msg.envelope
        trace = getattr(envelope, "trace", None)
        encoded_content = self._encode_content(msg.content)
        encoded_permission_context = self._encode_permission_context(msg.permission_context)
        message_data = msg.model_dump(
            mode="json",
            exclude={"content", "envelope", "permission_context"},
        )
        message_data["content"] = encoded_content
        message_data["permission_context"] = encoded_permission_context
        payload = {
            "envelope": {
                "envelope_id": envelope.envelope_id,
                "correlation_id": envelope.correlation_id,
                "trace": (
                    {"trace_id": trace.trace_id, "span_id": trace.span_id}
                    if trace is not None
                    else None
                ),
                "budget_ms": envelope.budget_ms,
                "token_budget": envelope.token_budget,
                "caller": envelope.caller,
                "idempotency_key": envelope.idempotency_key,
            },
            "message": message_data,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def decode(self, data: bytes) -> RoostMessage:
        """Decode JSON bytes, rebuilding a local envelope and typed content when importable."""
        payload = json.loads(data)
        envelope_data = payload["envelope"]
        trace_data = envelope_data.get("trace")
        trace = TraceContext(**trace_data) if trace_data is not None else None
        envelope = LocalEnvelope(
            envelope_id=envelope_data["envelope_id"],
            correlation_id=envelope_data["correlation_id"],
            trace=trace,
            budget_ms=envelope_data.get("budget_ms"),
            token_budget=envelope_data.get("token_budget"),
            caller=envelope_data["caller"],
            idempotency_key=envelope_data.get("idempotency_key"),
        )

        message_data = payload["message"]
        content = self._decode_content(message_data.pop("content", None))
        sender = AgentAddress.model_validate(message_data.pop("sender"))
        receivers = [AgentAddress.model_validate(receiver) for receiver in message_data.pop("receivers", [])]
        failure_data = message_data.pop("failure", None)
        failure = FailureInfo.model_validate(failure_data) if failure_data is not None else None
        return RoostMessage(
            **message_data,
            sender=sender,
            receivers=receivers,
            content=content,
            envelope=envelope,
            failure=failure,
        )

    @staticmethod
    def _encode_content(content: Any) -> Any:
        """Return a JSON-compatible content value, tagging Pydantic models."""
        if isinstance(content, BaseModel):
            model_type = type(content)
            return {
                "model": f"{model_type.__module__}.{model_type.__qualname__}",
                "data": content.model_dump(mode="json"),
            }
        try:
            json.dumps(content)
        except (TypeError, ValueError) as exc:
            raise UnencodableContent(f"content of type {type(content).__name__} is not JSON-encodable") from exc
        return content

    @staticmethod
    def _encode_permission_context(permission_context: Any) -> Any:
        """Serialize an authority context without relying on object internals."""
        if permission_context is None:
            return None
        to_dict = getattr(permission_context, "to_dict", None)
        if callable(to_dict):
            return to_dict()
        logger.warning(
            "Permission context %s has no to_dict(); using a lossy string representation",
            type(permission_context).__name__,
        )
        return str(permission_context)

    @classmethod
    def _decode_content(cls, content: Any) -> Any:
        """Revalidate tagged Pydantic content when its class can be imported."""
        if not isinstance(content, dict) or set(content) != {"model", "data"}:
            return content
        model_class = cls._import_model(content["model"])
        if model_class is None:
            return content["data"]
        return model_class.model_validate(content["data"])

    @staticmethod
    def _import_model(dotted_name: str) -> type[BaseModel] | None:
        """Resolve an importable dotted Pydantic model name."""
        parts = dotted_name.split(".")
        for split_at in range(len(parts) - 1, 0, -1):
            try:
                value: Any = importlib.import_module(".".join(parts[:split_at]))
            except ImportError:
                continue
            try:
                for attribute in parts[split_at:]:
                    value = getattr(value, attribute)
            except AttributeError:
                return None
            return value if isinstance(value, type) and issubclass(value, BaseModel) else None
        return None
