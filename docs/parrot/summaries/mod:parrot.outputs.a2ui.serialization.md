---
type: Wiki Summary
title: parrot.outputs.a2ui.serialization
id: mod:parrot.outputs.a2ui.serialization
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: A2UI serialization layer — the *sole* owner of the protocol ``version`` field.
relates_to:
- concept: func:parrot.outputs.a2ui.serialization.deserialize
  rel: defines
- concept: func:parrot.outputs.a2ui.serialization.iter_jsonl
  rel: defines
- concept: func:parrot.outputs.a2ui.serialization.serialize
  rel: defines
- concept: func:parrot.outputs.a2ui.serialization.to_jsonl
  rel: defines
- concept: mod:parrot.outputs.a2ui.models
  rel: references
---

# `parrot.outputs.a2ui.serialization`

A2UI serialization layer — the *sole* owner of the protocol ``version`` field.

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

## Functions

- `def serialize(message: A2UIMessageBase) -> dict[str, Any]` — Serialize an A2UI message to a JSON-ready dict, injecting ``version``.
- `def deserialize(data: dict[str, Any] | str | bytes) -> A2UIMessageBase` — Deserialize wire JSON into the correct concrete A2UI message.
- `def to_jsonl(messages: A2UIMessageBase | Iterable[A2UIMessageBase]) -> str` — Serialize one or more messages to JSONL (one complete message per line).
- `def iter_jsonl(text: str) -> Iterator[A2UIMessageBase]` — Parse a JSONL payload into A2UI messages, one per non-empty line.
