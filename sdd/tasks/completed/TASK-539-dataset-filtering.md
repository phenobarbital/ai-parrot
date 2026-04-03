# TASK-539: Dataset Filtering Integration

**Feature**: policy-based-access-control
**Spec**: `sdd/specs/policy-based-access-control.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-534, TASK-535, TASK-538
**Assigned-to**: unassigned

---

## Context

> Extends the PBAC filtering pattern from TASK-538 (tools) to DatasetManager entries.
> Unauthorized datasets become invisible to the agent — they cannot be queried or listed.
> Uses `ResourceType.DATASET` (added in TASK-534).
>
> Implements Spec Module 6.

---

## Scope

- In the handler where DatasetManager is configured for the agent session:
  1. Get Guardian from `request.app['security']`
  2. Call `guardian.filter_resources(resources=dataset_names, request=request,
     resource_type=ResourceType.DATASET, action="dataset:query")`
  3. Remove denied datasets from DatasetManager before agent receives it
- Follow the same pattern established in TASK-538 for tool filtering
- Handle edge case: no PBAC → all datasets visible

**NOT in scope**:
- Tool filtering (TASK-538)
- MCP filtering (TASK-540)
- Column-level or row-level dataset access control

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/agent.py` | MODIFY | Add Guardian dataset filtering where DatasetManager is configured |
| `tests/auth/test_dataset_filtering.py` | CREATE | Tests for dataset filtering |

---

## Implementation Notes

### Pattern to Follow
```python
# Same pattern as tool filtering (TASK-538):
async def _filter_datasets_for_user(self, dataset_manager):
    """Filter datasets based on PBAC policies for current user."""
    guardian = self.request.app.get('security')
    if guardian is None:
        return

    dataset_names = [ds.name for ds in dataset_manager.datasets]
    filtered = await guardian.filter_resources(
        resources=dataset_names,
        request=self.request,
        resource_type=ResourceType.DATASET,
        action="dataset:query",
    )
    if filtered.denied:
        self.logger.info(
            "PBAC filtered %d datasets for user: %s",
            len(filtered.denied), filtered.denied,
        )
        dataset_manager.remove_datasets(filtered.denied)
```

### Key Constraints
- Uses `ResourceType.DATASET` (from TASK-534 upstream changes)
- Action type: `dataset:query` (or equivalent — check spec open question)
- Same caching behavior as tool filtering (PolicyEvaluator LRU, 30s TTL)
- Must identify how DatasetManager exposes dataset names and supports removal

### References in Codebase
- `parrot/tools/dataset_manager/tool.py` — DatasetInfo, DatasetEntry
- `parrot/handlers/agent.py` — where DatasetManager is configured
- `parrot/handlers/datasets.py` — DatasetManagerHandler

---

## Acceptance Criteria

- [ ] Denied datasets removed from DatasetManager before agent receives it
- [ ] Agent cannot see or query denied datasets
- [ ] `dataset:*` policy matches all datasets
- [ ] `dataset:sales_*` pattern matches sales_2024, sales_q1, etc.
- [ ] No PBAC → all datasets visible (backward compatible)
- [ ] Tests pass: `pytest tests/auth/test_dataset_filtering.py -v`

---

## Test Specification

```python
import pytest


class TestDatasetFiltering:
    async def test_denied_datasets_invisible(self, handler, mock_request_restricted):
        """Restricted user cannot see confidential datasets."""
        dm = await handler._get_filtered_dataset_manager(mock_request_restricted)
        dataset_names = [ds.name for ds in dm.datasets]
        assert "hr_confidential" not in dataset_names
        assert "public_sales" in dataset_names

    async def test_no_pbac_all_visible(self, handler_no_pbac, mock_request):
        """Without PBAC, all datasets visible."""
        dm = await handler_no_pbac._get_filtered_dataset_manager(mock_request)
        assert len(dm.datasets) > 0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-539-dataset-filtering.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: Added _filter_datasets_for_user() to AgentTalk. Called before agent.attach_dm()
in POST handler. Uses ResourceType.DATASET with graceful skip if not in enum (pre-0.19.0).
Calls dataset_manager.remove_dataset() for denied datasets. Fails open on errors.

**Deviations from spec**: none
