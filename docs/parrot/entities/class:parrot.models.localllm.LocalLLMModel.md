---
type: Wiki Entity
title: LocalLLMModel
id: class:parrot.models.localllm.LocalLLMModel
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Common local LLM model identifiers.
---

# LocalLLMModel

Defined in [`parrot.models.localllm`](../summaries/mod:parrot.models.localllm.md).

```python
class LocalLLMModel(Enum)
```

Common local LLM model identifiers.

Enumerates popular open-weight models typically served via
Ollama, vLLM, llama.cpp, or LM Studio. Values match the model
name strings expected by these servers.
