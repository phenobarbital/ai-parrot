---
type: Wiki Entity
title: OptionsSource
id: class:parrot.forms.options.OptionsSource
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Dynamic options source configuration for fetching options at runtime.
---

# OptionsSource

Defined in [`parrot.forms.options`](../summaries/mod:parrot.forms.options.md).

```python
class OptionsSource(BaseModel)
```

Dynamic options source configuration for fetching options at runtime.

Attributes:
    source_type: Type of source (e.g., "tool", "endpoint", "query").
    source_ref: Reference to the source (tool name, URL, query name).
    value_field: Field in the source response to use as option value.
    label_field: Field in the source response to use as option label.
    cache_ttl_seconds: How long to cache the fetched options. None means no cache.
