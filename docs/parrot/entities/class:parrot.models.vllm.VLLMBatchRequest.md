---
type: Wiki Entity
title: VLLMBatchRequest
id: class:parrot.models.vllm.VLLMBatchRequest
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Batch request model for vLLM batch processing.
---

# VLLMBatchRequest

Defined in [`parrot.models.vllm`](../summaries/mod:parrot.models.vllm.md).

```python
class VLLMBatchRequest(BaseModel)
```

Batch request model for vLLM batch processing.

Represents a single request within a batch, containing
the prompt and optional parameters for generation.

Attributes:
    prompt: The input prompt or messages
    model: Model identifier (optional, uses default if not specified)
    temperature: Sampling temperature
    max_tokens: Maximum tokens to generate
    guided_json: Optional JSON schema constraint
    guided_regex: Optional regex constraint
    guided_choice: Optional choice constraint
    lora_adapter: Optional LoRA adapter name
    sampling_params: Optional extended sampling parameters
