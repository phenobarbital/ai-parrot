---
type: Wiki Entity
title: GroqModel
id: class:parrot.models.groq.GroqModel
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Description for Enabled Groq models.
---

# GroqModel

Defined in [`parrot.models.groq`](../summaries/mod:parrot.models.groq.md).

```python
class GroqModel(Enum)
```

Description for Enabled Groq models.

Only these models are supporting Structured Output:
- meta-llama/llama-4-maverick-17b-128e-instruct
- meta-llama/llama-4-scout-17b-16e-instruct

Also, streaming output is not supported with structured outputs.
