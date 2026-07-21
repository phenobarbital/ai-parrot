---
type: Wiki Summary
title: parrot.auth.rls_registry
id: mod:parrot.auth.rls_registry
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Row-Level Security (RLS) Registry for FEAT-228 Data-Plane Authorization.
relates_to:
- concept: class:parrot.auth.rls_registry.RlsPredicate
  rel: defines
- concept: class:parrot.auth.rls_registry.RlsRegistry
  rel: defines
- concept: class:parrot.auth.rls_registry.RlsRule
  rel: defines
- concept: mod:parrot.auth.permission
  rel: references
---

# `parrot.auth.rls_registry`

Row-Level Security (RLS) Registry for FEAT-228 Data-Plane Authorization.

Maps ``(driver, table)`` pairs to predicate templates with subject-attribute
placeholders.  At query time the registry renders a :class:`RlsPredicate` that
the injection layer (:mod:`parrot.tools.dataset_manager.sources.rls`) injects
into the outbound query.

Design constraints (see spec §2 and §4):
- Predicates are *never* string-interpolated.  Values are always returned as
  bound parameters (``bound_params`` dict) for the driver to bind safely.
- Empty attribute lists (e.g. no programs on the subject) produce a deny-all
  predicate (``1=0``) rather than an open predicate.
- The registry is in-memory and loaded from config at startup (config loading
  is outside this module's responsibility).

Usage::

    from parrot.auth.rls_registry import RlsRegistry, RlsRule, RlsPredicate

    registry = RlsRegistry()
    registry.register(RlsRule(
        driver="pg",
        table="sales.orders",
        predicate_template="region IN (:subject.programs)",
        subject_attribute="programs",
        description="Regional managers see only their region",
    ))

    # At query time:
    predicates = registry.lookup("pg", {"pg:sales.orders"})
    rendered = registry.render(predicates[0], pctx)

## Classes

- **`RlsRule(BaseModel)`** — Registry entry: template predicate keyed by ``(driver, table)``.
- **`RlsPredicate(BaseModel)`** — A rendered RLS predicate ready for injection.
- **`RlsRegistry`** — In-memory registry mapping ``(driver, table)`` to predicate templates.
