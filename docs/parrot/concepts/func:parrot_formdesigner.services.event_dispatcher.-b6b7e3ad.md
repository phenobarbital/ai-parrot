---
type: Concept
title: apply_schema_overrides()
id: func:parrot_formdesigner.services.event_dispatcher.apply_schema_overrides
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Shallow-merge ``overrides`` onto a copy of ``base``.
---

# apply_schema_overrides

```python
def apply_schema_overrides(base: dict[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]
```

Shallow-merge ``overrides`` onto a copy of ``base``.

Only top-level keys are replaced. Nested structures in ``base`` that
share a key with ``overrides`` are entirely replaced by the value from
``overrides`` (no deep merge). This is intentional per spec §7 MVP
decision; deep merge is deferred to a follow-up.

Args:
    base: The serialised ``FormSchema`` dict to patch.
    overrides: Top-level key/value pairs to merge in.

Returns:
    A new dict with ``overrides`` applied (``base`` is not mutated).

Example::

    >>> apply_schema_overrides({"a": 1, "b": {"x": 1}}, {"b": {"y": 2}})
    {"a": 1, "b": {"y": 2}}  # nested "x" is dropped — shallow only
