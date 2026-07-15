---
type: Wiki Entity
title: PartialFormData
id: class:parrot_formdesigner.core.partial.PartialFormData
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Ephemeral partial form answer cache entry.
---

# PartialFormData

Defined in [`parrot_formdesigner.core.partial`](../summaries/mod:parrot_formdesigner.core.partial.md).

```python
class PartialFormData(BaseModel)
```

Ephemeral partial form answer cache entry.

Stored in Redis under key ``parrot:partial:{form_id}:{session_id}``.
Timezone-awareness is enforced via ``AwareDatetime`` — naive datetimes
will be rejected at validation time.

Attributes:
    form_id: The form whose answers are being cached.
    session_id: The user session that owns this cache entry.
    data: Sparse mapping of field_id to the cached value.  New values
        always override existing cached values (last-write-wins).
    field_errors: Per-field validation errors collected during the last
        ``save_partial`` call.  Mapping of field_id to a list of error
        message strings.
    saved_at: UTC timezone-aware timestamp of the most recent write.
    expires_at: UTC timezone-aware timestamp when this entry will expire
        in Redis.
