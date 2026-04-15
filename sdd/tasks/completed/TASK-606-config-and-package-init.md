# TASK-606: Config Variable & Package Init

**Feature**: vectorstore-handler-api
**Spec**: `sdd/specs/vectorstore-handler-api.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Foundation task for FEAT-087. Adds the `VECTOR_HANDLER_MAX_FILE_SIZE` config variable
> to `parrot/conf.py` and creates the `parrot/handlers/stores/` package skeleton with
> `__init__.py`. All subsequent tasks depend on this package existing.
> Implements Spec Module 1 and the package creation part of Module 6.

---

## Scope

- Add `VECTOR_HANDLER_MAX_FILE_SIZE` to `parrot/conf.py` (default `25 * 1024 * 1024` = 25MB), using `config.getint()` with fallback
- Create `parrot/handlers/stores/__init__.py` as an empty package init (exports will be added in TASK-612)

**NOT in scope**: handler implementation, helper class, route registration, exports

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Add `VECTOR_HANDLER_MAX_FILE_SIZE` variable |
| `packages/ai-parrot/src/parrot/handlers/stores/__init__.py` | CREATE | Empty package init |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# parrot/conf.py uses navconfig for configuration:
from navconfig import config  # verified: parrot/conf.py uses config.get(), config.getboolean(), etc.
```

### Existing Signatures to Use
```python
# parrot/conf.py:51-57 — existing config pattern
DBHOST = config.get('DBHOST', fallback='localhost')           # line 51
DBPORT = config.get('DBPORT', fallback=5432)                  # line 55
async_default_dsn = f'postgresql+asyncpg://...'               # line 57

# Follow the same config.get/config.getint pattern
# Add near the end of the config variables section
```

### Does NOT Exist
- ~~`parrot.conf.VECTOR_HANDLER_MAX_FILE_SIZE`~~ — does not exist yet; this task creates it
- ~~`parrot.handlers.stores`~~ — this package does not exist yet; this task creates it

---

## Implementation Notes

### Pattern to Follow
```python
# Follow existing config pattern from parrot/conf.py
# Use config.getint for numeric values with fallback
VECTOR_HANDLER_MAX_FILE_SIZE = config.getint(
    'VECTOR_HANDLER_MAX_FILE_SIZE',
    fallback=25 * 1024 * 1024  # 25MB
)
```

### Key Constraints
- Place the variable near other configuration constants (after the PLUGINS/STATIC/OUTPUT section)
- The `__init__.py` should be minimal — just a docstring, no imports yet

### References in Codebase
- `packages/ai-parrot/src/parrot/conf.py` — config patterns to follow
- `packages/ai-parrot/src/parrot/handlers/scraping/__init__.py` — example package init

---

## Acceptance Criteria

- [ ] `from parrot.conf import VECTOR_HANDLER_MAX_FILE_SIZE` works
- [ ] Default value is `26214400` (25MB)
- [ ] `parrot/handlers/stores/__init__.py` exists
- [ ] `import parrot.handlers.stores` works without error

---

## Test Specification

```python
# tests/unit/test_conf_vector_handler.py
from parrot.conf import VECTOR_HANDLER_MAX_FILE_SIZE


def test_vector_handler_max_file_size_default():
    """Config variable exists with correct default."""
    assert VECTOR_HANDLER_MAX_FILE_SIZE == 25 * 1024 * 1024


def test_vector_handler_max_file_size_is_int():
    """Config variable is an integer."""
    assert isinstance(VECTOR_HANDLER_MAX_FILE_SIZE, int)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-606-config-and-package-init.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude-sonnet)
**Date**: 2026-04-07
**Notes**: Added VECTOR_HANDLER_MAX_FILE_SIZE=26214400 (25MB) to parrot/conf.py. Created parrot/handlers/stores/__init__.py with package docstring only.

**Deviations from spec**: none
