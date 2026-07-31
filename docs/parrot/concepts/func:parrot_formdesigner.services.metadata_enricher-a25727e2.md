---
type: Concept
title: enrich_submission()
id: func:parrot_formdesigner.services.metadata_enricher.enrich_submission
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Resolve declared metadata for a pending submission.
---

# enrich_submission

```python
async def enrich_submission(*, request: 'web.Request', form: 'FormSchema', submission: 'FormSubmission', answers: dict[str, Any], auth_context: 'AuthContext') -> tuple[dict[str, Any], dict[str, Any]]
```

Resolve declared metadata for a pending submission.

Iterates ``form.metadata`` in declaration order, dispatching each
entry to either the built-in source resolver
(:data:`BUILTIN_METADATA_SOURCES`) or a registered async callback
looked up via :func:`get_form_callback` with tenant fallback.

Args:
    request: Inbound aiohttp request, used by built-in resolvers
        to read session / user / headers.
    form: The form definition; its ``tenant`` field drives callback
        lookup.
    submission: The in-flight ``FormSubmission`` (constructed but
        not yet stored). Resolvers may read its existing fields
        (e.g. ``submission_id``, ``created_at``).
    answers: Sanitized form answers from the validator.
    auth_context: Runtime auth context forwarded to callbacks.

Returns:
    Tuple ``(core_overrides, extra_flat)`` where ``core_overrides``
    is a dict whose keys are a subset of ``CORE_METADATA_COLUMNS``
    (to be applied via ``submission.model_copy(update=...)``) and
    ``extra_flat`` is a dict of remaining keys to merge into
    ``submission.data``.

Raises:
    MetadataResolutionError: When a ``required=True`` entry cannot
        be resolved, or when a callback fan-out returns an invalid
        identifier as a key, or when a resolved key would collide
        with an existing answer in ``answers``.
