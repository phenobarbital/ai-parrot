---
type: Wiki Entity
title: FieldControlMetadata
id: class:parrot_formdesigner.controls.registry.FieldControlMetadata
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Metadata describing a single form-control entry for the toolbar.
---

# FieldControlMetadata

Defined in [`parrot_formdesigner.controls.registry`](../summaries/mod:parrot_formdesigner.controls.registry.md).

```python
class FieldControlMetadata(BaseModel)
```

Metadata describing a single form-control entry for the toolbar.

Attributes:
    type: Canonical id (`FieldType.value` or extension type id).
    label: Short, human-readable name.
    description: Description shown in the toolbar tooltip / help.
    category: Grouping bucket — one of
        ``"basic" | "selection" | "media" | "layout" | "advanced"``.
    icon: Consumer-defined glyph name.
    snippet: JSON Schema snippet seed to drop into a new form.
    render_hint: UI hint such as ``"input" | "select" | "container"``.
    supports_constraints: Whether the control supports validation
        constraints (min/max length, regex, etc.).
    is_container: Whether the control nests other fields (groups, arrays).
    supported_operators: List of ``ConditionOperator`` values meaningful for
        this control type (used in ``depends_on.conditions`` and
        ``post_depends.conditions``).  Empty list = all operators accepted.
        Optional — omit for extension types.
    supported_effects: List of pre-dependency ``effect`` values applicable
        to this control (``"show" | "hide" | "require" | "disable"``).
        Empty list = all effects applicable.  Optional.
    supported_operations: List of :class:`DependencyOperation` ``op`` values
        that make semantic sense for this control type (e.g. arithmetic ops
        only for numeric types).  Empty list = all ops applicable.  Optional.
