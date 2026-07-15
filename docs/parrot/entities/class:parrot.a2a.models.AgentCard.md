---
type: Wiki Entity
title: AgentCard
id: class:parrot.a2a.models.AgentCard
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Self-describing manifest for an agent (A2A v1.0 structure).
---

# AgentCard

Defined in [`parrot.a2a.models`](../summaries/mod:parrot.a2a.models.md).

```python
class AgentCard
```

Self-describing manifest for an agent (A2A v1.0 structure).

Replaces the flat v0.3 ``url`` + ``preferredTransport`` with a structured
``supported_interfaces`` array. The flat accessors remain available as
read-only backward-compat properties (``url``, ``preferred_transport``,
``protocol_version``) so existing consumers keep working.

## Methods

- `def url(self) -> Optional[str]` — Backward-compat: first interface URL (the v0.3 flat `url`).
- `def url(self, value: Optional[str]) -> None` — Backward-compat writable `url`: update (or create) the first interface.
- `def preferred_transport(self) -> str` — Backward-compat: first interface protocol binding.
- `def preferred_transport(self, value: str) -> None` — Backward-compat writable `preferred_transport`.
- `def protocol_version(self) -> str` — Backward-compat: first interface protocol version.
- `def to_dict(self, version: str='1.0') -> Dict[str, Any]`
- `def from_dict(cls, data: Dict[str, Any]) -> 'AgentCard'`
