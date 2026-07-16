---
type: Concept
title: resolve_alias()
id: func:parrot.models.openai.resolve_alias
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Map a deprecated model ID to the recommended migration target.
---

# resolve_alias

```python
def resolve_alias(model: Union[str, OpenAIModel]) -> str
```

Map a deprecated model ID to the recommended migration target.

Per spec §8 Q3 — currently using interpretation (b): deprecated IDs
are mapped to the new client-wide default ``gpt-5-mini``.
Pass-through for non-deprecated IDs.

TODO(spec §8 Q3): revisit if interpretation (a) (canonical-alias) is preferred.
