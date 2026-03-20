# TASK-165: Hook Event Logging After Execution

**Feature**: Investment Memo Persistency (FEAT-024)
**Spec**: `sdd/specs/finance-investment-memo-persistency.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (1h)
**Depends-on**: TASK-163, TASK-161
**Assigned-to**: claude-session
**Completed**: 2026-03-05

---

## Context

> Log lifecycle events after order execution completes.
> Tracks EXECUTION_COMPLETED or EXECUTION_FAILED events with details.

---

## Scope

- Add event logging after execution finalization
- Log EXECUTION_COMPLETED with order stats
- Log EXECUTION_FAILED if all orders fail
- Include details: total_orders, successful, failed

**NOT in scope**: Other event types (ORDERS_GENERATED, EXPIRED).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/execution.py` | MODIFY | Add event logging hook |

---

## Implementation Notes

### Event Logging Hook

```python
class ExecutionOrchestrator:
    async def _finalize_execution(
        self,
        memo: InvestmentMemo,
        reports: list[ExecutionReport],
    ) -> None:
        """
        Finalize execution and log completion event.

        Args:
            memo: The source investment memo.
            reports: List of execution reports for all orders.
        """
        if not self.memo_store:
            return

        successful = sum(1 for r in reports if r.status == "filled")
        failed = len(reports) - successful

        event_type = (
            MemoEventType.EXECUTION_COMPLETED
            if successful > 0
            else MemoEventType.EXECUTION_FAILED
        )

        await self.memo_store.log_event(
            memo.id,
            event_type,
            {
                "total_orders": len(reports),
                "successful": successful,
                "failed": failed,
                "tickers": list(set(r.ticker for r in reports)),
            },
        )
```

### Integration Point

Call `_finalize_execution()` after all orders processed:

```python
async def run_pipeline(self, ...):
    ...
    reports = await self._execute_orders(orders)
    await self._finalize_execution(memo, reports)
    return reports
```

---

## Acceptance Criteria

- [x] EXECUTION_COMPLETED logged when any orders succeed
- [x] EXECUTION_FAILED logged when all orders fail
- [x] Event includes total_orders, successful, failed counts
- [x] Event includes list of tickers
- [x] No event logged if memo_store is None
- [x] Errors in logging don't crash pipeline

---

## Completion Note

**Completed**: 2026-03-05
**Implemented by**: claude-session

### Summary

Added `_finalize_execution()` method to `ExecutionOrchestrator` in `parrot/finance/execution.py`:
- Uses `action_taken == "executed"` (not `status == "filled"`) for successful orders
- Derives tickers from `execution_details.symbol` (deduped via set comprehension)
- `log_event()` call wrapped in try/except to prevent pipeline crash
- Called with `await` from `run_trading_pipeline()` after `process_orders()` completes
