---
type: Concept
title: truncate_to_tokens()
id: func:parrot.knowledge.wiki.context.truncate_to_tokens
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Deterministically truncate ``text`` to approximately ``max_tokens``.
---

# truncate_to_tokens

```python
def truncate_to_tokens(text: str, max_tokens: Optional[int]) -> tuple[str, bool]
```

Deterministically truncate ``text`` to approximately ``max_tokens``.

Uses the same 4-chars-per-token heuristic as the fallback estimator
so truncation never requires a tokenizer; cuts on a whitespace
boundary where possible.

Args:
    text: Text to truncate.
    max_tokens: Token ceiling; ``None`` disables truncation.

Returns:
    ``(text, truncated_flag)``.
