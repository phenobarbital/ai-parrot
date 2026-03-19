# TASK-163: Add MemoStore to ExecutionOrchestrator

**Feature**: Investment Memo Persistency (FEAT-024)
**Spec**: `sdd/specs/finance-investment-memo-persistency.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1h)
**Depends-on**: TASK-159
**Assigned-to**: claude-session

---

## Context

> Inject MemoStore dependency into ExecutionOrchestrator.
> This enables memo persistence and event logging in the pipeline.

---

## Scope

- Add `memo_store: Optional[AbstractMemoStore]` parameter to `ExecutionOrchestrator.__init__()`
- Store as instance attribute
- Add factory function `get_memo_store()` for default store
- Update docstrings

**NOT in scope**: Actual persistence hooks (TASK-164, TASK-165).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/execution.py` | MODIFY | Add memo_store parameter |
| `parrot/finance/memo_store/__init__.py` | MODIFY | Add get_memo_store() factory |

---

## Acceptance Criteria

- [x] `ExecutionOrchestrator.__init__()` accepts `memo_store` parameter
- [x] `self.memo_store` attribute set correctly
- [x] Default memo store created if `MEMO_STORE_PATH` env var set
- [x] None if not configured (opt-in behavior)
- [x] `get_memo_store()` factory function exported
- [x] Existing tests still pass

---

## Completion Note

**Completed**: 2026-03-04

### Implementation Summary

1. **`parrot/finance/execution.py`**:
   - Added `from .memo_store import AbstractMemoStore` import
   - Added `memo_store: Optional[AbstractMemoStore] = None` to `__init__()` signature
   - Added full docstring for `__init__()` parameters
   - Sets `self.memo_store = memo_store if memo_store is not None else self._default_memo_store()`
   - Added `_default_memo_store()` method:
     - Reads `MEMO_STORE_PATH` env var
     - Creates `FileMemoStore(base_path=path)` if set, otherwise returns `None`
     - Logs info when memo store is enabled

2. **`parrot/finance/memo_store/__init__.py`**:
   - Added `import os`
   - Added `get_memo_store(base_path=None)` factory function:
     - Uses explicit `base_path` if provided
     - Falls back to `MEMO_STORE_PATH` env var
     - Defaults to `"investment_memos"` directory
   - Added `"get_memo_store"` to `__all__`

### Verified Behaviors
- `memo_store=None` (no env var) → `self.memo_store is None` ✓
- `MEMO_STORE_PATH` set → `self.memo_store = FileMemoStore(path)` ✓
- Explicit `memo_store=custom` → used as-is ✓
- `get_memo_store('/tmp/x')` → `FileMemoStore('/tmp/x')` ✓
- `get_memo_store()` → `FileMemoStore('investment_memos')` ✓
