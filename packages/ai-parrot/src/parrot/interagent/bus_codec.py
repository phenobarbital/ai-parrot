"""Bytes-safe mapping of Squawk messages onto a JSON EventEnvelope.payload (Squawk-owned convention, spec §8 Q2)."""

from __future__ import annotations

import base64
from datetime import date, datetime
from enum import Enum
from typing import Any

from parrot.interagent.errors import SquawkError, SquawkErrorCode
from parrot.interagent.messages import (
    CallMessage,
    CancelMessage,
    ProgressMessage,
    ResultMessage,
)

BusMessage = CallMessage | ResultMessage | ProgressMessage | CancelMessage

_KINDS: dict[str, type] = {
    "CallMessage": CallMessage,
    "ResultMessage": ResultMessage,
    "ProgressMessage": ProgressMessage,
    "CancelMessage": CancelMessage,
}

_BYTES_FIELDS = ("args", "inline", "frame", "token")

VERSION = 1

# Bound on one decoded bytes field (64 MiB of payload): a bus message is a control-plane
# envelope; bulk artifacts travel as handles/frames, never inline on the bus.
MAX_BYTES_FIELD = 64 * 1024 * 1024
_MAX_B64_CHARS = 4 * ((MAX_BYTES_FIELD + 2) // 3)


def _jsonify_value(value: Any) -> Any:
    """Recursively convert datetime, date, and Enum to JSON-safe primitives."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _jsonify_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify_value(item) for item in value]
    return value


class BusPayloadSerializer:
    """{'kind', 'v', 'data'} with every bytes field as {'__b64__': ...}. No pycapnp; FEAT-747 M9 imports exactly this."""

    def to_payload(self, message: BusMessage) -> dict[str, Any]:
        """Serialize a bus message to a JSON-safe payload dict.

        Args:
            message: The bus message to serialize.

        Returns:
            A dict with 'kind', 'v', and 'data' keys. All bytes fields are
            encoded as {'__b64__': '<base64>'}.
        """
        raw = message.model_dump(mode="python")
        # Encode bytes fields as base64
        for f in _BYTES_FIELDS:
            if isinstance(raw.get(f), (bytes, bytearray)):
                raw[f] = {"__b64__": base64.b64encode(raw[f]).decode("ascii")}
        # Convert datetime/Enum to JSON-safe primitives
        raw = _jsonify_value(raw)
        return {"kind": type(message).__name__, "v": VERSION, "data": raw}

    def from_payload(self, payload: dict[str, Any]) -> BusMessage:
        """Deserialize an untrusted JSON payload to a bus message.

        Any ``caller`` in the payload is discarded: the server sets it from the
        handshake / envelope metadata, so a peer cannot assert another identity.
        Every malformed input — wrong shape, bad base64, oversized bytes field,
        unknown kind/version or failed validation — raises the same error.

        Args:
            payload: A dict with 'kind', 'v', and 'data' keys.

        Returns:
            The deserialized bus message.

        Raises:
            SquawkError: ``UPSTREAM_FAILED`` / ``malformed`` for any malformed payload.
        """
        try:
            if not isinstance(payload, dict):
                raise TypeError("payload must be an object")
            cls = _KINDS.get(str(payload.get("kind")))
            if cls is None or payload.get("v") != VERSION:
                raise ValueError("unknown kind or version")
            raw = payload.get("data") or {}
            if not isinstance(raw, dict):
                raise TypeError("data must be an object")
            data = dict(raw)
            for f in _BYTES_FIELDS:
                v = data.get(f)
                if isinstance(v, dict) and "__b64__" in v:
                    encoded = v["__b64__"]
                    if not isinstance(encoded, str) or len(encoded) > _MAX_B64_CHARS:
                        raise ValueError(f"invalid or oversized bytes field {f!r}")
                    data[f] = base64.b64decode(encoded, validate=True)
            # Caller identity comes from the authenticated session/envelope, never the payload.
            data.pop("caller", None)
            return cls.model_validate(data)
        except SquawkError:
            raise
        except Exception as exc:  # TypeError, ValueError, binascii.Error, pydantic.ValidationError
            raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "malformed") from exc
