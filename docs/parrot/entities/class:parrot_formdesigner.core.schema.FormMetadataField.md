---
type: Wiki Entity
title: FormMetadataField
id: class:parrot_formdesigner.core.schema.FormMetadataField
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Declared contextual metadata captured on every form submission.
---

# FormMetadataField

Defined in [`parrot_formdesigner.core.schema`](../summaries/mod:parrot_formdesigner.core.schema.md).

```python
class FormMetadataField(BaseModel)
```

Declared contextual metadata captured on every form submission.

Metadata fields are computed in a before-save enrichment step on the
submit handler. Each declaration produces one or more ``key`` / value
pairs that are either promoted to a real ``form_data`` column (for
reserved core keys) or flat-merged into the submission ``data`` JSONB
alongside the user's answers (no ``"metadata"`` sub-object).

Attributes:
    key: Identifier under which the value is stored. Must be a valid
        Postgres identifier (``[A-Za-z_][A-Za-z0-9_]{0,62}``) so it
        is safe to promote to a column name and stable as a JSONB
        key. Validated at FormSchema construction.
    source: Where the value comes from. Built-in sources resolve
        against the inbound request / session; ``"callback"`` invokes
        a coroutine registered with ``register_form_callback``;
        ``"constant"`` returns ``default`` verbatim.
    label: Optional human-readable label (i18n supported).
    callback_ref: Required when ``source == "callback"``. Logical
        callback name looked up in the shared tenant-scoped form
        callback registry.
    default: Value substituted when the resolver returns ``None`` or
        a non-required callback fails. Also the source of truth for
        ``source == "constant"``.
    required: When ``True``, an unresolved value (resolver returns
        ``None`` after ``default`` substitution) fails the
        submission with HTTP 422.
    options: Free-form per-source options bag (e.g.
        ``{"header": "Accept-Language"}`` for ``locale``). Kept loose
        on purpose to avoid a discriminated union per built-in.
