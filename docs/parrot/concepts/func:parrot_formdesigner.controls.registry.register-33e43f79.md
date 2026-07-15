---
type: Concept
title: register_field_control()
id: func:parrot_formdesigner.controls.registry.register_field_control
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Register (or overwrite) a control entry in the toolbar registry.
---

# register_field_control

```python
def register_field_control(field_type: FieldType | str, *, label: str, description: str, category: str, icon: str, snippet: dict[str, Any], render_hint: str, supports_constraints: bool, is_container: bool=False, supported_operators: list[str] | None=None, supported_effects: list[str] | None=None, supported_operations: list[str] | None=None) -> None
```

Register (or overwrite) a control entry in the toolbar registry.

Idempotent: re-registering the same ``field_type`` overwrites the previous
entry and logs a warning.

Args:
    field_type: A ``FieldType`` enum or a string id (for extension types).
    label: Short, human-readable label.
    description: Description for the toolbar tooltip / help.
    category: One of ``"basic" | "selection" | "media" | "layout" | "advanced"``.
    icon: Consumer-defined glyph name.
    snippet: JSON Schema snippet seed.
    render_hint: UI hint (e.g. ``"input"``, ``"select"``, ``"container"``).
    supports_constraints: Whether the control supports validation constraints.
    is_container: Whether the control nests other fields. Defaults to ``False``.
    supported_operators: ``ConditionOperator`` values meaningful for this type.
        ``None`` (default) and ``[]`` both mean "all operators applicable".
    supported_effects: Dependency ``effect`` values applicable to this type.
        ``None`` (default) and ``[]`` both mean "all effects applicable".
    supported_operations: ``DependencyOperation.op`` values that make sense
        for this type.  ``None`` (default) and ``[]`` both mean "all ops".
