---
type: Wiki Entity
title: VLLMSamplingParams
id: class:parrot.models.vllm.VLLMSamplingParams
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extended sampling parameters for vLLM.
---

# VLLMSamplingParams

Defined in [`parrot.models.vllm`](../summaries/mod:parrot.models.vllm.md).

```python
class VLLMSamplingParams(BaseModel)
```

Extended sampling parameters for vLLM.

These parameters extend the standard OpenAI-compatible sampling
with vLLM-specific options for fine-grained control.

Attributes:
    top_k: Top-k sampling (-1 to disable)
    min_p: Minimum probability threshold (0.0 to 1.0)
    repetition_penalty: Penalty for repeated tokens (>1.0 to discourage)
    length_penalty: Length penalty for beam search
    presence_penalty: Penalty for new tokens based on presence
    frequency_penalty: Penalty for new tokens based on frequency

## Methods

- `def to_extra_body(self) -> Dict[str, Any]` — Convert to vLLM extra_body format.
