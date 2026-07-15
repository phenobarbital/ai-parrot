---
type: Wiki Entity
title: DatasetPolicyGuard
id: class:parrot.auth.dataset_guard.DatasetPolicyGuard
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: PBAC enforcement for DatasetManager.
---

# DatasetPolicyGuard

Defined in [`parrot.auth.dataset_guard`](../summaries/mod:parrot.auth.dataset_guard.md).

```python
class DatasetPolicyGuard
```

PBAC enforcement for DatasetManager.

Wraps a shared ``PolicyEvaluator`` (the same instance used by
``Guardian`` and ``PBACPermissionResolver``) with dataset-specific
resource type and actions.

Failure semantics (mirrors ``PBACPermissionResolver``):

- ``ImportError`` on ``navigator-auth`` → all methods return
  "all-allowed" (fail-open; preserves backwards compat when the SDK is
  absent).
- Any *other* exception inside a filter/check → log WARNING with
  ``user_id`` + resource name + reason; return DENY for the affected
  subset (fail-closed).
- ``PermissionContext.session`` is ``None`` or ``user_id`` is ``None``
  → DENY for every resource (fail-closed).

Backwards-compatible opt-in: ``DatasetManager`` instantiated without
a ``policy_guard`` argument performs no enforcement.  Datasets that
have no matching YAML policy remain visible to all users.

Args:
    evaluator: Shared ``PolicyEvaluator`` instance (injected by app
        bootstrap after ``setup_pbac()``).
    logger: Optional logger; defaults to
        ``logging.getLogger(__name__)``.

Example::

    guard = DatasetPolicyGuard(evaluator=evaluator)
    allowed = await guard.filter_datasets(ctx, ["sales", "finance"])
    # → {"sales"}  (if "finance" is denied for this user)

## Methods

- `async def filter_datasets(self, context: PermissionContext, dataset_names: list[str]) -> set[str]` — Return the subset of datasets the user is permitted to read.
- `async def filter_columns(self, context: PermissionContext, dataset_name: str, columns: list[str]) -> list[str]` — Return allowed columns in their original input order.
- `async def can_read_dataset(self, context: PermissionContext, dataset_name: str) -> bool` — Single-resource check — can the user read this dataset?
