---
type: Wiki Summary
title: parrot.auth.dataplane_guard
id: mod:parrot.auth.dataplane_guard
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: DataPlanePolicyGuard for FEAT-228 Data-Plane Authorization.
relates_to:
- concept: class:parrot.auth.dataplane_guard.DataPlanePolicyGuard
  rel: defines
- concept: mod:parrot.auth.exceptions
  rel: references
- concept: mod:parrot.auth.permission
  rel: references
- concept: mod:parrot.auth.rls_registry
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.resolver
  rel: references
---

# `parrot.auth.dataplane_guard`

DataPlanePolicyGuard for FEAT-228 Data-Plane Authorization.

A sibling of :class:`~parrot.auth.dataset_guard.DatasetPolicyGuard` that
evaluates **physical-resource** PBAC policies: ``driver:connect``,
``table:read``, and ``source:read`` actions against the shared
``PolicyEvaluator``.

Architecture mirrors ``DatasetPolicyGuard`` exactly:
- Same lazy-import pattern for ``navigator-auth`` types (fail-open on
  ``ImportError``).
- Same ``to_eval_context`` bridge from ``PermissionContext`` to
  ``EvalContext``.
- Same WARNING-on-deny log format for operator visibility.
- Fail-open when no ``PermissionContext`` is available (FEAT-151 parity).
- Fail-closed on evaluator errors for guarded resources.

Resource naming (Spec §2):
    ``driver:<driver>``                  action: ``driver:connect``
    ``table:<driver>:<schema>.<table>``  action: ``table:read``
    ``source:<type>:<identifier>``       action: ``source:read``

Usage::

    guard = DataPlanePolicyGuard(
        evaluator=evaluator,
        rls_registry=registry,
        sensitive_drivers=frozenset({"bigquery_finance"}),
    )
    await guard.authorize_source(ctx, resources)  # raises AuthorizationRequired on denial

## Classes

- **`DataPlanePolicyGuard`** — Data-plane authorization guard for driver / table / source resources.
