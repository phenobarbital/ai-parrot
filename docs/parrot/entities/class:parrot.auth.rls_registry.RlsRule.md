---
type: Wiki Entity
title: RlsRule
id: class:parrot.auth.rls_registry.RlsRule
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'Registry entry: template predicate keyed by ``(driver, table)``.'
---

# RlsRule

Defined in [`parrot.auth.rls_registry`](../summaries/mod:parrot.auth.rls_registry.md).

```python
class RlsRule(BaseModel)
```

Registry entry: template predicate keyed by ``(driver, table)``.

Attributes:
    driver: Canonical ai-parrot driver name (output of ``normalize_driver``).
    table: Fully-qualified table name in ``schema.table`` form.
    predicate_template: SQL WHERE fragment with ``:subject.<attr>``
        placeholders, e.g. ``"region IN (:subject.programs)"``.
    subject_attribute: Name of the ``UserSession.metadata`` key whose
        values are bound as parameters, e.g. ``"programs"`` or
        ``"groups"``.
    description: Human-readable description of the rule.
