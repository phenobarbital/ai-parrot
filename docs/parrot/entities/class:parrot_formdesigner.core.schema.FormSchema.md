---
type: Wiki Entity
title: FormSchema
id: class:parrot_formdesigner.core.schema.FormSchema
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: The canonical representation of a complete form.
---

# FormSchema

Defined in [`parrot_formdesigner.core.schema`](../summaries/mod:parrot_formdesigner.core.schema.md).

```python
class FormSchema(BaseModel)
```

The canonical representation of a complete form.

FormSchema is the central data model of the forms abstraction layer.
It is platform-agnostic and can be rendered to Adaptive Cards, HTML5,
JSON Schema, or any other format via the renderer system.

Attributes:
    form_id: Unique identifier for this form.
    version: Schema version string.
    title: Human-readable form title.
    description: Optional description of the form's purpose.
    sections: Ordered list of form sections.
    submit: Optional submission action configuration.
    cancel_allowed: Whether the user can cancel/dismiss the form.
    meta: Arbitrary metadata for renderer-specific extensions.
    created_at: Optional creation timestamp (UTC). Populated by storage
        backends when forms are loaded from persistence; ``None`` for
        ad-hoc forms registered in memory.
    tenant: Optional tenant slug. When set, persistence backends use it
        to resolve the Postgres schema where the form is stored
        (e.g. ``"epson"`` → ``epson.form_schemas``). ``None`` falls
        back to the storage's default schema.
    metadata: Declared contextual metadata fields captured on submission.
    events: Optional lifecycle event bindings (FEAT-188). Maps each
        lifecycle event name (``onBeforeOpen``, ``onSchemaLoaded``,
        ``onBeforeSubmit``, ``onAfterSubmit``, ``onError``) to a
        ``FormEventBinding`` that declares the logical handler reference
        and transport options. When ``None`` (default), no lifecycle hooks
        are invoked — forms without events behave identically to their
        pre-FEAT-188 state.
    is_public: If True, the form's read and submission URLs are accessible
        without authentication. Default ``False``. Toggling to ``True``
        registers the form's public paths in navigator-auth's runtime
        exclude list; toggling to ``False`` or deleting the form unregisters
        them. (FEAT-241)

## Methods

- `def iter_all_fields(self) -> Iterator[FormField]` — Yield every ``FormField`` across all sections, flattening subsections.
