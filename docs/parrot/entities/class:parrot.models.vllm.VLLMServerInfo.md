---
type: Wiki Entity
title: VLLMServerInfo
id: class:parrot.models.vllm.VLLMServerInfo
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: vLLM server information model.
---

# VLLMServerInfo

Defined in [`parrot.models.vllm`](../summaries/mod:parrot.models.vllm.md).

```python
class VLLMServerInfo(BaseModel)
```

vLLM server information model.

Contains metadata about the running vLLM server instance.

Attributes:
    version: vLLM version string
    model_id: Currently loaded model identifier
    gpu_memory_utilization: GPU memory utilization (0.0 to 1.0)
    max_model_len: Maximum model context length
    tensor_parallel_size: Number of GPUs for tensor parallelism
