---
type: Wiki Entity
title: ProducerOrigin
id: class:parrot.outputs.a2ui.catalog.base.ProducerOrigin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Origin of an envelope, controlling ``requires_actions`` enforcement.
---

# ProducerOrigin

Defined in [`parrot.outputs.a2ui.catalog.base`](../summaries/mod:parrot.outputs.a2ui.catalog.base.md).

```python
class ProducerOrigin(str, Enum)
```

Origin of an envelope, controlling ``requires_actions`` enforcement.

Tool builders emit envelopes deterministically and MAY include action-bearing
components (they degrade to deep links at render time). The LLM producer path
is display-only in v1 and MUST NOT emit ``requires_actions`` components.
