---
type: Wiki Summary
title: parrot.models.vllm
id: mod:parrot.models.vllm
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic models for vLLM client integration.
relates_to:
- concept: class:parrot.models.vllm.VLLMBatchRequest
  rel: defines
- concept: class:parrot.models.vllm.VLLMBatchResponse
  rel: defines
- concept: class:parrot.models.vllm.VLLMConfig
  rel: defines
- concept: class:parrot.models.vllm.VLLMGuidedParams
  rel: defines
- concept: class:parrot.models.vllm.VLLMLoRARequest
  rel: defines
- concept: class:parrot.models.vllm.VLLMSamplingParams
  rel: defines
- concept: class:parrot.models.vllm.VLLMServerInfo
  rel: defines
- concept: func:parrot.models.vllm.pydantic_to_guided_json
  rel: defines
---

# `parrot.models.vllm`

Pydantic models for vLLM client integration.

This module provides configuration and request/response models
for the vLLMClient, supporting vLLM-specific features like guided
decoding, LoRA adapters, and batch processing.

## Classes

- **`VLLMConfig(BaseModel)`** — Configuration for vLLM client.
- **`VLLMSamplingParams(BaseModel)`** — Extended sampling parameters for vLLM.
- **`VLLMLoRARequest(BaseModel)`** — LoRA adapter configuration for vLLM requests.
- **`VLLMGuidedParams(BaseModel)`** — Guided decoding parameters for constrained generation.
- **`VLLMBatchRequest(BaseModel)`** — Batch request model for vLLM batch processing.
- **`VLLMBatchResponse(BaseModel)`** — Batch response model for vLLM batch processing.
- **`VLLMServerInfo(BaseModel)`** — vLLM server information model.

## Functions

- `def pydantic_to_guided_json(model: Type[BaseModel]) -> Dict[str, Any]` — Convert a Pydantic model class to vLLM guided_json schema.
