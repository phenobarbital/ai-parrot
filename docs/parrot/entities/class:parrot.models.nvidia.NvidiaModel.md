---
type: Wiki Entity
title: NvidiaModel
id: class:parrot.models.nvidia.NvidiaModel
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Nvidia NIM-hosted model identifiers.
---

# NvidiaModel

Defined in [`parrot.models.nvidia`](../summaries/mod:parrot.models.nvidia.md).

```python
class NvidiaModel(str, Enum)
```

Nvidia NIM-hosted model identifiers.

String-valued enum so members interchange with raw model strings
in OpenAI SDK calls (e.g. ``model=NvidiaModel.KIMI_K2_THINKING.value``
or simply ``model=NvidiaModel.KIMI_K2_THINKING`` since the class
inherits from ``str``).

All slugs have been verified against the Nvidia NIM model catalog.
