---
type: Concept
title: select_smart_fields()
id: func:parrot_tools.odoo.smart_fields.select_smart_fields
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Select the most LLM-useful fields from an Odoo ``fields_get`` response.
---

# select_smart_fields

```python
def select_smart_fields(fields_metadata: dict[str, Any], max_fields: int=15, always_include: list[str] | None=None) -> list[str]
```

Select the most LLM-useful fields from an Odoo ``fields_get`` response.

Args:
    fields_metadata: Mapping of ``field_name → field_meta_dict`` as returned
        by ``fields_get``.  Each value must contain at minimum a ``"type"``
        key.
    max_fields: Maximum number of *scored* fields to include (excludes
        ``id``, ``display_name``, and any entries in ``always_include``).
        Defaults to 15.
    always_include: Extra field names to always include regardless of score.
        These don't count against ``max_fields``.

Returns:
    Sorted list of field names.  ``id`` and ``display_name`` come first
    (if they exist in the metadata), followed by the top-scoring fields in
    descending score order.  Binary/HTML fields are never included.

Example::

    meta = await toolkit.fields_get("res.partner")
    fields = select_smart_fields(meta, max_fields=10)
    # ["id", "display_name", "name", "email", "phone", ...]
