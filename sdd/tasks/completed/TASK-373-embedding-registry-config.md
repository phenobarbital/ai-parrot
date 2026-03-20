# TASK-373: Add EMBEDDING_REGISTRY_MAX_MODELS Configuration

**Feature**: first-time-caching-embedding-model
**Feature ID**: FEAT-054
**Spec**: `sdd/specs/first-time-caching-embedding-model.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> The EmbeddingRegistry needs a configurable `max_models` threshold for LRU eviction.
> This task adds the configuration constant before the registry is built.
> Implements Spec Module 2.

---

## Scope

- Add `EMBEDDING_REGISTRY_MAX_MODELS` setting to `parrot/conf.py`
- Default value: `10`
- Should be overridable via environment variable

**NOT in scope**: The registry itself (TASK-374), any consumer refactoring.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/conf.py` | MODIFY | Add `EMBEDDING_REGISTRY_MAX_MODELS` setting |

---

## Implementation Notes

### Pattern to Follow
Follow the existing pattern in `parrot/conf.py` for environment-variable-backed settings:
```python
EMBEDDING_REGISTRY_MAX_MODELS = int(os.getenv('EMBEDDING_REGISTRY_MAX_MODELS', '10'))
```

### Key Constraints
- Must be an integer
- Default: 10
- Place near other embedding-related constants (`EMBEDDING_DEFAULT_MODEL`, `EMBEDDING_DEVICE`, etc.)

### References in Codebase
- `parrot/conf.py` — existing `EMBEDDING_DEFAULT_MODEL`, `EMBEDDING_DEVICE` patterns

---

## Acceptance Criteria

- [ ] `EMBEDDING_REGISTRY_MAX_MODELS` exists in `parrot/conf.py` with default `10`
- [ ] Overridable via environment variable
- [ ] Import works: `from parrot.conf import EMBEDDING_REGISTRY_MAX_MODELS`

---

## Test Specification

```python
# Minimal verification — no separate test file needed for a constant
from parrot.conf import EMBEDDING_REGISTRY_MAX_MODELS

def test_embedding_registry_max_models_default():
    """Config constant exists with correct default."""
    assert isinstance(EMBEDDING_REGISTRY_MAX_MODELS, int)
    assert EMBEDDING_REGISTRY_MAX_MODELS == 10
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-373-embedding-registry-config.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-03-20
**Notes**: Added `EMBEDDING_REGISTRY_MAX_MODELS = int(os.getenv('EMBEDDING_REGISTRY_MAX_MODELS', '10'))` to `parrot/conf.py` near the other embedding-related settings.

**Deviations from spec**: none
