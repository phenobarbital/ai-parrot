---
type: Wiki Entity
title: VLLMConfig
id: class:parrot.models.vllm.VLLMConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration for vLLM client.
---

# VLLMConfig

Defined in [`parrot.models.vllm`](../summaries/mod:parrot.models.vllm.md).

```python
class VLLMConfig(BaseModel)
```

Configuration for vLLM client.

Attributes:
    base_url: vLLM server base URL (default: http://localhost:8000/v1)
    api_key: Optional API key for authentication
    timeout: Request timeout in seconds
