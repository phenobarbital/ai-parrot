# TASK-164: Hook Memo Persistence After Deliberation

**Feature**: Investment Memo Persistency (FEAT-024)
**Spec**: `sdd/specs/finance-investment-memo-persistency.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1h)
**Depends-on**: TASK-163
**Assigned-to**: claude-session
**Completed**: 2026-03-05

---

## Context

> Fire-and-forget persistence of InvestmentMemo after deliberation.
> Should not block the execution pipeline.

---

## Scope

- Add `_persist_memo()` helper method to `ExecutionOrchestrator`
- Call via `asyncio.create_task()` after memo generation (fire-and-forget)
- Log errors but don't raise (non-blocking)
- Add logger for persistence operations

**NOT in scope**: Event logging (TASK-165).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/execution.py` | MODIFY | Add persistence hook |

---

## Implementation Notes

### Persistence Hook

```python
class ExecutionOrchestrator:
    async def run_pipeline(self, ...):
        # ... existing deliberation code ...
        memo = await committee.run_deliberation(...)

        # Fire-and-forget persistence
        if self.memo_store:
            asyncio.create_task(self._persist_memo(memo))

        # Continue with order processing immediately
        orders = memo_to_orders(memo)
        ...

    async def _persist_memo(self, memo: InvestmentMemo) -> None:
        """
        Fire-and-forget memo persistence.

        Errors are logged but not raised to avoid blocking pipeline.
        """
        try:
            await self.memo_store.store(memo)
            self.logger.debug(f"Memo {memo.id} persisted successfully")
        except Exception as e:
            self.logger.error(f"Failed to persist memo {memo.id}: {e}")
```

### Fire-and-Forget Pattern

The key is using `asyncio.create_task()` without awaiting:
- Pipeline continues immediately
- Persistence happens in background
- Errors logged but don't crash pipeline

---

## Acceptance Criteria

- [x] Memo persisted after deliberation completes
- [x] Pipeline does NOT wait for persistence (fire-and-forget)
- [x] Persistence errors logged but don't raise
- [x] Debug log on successful persistence
- [x] Error log on failed persistence
- [x] Persistence skipped if `memo_store` is None

---

## Completion Note

**Completed**: 2026-03-05
**Implemented by**: claude-session

### Summary

Added `_persist_memo()` method to `ExecutionOrchestrator` in `parrot/finance/execution.py`.
Fire-and-forget call added in `run_trading_pipeline()` after orchestrator creation:
- `asyncio.create_task(orchestrator._persist_memo(memo))` when `memo_store` is set
- Errors caught and logged, never re-raised
- Debug log on success, error log on failure

Also added `InvestmentMemo` and `MemoEventType` to imports.
