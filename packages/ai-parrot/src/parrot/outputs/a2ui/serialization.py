"""A2UI serialization layer — the *sole* owner of the protocol ``version`` field.

Every A2UI message on the wire carries a ``version`` field. Per spec FEAT-273
(G3 and the "candidate spec with no other implementer" risk), that field is read
and written in exactly one place: this module. No model in
:mod:`parrot.outputs.a2ui.models` declares or defaults ``version``; a future
protocol fork is therefore absorbable here alone.

Responsibilities:

* Serialize any :data:`~parrot.outputs.a2ui.models.A2UIMessage` to a JSON dict or
  a JSONL line, injecting ``version``.
* Deserialize incoming JSON/JSONL into the discriminated union, validating and
  stripping ``version`` and rejecting unknown message types with a structured
  :class:`pydantic.ValidationError`.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Iterator

from pydantic import TypeAdapter

from parrot.outputs.a2ui.models import A2UIMessage, A2UIMessageBase

__all__ = [
    "A2UI_VERSION",
    "VERSION_FIELD",
    "deserialize",
    "iter_jsonl",
    "serialize",
    "to_jsonl",
]

#: The A2UI protocol version this serialization layer emits. Bump here (and only
#: here) when targeting a new protocol revision.
A2UI_VERSION = "1.0"

#: The wire field name carrying the protocol version.
VERSION_FIELD = "version"

#: Reusable adapter for the discriminated union. Building it once is cheaper and
#: gives consistent discriminator/alias handling.
_ADAPTER: TypeAdapter = TypeAdapter(A2UIMessage)


def serialize(message: A2UIMessageBase) -> dict[str, Any]:
    """Serialize an A2UI message to a JSON-ready dict, injecting ``version``.

    Args:
        message: Any concrete A2UI message instance.

    Returns:
        A dict using the wire (aliased) field names, with ``version`` set to
        :data:`A2UI_VERSION`.
    """
    payload = message.model_dump(by_alias=True, mode="json")
    # The serialization layer is the single owner of ``version``.
    payload[VERSION_FIELD] = A2UI_VERSION
    return payload


def deserialize(data: dict[str, Any] | str | bytes) -> A2UIMessageBase:
    """Deserialize wire JSON into the correct concrete A2UI message.

    The ``version`` field, if present, is type-checked (must be a string) and stripped
    before model validation so that it never leaks onto a model instance. Its *value* is
    intentionally NOT asserted equal to :data:`A2UI_VERSION` — forward/backward
    compatibility (absorbing a future protocol revision) is owned by this single module,
    so accepting a differing version string here is deliberate.

    Args:
        data: A JSON dict, or a JSON string/bytes payload.

    Returns:
        The concrete message routed via the ``messageType`` discriminator.

    Raises:
        pydantic.ValidationError: If the payload is not a valid, known message.
        ValueError: If ``version`` is present but not a string.
    """
    if isinstance(data, (str, bytes)):
        data = json.loads(data)
    if not isinstance(data, dict):
        raise ValueError(f"A2UI message must be a JSON object, got {type(data)!r}.")

    payload = dict(data)  # shallow copy — never mutate the caller's dict
    version = payload.pop(VERSION_FIELD, None)
    if version is not None and not isinstance(version, str):
        raise ValueError(f"A2UI {VERSION_FIELD!r} must be a string, got {version!r}.")

    # TypeAdapter validation routes via the discriminator and raises a structured
    # ValidationError for unknown message types.
    return _ADAPTER.validate_python(payload)


def to_jsonl(messages: A2UIMessageBase | Iterable[A2UIMessageBase]) -> str:
    """Serialize one or more messages to JSONL (one complete message per line).

    Args:
        messages: A single message or an iterable of messages.

    Returns:
        A JSONL string; each line is a complete, parseable A2UI message.
    """
    if isinstance(messages, A2UIMessageBase):
        messages = [messages]
    return "\n".join(json.dumps(serialize(m)) for m in messages)


def iter_jsonl(text: str) -> Iterator[A2UIMessageBase]:
    """Parse a JSONL payload into A2UI messages, one per non-empty line.

    Args:
        text: A JSONL string.

    Yields:
        Concrete A2UI messages in line order.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        yield deserialize(line)
