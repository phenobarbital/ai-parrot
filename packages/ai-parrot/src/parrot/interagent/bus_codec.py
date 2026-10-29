"""Bytes-safe mapping of Squawk messages onto a JSON EventEnvelope.payload (Squawk-owned convention, spec §8 Q2)."""

from __future__ import annotations

import base64
import json
from datetime import date, datetime
from enum import Enum
from typing import Any

from parrot.interagent.errors import SquawkError, SquawkErrorCode
from parrot.interagent.messages import (
    Budget,
    CallMessage,
    CancelMessage,
    HelloMessage,
    ProgressMessage,
    ResultMessage,
    WelcomeMessage,
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
        """Deserialize a JSON payload to a bus message.

        Args:
            payload: A dict with 'kind', 'v', and 'data' keys.

        Returns:
            The deserialized bus message.

        Raises:
            SquawkError: If kind or version is unknown, or validation fails.
        """
        cls = _KINDS.get(str(payload.get("kind")))
        if cls is None or payload.get("v") != VERSION:
            raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "malformed")
        data = dict(payload.get("data") or {})
        # Decode base64 bytes fields
        for f in _BYTES_FIELDS:
            v = data.get(f)
            if isinstance(v, dict) and "__b64__" in v:
                data[f] = base64.b64decode(v["__b64__"])
        try:
            return cls.model_validate(data)
        except Exception as exc:  # pydantic.ValidationError and friends
            raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "malformed") from exc