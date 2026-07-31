---
type: Wiki Entity
title: Artifact
id: class:parrot.a2a.models.Artifact
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Output produced by an agent.
---

# Artifact

Defined in [`parrot.a2a.models`](../summaries/mod:parrot.a2a.models.md).

```python
class Artifact
```

Output produced by an agent.

## Methods

- `def from_a2ui_envelope(cls, envelope: Dict[str, Any], *, name: str='a2ui-surface', artifact_id: Optional[str]=None) -> 'Artifact'` — Wrap a display A2UI ``CreateSurface`` envelope into an A2A Artifact.
- `def from_response(cls, response: Any, name: str='response') -> 'Artifact'` — Create artifact from an AIMessage or string response.
- `def to_dict(self, version: str='1.0') -> Dict[str, Any]`
