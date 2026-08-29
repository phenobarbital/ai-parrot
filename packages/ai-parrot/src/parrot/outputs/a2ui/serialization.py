"""A2UI serialization layer — the *sole* owner of the protocol ``version`` field.

Every A2UI v1.0 message on the wire is an **envelope by key**:
``{"version": "v1.0", "<messageKey>": {...}}`` with exactly one message key
besides ``version``. Per spec FEAT-470 (G3), that field is written in exactly
one place: this module. The inner message models
(:mod:`parrot.outputs.a2ui.models`) never default or write it themselves.

Responsibilities:

* Serialize any inner A2UI message (``CreateSurface``, ``ActionMessage``, ...)
  — or an already-built envelope (:class:`~parrot.outputs.a2ui.models.A2UIAgentMessage`
  / :class:`~parrot.outputs.a2ui.models.A2UIRendererMessage`) — to a JSON dict
  or a JSONL line, injecting ``version``.
* Deserialize incoming JSON/JSONL into the correct envelope model. Legacy
  (pre-v1.0) payloads are detected and normalized via
  :mod:`parrot.outputs.a2ui.compat` first, with a ``DeprecationWarning``
  (spec G5 — compat is read-only; nothing here ever emits the legacy shape).
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Iterable, Iterator
from typing import Any

from parrot.outputs.a2ui import compat
from parrot.outputs.a2ui.models import (
    A2UIAgentMessage,
    A2UIMessageBase,
    A2UIRendererMessage,
    ActionMessage,
    AgentFunctionResponse,
    CallAgentFunction,
    CallRendererFunction,
    CreateSurface,
    DeleteSurface,
    ErrorMessage,
    RendererFunctionResponse,
    UpdateComponents,
    UpdateDataModel,
)

__all__ = [
    "A2UI_VERSION",
    "VERSION_FIELD",
    "deserialize",
    "iter_jsonl",
    "serialize",
    "to_jsonl",
]

#: The A2UI protocol version this serialization layer emits and validates.
A2UI_VERSION = "v1.0"

#: The wire field name carrying the protocol version.
VERSION_FIELD = "version"

#: Agent -> Renderer inner message classes, keyed by their wire message key.
_AGENT_KEY_BY_CLASS: dict[type[A2UIMessageBase], str] = {
    CreateSurface: "createSurface",
    UpdateComponents: "updateComponents",
    UpdateDataModel: "updateDataModel",
    DeleteSurface: "deleteSurface",
    CallRendererFunction: "callRendererFunction",
    AgentFunctionResponse: "agentFunctionResponse",
}

#: Renderer -> Agent inner message classes, keyed by their wire message key.
_RENDERER_KEY_BY_CLASS: dict[type[A2UIMessageBase], str] = {
    ActionMessage: "action",
    CallAgentFunction: "callAgentFunction",
    RendererFunctionResponse: "rendererFunctionResponse",
    ErrorMessage: "error",
}

_KEY_BY_CLASS: dict[type[A2UIMessageBase], str] = {
    **_AGENT_KEY_BY_CLASS,
    **_RENDERER_KEY_BY_CLASS,
}

_AGENT_KEYS = frozenset(_AGENT_KEY_BY_CLASS.values())
_RENDERER_KEYS = frozenset(_RENDERER_KEY_BY_CLASS.values())

#: Any concrete inner A2UI message (agent- or renderer-originated).
AnyA2UIMessage = (
    CreateSurface
    | UpdateComponents
    | UpdateDataModel
    | DeleteSurface
    | CallRendererFunction
    | AgentFunctionResponse
    | ActionMessage
    | CallAgentFunction
    | RendererFunctionResponse
    | ErrorMessage
)

#: Any A2UI message-shaped object accepted by :func:`serialize`.
Serializable = AnyA2UIMessage | A2UIAgentMessage | A2UIRendererMessage


def serialize(message: Serializable) -> dict[str, Any]:
    """Serialize an A2UI message to a JSON-ready envelope dict.

    Accepts either a concrete inner message (``CreateSurface``, ...) or an
    already-built envelope (``A2UIAgentMessage``/``A2UIRendererMessage``).

    Args:
        message: Any A2UI inner message or envelope instance.

    Returns:
        ``{"version": "v1.0", "<messageKey>": {...}}`` — exactly two keys.

    Raises:
        TypeError: If ``message`` is not a recognized A2UI message type.
    """
    if isinstance(message, (A2UIAgentMessage, A2UIRendererMessage)):
        for field_name in message.__class__.model_fields:
            if field_name == "version":
                continue
            inner = getattr(message, field_name)
            if inner is not None:
                return serialize(inner)
        raise ValueError("A2UI envelope carries no message key.")  # pragma: no cover

    for cls, key in _KEY_BY_CLASS.items():
        if isinstance(message, cls):
            payload = message.model_dump(by_alias=True, mode="json", exclude_none=True)
            # ``exclude_none`` drops optional None fields (path, catalogId, ...)
            # but MUST NOT drop an explicit ``value: null`` — that is a
            # meaningful, distinct wire signal ("delete this key"/"function
            # returned null"), not the absence of a field.
            if isinstance(message, UpdateDataModel) or (
                isinstance(message, (AgentFunctionResponse, RendererFunctionResponse))
                and "value" in message.model_fields_set
            ):
                payload["value"] = message.value
            return {VERSION_FIELD: A2UI_VERSION, key: payload}

    raise TypeError(f"Cannot serialize unknown A2UI message type: {type(message)!r}.")


def _validate_envelope(data: dict[str, Any]) -> A2UIAgentMessage | A2UIRendererMessage:
    """Route a v1.0-shaped envelope dict to the correct envelope model."""
    keys = set(data) - {VERSION_FIELD}
    if keys & _AGENT_KEYS:
        return A2UIAgentMessage.model_validate(data)
    if keys & _RENDERER_KEYS:
        return A2UIRendererMessage.model_validate(data)
    raise ValueError(f"Unrecognized A2UI envelope keys: {sorted(keys)!r}.")


def deserialize(
    data: dict[str, Any] | str | bytes,
) -> A2UIAgentMessage | A2UIRendererMessage | list[A2UIAgentMessage]:
    """Deserialize wire JSON into the correct A2UI v1.0 envelope.

    Legacy (pre-v1.0) payloads (``"messageType" in data``) are normalized via
    :mod:`parrot.outputs.a2ui.compat` first, emitting a ``DeprecationWarning``.
    A legacy ``updateDataModel`` with multiple ``contents`` keys normalizes to
    several v1.0 envelopes — the ONE case where this function returns a list.

    Args:
        data: A JSON dict, or a JSON string/bytes payload.

    Returns:
        The validated envelope (or a list of envelopes, for the legacy
        multi-content ``updateDataModel`` case).

    Raises:
        pydantic.ValidationError: If the payload does not validate as a v1.0
            envelope.
        TypeError: If the payload is not a JSON object.
        ValueError: If its legacy ``messageType`` is unsupported (see
            :func:`compat.normalize_legacy`), or its envelope keys are
            unrecognized.
    """
    if isinstance(data, (str, bytes)):
        data = json.loads(data)
    if not isinstance(data, dict):
        raise TypeError(f"A2UI message must be a JSON object, got {type(data)!r}.")

    if compat.is_legacy_envelope(data):
        normalized = compat.normalize_legacy(data)
        warnings.warn(
            "Received a legacy (pre-A2UI-v1.0) dialect payload; normalizing to "
            "v1.0. Emit v1.0 directly instead — legacy read support is "
            "compatibility-only and carries no emission guarantee.",
            DeprecationWarning,
            stacklevel=2,
        )
        if isinstance(normalized, list):
            return [_validate_envelope(item) for item in normalized]  # type: ignore[misc]
        return _validate_envelope(normalized)

    return _validate_envelope(data)


def to_jsonl(messages: Serializable | Iterable[Serializable]) -> str:
    """Serialize one or more messages to JSONL (one complete envelope per line).

    Args:
        messages: A single A2UI message/envelope, or an iterable of them.

    Returns:
        A JSONL string; each line is a complete, parseable A2UI v1.0 envelope.
    """
    if isinstance(messages, (A2UIMessageBase, A2UIAgentMessage, A2UIRendererMessage)):
        messages = [messages]
    return "\n".join(json.dumps(serialize(m)) for m in messages)


def iter_jsonl(text: str) -> Iterator[A2UIAgentMessage | A2UIRendererMessage]:
    """Parse a JSONL payload into A2UI envelopes, one per non-empty line.

    Args:
        text: A JSONL string.

    Yields:
        Concrete A2UI envelopes in line order.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = deserialize(line)
        if isinstance(parsed, list):
            yield from parsed
        else:
            yield parsed
