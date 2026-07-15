---
type: Wiki Entity
title: OutputRetryConfig
id: class:parrot.outputs.formatter.OutputRetryConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for LLM-based output retry on parsing failures.
---

# OutputRetryConfig

Defined in [`parrot.outputs.formatter`](../summaries/mod:parrot.outputs.formatter.md).

```python
class OutputRetryConfig
```

Configuration for LLM-based output retry on parsing failures.

When output parsing fails (e.g., malformed JSON for ECharts), this config
controls how the system will use an LLM to attempt to fix the output.

Attributes:
    max_retries: Maximum number of retry attempts (default: 2)
    retry_on_parse_error: Whether to retry on parsing/validation errors
    retry_model: Optional specific model to use for retries (uses client default if None)
    retry_temperature: Temperature for retry requests (lower = more deterministic)
    retry_max_tokens: Max tokens for retry response
    include_original_prompt: Whether to include the original user prompt in retry
    custom_retry_prompts: Optional dict mapping OutputMode to custom retry prompts

## Methods

- `def get_retry_prompt(self, mode: OutputMode) -> Optional[str]` — Get custom retry prompt for a specific output mode.
