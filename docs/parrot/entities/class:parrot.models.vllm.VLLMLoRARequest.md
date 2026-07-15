---
type: Wiki Entity
title: VLLMLoRARequest
id: class:parrot.models.vllm.VLLMLoRARequest
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: LoRA adapter configuration for vLLM requests.
---

# VLLMLoRARequest

Defined in [`parrot.models.vllm`](../summaries/mod:parrot.models.vllm.md).

```python
class VLLMLoRARequest(BaseModel)
```

LoRA adapter configuration for vLLM requests.

vLLM supports dynamically loading and switching between LoRA adapters
at request time, enabling fine-tuned behavior without reloading models.

Attributes:
    lora_name: Name of the LoRA adapter to use
    lora_int_id: Optional integer ID for the LoRA adapter
    lora_local_path: Optional local path to LoRA adapter weights

## Methods

- `def to_extra_body(self) -> Dict[str, Any]` — Convert to vLLM lora_request format.
