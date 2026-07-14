---
type: Wiki Entity
title: DataPlanePolicyGuard
id: class:parrot.auth.dataplane_guard.DataPlanePolicyGuard
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Data-plane authorization guard for driver / table / source resources.
---

# DataPlanePolicyGuard

Defined in [`parrot.auth.dataplane_guard`](../summaries/mod:parrot.auth.dataplane_guard.md).

```python
class DataPlanePolicyGuard
```

Data-plane authorization guard for driver / table / source resources.

Sibling of :class:`~parrot.auth.dataset_guard.DatasetPolicyGuard`.
Evaluates three resource dimensions:
- ``driver`` → action ``driver:connect``
- ``table``  → action ``table:read``
- ``source`` → action ``source:read``

Failure semantics:
- ``ctx is None`` → fail-open (no enforcement; FEAT-151 parity).
- ``ImportError`` for ``navigator-auth`` → fail-open.
- Any other evaluator exception → fail-closed (DENY) + WARNING log.
- ``sensitive_drivers`` pre-check rejects non-slug sources before
  any PBAC evaluation.

Args:
    evaluator: Shared ``PolicyEvaluator`` instance (same as
        ``DatasetPolicyGuard``).
    rls_registry: :class:`~parrot.auth.rls_registry.RlsRegistry` for RLS
        predicate lookup.
    sensitive_drivers: Set of driver names that require ``QuerySlugSource``
        (slug-only enforcement mode).
    logger: Optional logger; defaults to module-level logger.

## Methods

- `def is_sensitive_driver(self, driver: str) -> bool` — Return True if this driver is classed as 'sensitive' (slug-only).
- `async def can_connect_driver(self, ctx: PermissionContext, driver: str) -> bool` — Check whether the subject may connect to the given driver.
- `async def filter_tables(self, ctx: PermissionContext, driver: str, tables: list[str]) -> set[str]` — Return the subset of tables the subject may read.
- `async def authorize_source(self, ctx: Optional[PermissionContext], resources: 'PhysicalResources') -> None` — Run the full authorization chain for a physical resource set.
- `async def rls_predicates(self, ctx: PermissionContext, resources: 'PhysicalResources') -> 'list[RlsPredicate]'` — Collect RLS predicates for the given resources from the registry.
