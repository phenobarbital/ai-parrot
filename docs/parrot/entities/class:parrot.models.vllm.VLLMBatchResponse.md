---
type: Wiki Entity
title: VLLMBatchResponse
id: class:parrot.models.vllm.VLLMBatchResponse
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Batch response model for vLLM batch processing.
---

# VLLMBatchResponse

Defined in [`parrot.models.vllm`](../summaries/mod:parrot.models.vllm.md).

```python
class VLLMBatchResponse(BaseModel)
```

Batch response model for vLLM batch processing.

Contains the results of a batch processing operation,
including individual responses and aggregate statistics.

Attributes:
    responses: List of generated text responses
    errors: List of errors for failed requests (indexed by position)
    total_requests: Total number of requests in the batch
    successful: Number of successful completions
    failed: Number of failed requests
    total_tokens: Total tokens used across all requests
