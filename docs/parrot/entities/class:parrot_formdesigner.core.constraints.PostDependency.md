---
type: Wiki Entity
title: PostDependency
id: class:parrot_formdesigner.core.constraints.PostDependency
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'A forward dependency: how a field''s answered value affects a later field.'
---

# PostDependency

Defined in [`parrot_formdesigner.core.constraints`](../summaries/mod:parrot_formdesigner.core.constraints.md).

```python
class PostDependency(BaseModel)
```

A forward dependency: how a field's answered value affects a later field.

``PostDependency`` declares that the *owning* field's value has a forward
effect on a control declared **after** it.  Ordering is validated by
:class:`~parrot_formdesigner.services.FormValidator`.

Attributes:
    target: The ``field_id`` of the field to affect (must be declared
        *after* the owning field in the form layout).
    effect: The effect to apply.  ``"set"`` and ``"calc"`` require an
        ``operation``; the others are pure visibility/state changes.
        One of:

        - ``"set"`` — assign a computed value to ``target`` (requires ``operation``).
        - ``"calc"`` — calculate and assign a derived value (requires ``operation``).
        - ``"reload_options"`` — hint to clients to refresh the options list of
          ``target`` (async hint; evaluation timing is renderer-specific).
        - ``"show"`` / ``"hide"`` — control visibility of ``target``.
        - ``"require"`` — make ``target`` required.
        - ``"cascade_clear"`` — clear the value of ``target``.
    conditions: Optional gating conditions evaluated against the *owning*
        field's value (and context). If ``None``, the effect always applies.
    logic: How ``conditions`` are combined (same semantics as
        :attr:`DependencyRule.logic`). Default ``"and"``.
    operation: Required when ``effect`` is ``"set"`` or ``"calc"``.
