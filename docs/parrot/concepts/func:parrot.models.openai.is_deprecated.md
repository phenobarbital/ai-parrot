---
type: Concept
title: is_deprecated()
id: func:parrot.models.openai.is_deprecated
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return True if ``model`` is in DEPRECATIONS or matches an alias entry.
---

# is_deprecated

```python
def is_deprecated(model: Union[str, OpenAIModel]) -> bool
```

Return True if ``model`` is in DEPRECATIONS or matches an alias entry.

An alias-match only counts as deprecated when the alias itself is NOT a
current ``OpenAIModel`` value.

Examples::

    is_deprecated("gpt-4-turbo-2024-04-09")  # True — direct key
    is_deprecated("gpt-4-turbo")              # True — alias of dead family
    is_deprecated("gpt-4.1-nano")             # True — deprecated alias
    is_deprecated("gpt-5-mini")               # False
    is_deprecated(OpenAIModel.GPT5_MINI)      # False
