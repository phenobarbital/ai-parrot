---
type: Wiki Entity
title: DependencyOperation
id: class:parrot_formdesigner.core.constraints.DependencyOperation
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: An operation that computes or assigns a value from referenced field values.
---

# DependencyOperation

Defined in [`parrot_formdesigner.core.constraints`](../summaries/mod:parrot_formdesigner.core.constraints.md).

```python
class DependencyOperation(BaseModel)
```

An operation that computes or assigns a value from referenced field values.

Used within :class:`DependencyRule` (as one of ``operations``) and
:class:`PostDependency` (as ``operation``) to express derived/calculated
field values.

Attributes:
    op: The operation kind. One of:
        - ``"copy"`` — copy a source field value to ``target``.
        - ``"add"`` / ``"subtract"`` / ``"multiply"`` / ``"divide"`` — arithmetic.
        - ``"percent"`` — compute a percentage.
        - ``"concat"`` — concatenate string operand values.
        - ``"format"`` — apply a format string (use ``options["template"]``).
        - ``"date_diff"`` — compute the difference between two dates
          (unit via ``options["unit"]``, e.g. ``"days"``).
        - ``"lookup"`` — look up a value via an external tool reference
          (tool ref in ``options["tool_ref"]``).
        - ``"aggregate"`` — aggregate values across repeated-section items
          (function in ``options["fn"]``, e.g. ``"sum"`` / ``"avg"`` / ``"count"``).
    operands: List of ``field_id`` strings whose current values are the
        inputs. Must be non-empty.
    target: The ``field_id`` that receives the computed value.
    options: Optional operation-specific configuration (e.g. ``{"unit": "days"}``
        for ``date_diff``, ``{"template": "{} {}"}`` for ``format``).
