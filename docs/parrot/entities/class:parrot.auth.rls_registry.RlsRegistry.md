---
type: Wiki Entity
title: RlsRegistry
id: class:parrot.auth.rls_registry.RlsRegistry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: In-memory registry mapping ``(driver, table)`` to predicate templates.
---

# RlsRegistry

Defined in [`parrot.auth.rls_registry`](../summaries/mod:parrot.auth.rls_registry.md).

```python
class RlsRegistry
```

In-memory registry mapping ``(driver, table)`` to predicate templates.

Rules are keyed by ``(driver, table)``.  The ``lookup`` method strips the
``driver:`` prefix from table resource strings (``"pg:sales.orders"`` →
looks up ``("pg", "sales.orders")``).

Example::

    registry = RlsRegistry()
    registry.register(RlsRule(
        driver="pg",
        table="sales.orders",
        predicate_template="region IN (:subject.programs)",
        subject_attribute="programs",
    ))
    rules = registry.lookup("pg", {"pg:sales.orders"})
    assert len(rules) == 1

## Methods

- `def register(self, rule: RlsRule) -> None` — Add a predicate template rule to the registry.
- `def lookup(self, driver: str, tables: set[str]) -> list[RlsRule]` — Return matching rules for the given driver and table resource strings.
- `def render(self, rule: RlsRule, ctx: PermissionContext) -> RlsPredicate` — Render a rule into a bound :class:`RlsPredicate`.
