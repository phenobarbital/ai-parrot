---
type: Wiki Summary
title: parrot.auth.dataset_guard
id: mod:parrot.auth.dataset_guard
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: PBAC enforcement helper for DatasetManager.
relates_to:
- concept: class:parrot.auth.dataset_guard.DatasetPolicyGuard
  rel: defines
- concept: mod:parrot.auth.permission
  rel: references
---

# `parrot.auth.dataset_guard`

PBAC enforcement helper for DatasetManager.

This module provides ``DatasetPolicyGuard``, a wrapper around
``navigator-auth``'s ``PolicyEvaluator`` that exposes three async methods
tailored to dataset-level and column-level access control.

Architecture
------------
``DatasetPolicyGuard`` mirrors ``PBACPermissionResolver``
(``parrot/auth/resolver.py:247``) in shape and discipline:

- Same lazy-import pattern for ``navigator-auth`` types (fail-open on
  ``ImportError``).
- Same ``to_eval_context`` bridge from ``PermissionContext`` to
  ``EvalContext``.
- Same WARNING-on-deny log format for operator visibility.
- Same fail-closed semantics on any non-``ImportError`` runtime error.

It is a **sibling** of ``PBACPermissionResolver``, NOT a subclass.  Both
wrap the same ``PolicyEvaluator`` instance but expose different interfaces:

- ``PBACPermissionResolver`` → ``ResourceType.TOOL``, action ``tool:execute``
- ``DatasetPolicyGuard``      → ``ResourceType.DATASET``, actions
  ``dataset:read`` / ``dataset:column:read``

Usage example (wired at app startup after ``setup_pbac``)::

    pdp, evaluator, guardian = setup_pbac(app, policy_dir="policies")
    if evaluator is not None:
        dataset_guard = DatasetPolicyGuard(evaluator=evaluator)
        dataset_manager = DatasetManager(policy_guard=dataset_guard)

Resource naming convention
--------------------------
``DatasetPolicyGuard`` passes resource names to ``PolicyEvaluator`` using the
``"dataset:<name>"`` prefix for dataset-level checks and
``"dataset:<dataset>:<column>"`` for column-level checks.  This matches the
resource key format declared in YAML policy files::

    resources:
      - "dataset:financial_data"        # dataset:read
      - "dataset:sales:profit_margin"   # dataset:column:read

## Classes

- **`DatasetPolicyGuard`** — PBAC enforcement for DatasetManager.
