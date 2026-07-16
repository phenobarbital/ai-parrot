---
type: Wiki Entity
title: TokenRetryMixin
id: class:parrot.clients.base.TokenRetryMixin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Mixin class to add token retry functionality to any LLM client.
---

# TokenRetryMixin

Defined in [`parrot.clients.base`](../summaries/mod:parrot.clients.base.md).

```python
class TokenRetryMixin
```

Mixin class to add token retry functionality to any LLM client.

## Methods

- `def is_token_limit_error(self, error: Exception) -> bool` — Check if the error is related to token limits.
- `def should_retry_with_more_tokens(self, current_tokens: int, retry_count: int) -> bool` — Determine if we should retry with increased tokens.
- `def get_increased_token_limit(self, current_tokens: int) -> int` — Calculate the new token limit for retry.
