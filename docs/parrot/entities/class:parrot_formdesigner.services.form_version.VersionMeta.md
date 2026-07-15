---
type: Wiki Entity
title: VersionMeta
id: class:parrot_formdesigner.services.form_version.VersionMeta
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Metadata record for a published form version.
---

# VersionMeta

Defined in [`parrot_formdesigner.services.form_version`](../summaries/mod:parrot_formdesigner.services.form_version.md).

```python
class VersionMeta(BaseModel)
```

Metadata record for a published form version.

Attributes:
    form_id: The form's canonical identifier.
    version: The semver-style ``major.minor`` tag (e.g. ``"1.0"``).
    published_at: UTC timestamp when this version was published.
    tenant: Tenant slug.
    is_frozen: Always ``True`` — published versions are immutable.
