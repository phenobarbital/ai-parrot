# TASK-181: Portfolio Manager Platform Update

**Feature**: Multi-Executor Integration (FEAT-026)
**Spec**: `sdd/specs/finance-multi-executor-integration.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-177
**Assigned-to**: claude-session

---

## Context

> Add `Platform.IBKR` to Portfolio Manager's platform list in the monitoring
> agent definition so the PM can reason about all four platforms.

---

## Scope

- Add `Platform.IBKR` to the PM's `platforms` list in `parrot/finance/agents/monitoring.py`
- Verify PM agent declaration includes `platforms=[Alpaca, Binance, Kraken, IBKR]`

**NOT in scope**: Tool wiring (callers must pass ibkr tools via `monitor_tools`), schema changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/agents/monitoring.py` | MODIFY | Add Platform.IBKR to PM platforms |

---

## Implementation Notes

- The PM already declares `platforms=[Alpaca, Binance, Kraken]`
- Simply add `Platform.IBKR` to the list
- No logic changes needed — the PM receives tools externally via `monitor_tools`

---

## Acceptance Criteria

- [x] `create_portfolio_manager_profile().platforms` includes `Platform.IBKR`
- [x] PM platform list is `[Alpaca, Binance, Kraken, IBKR]`
- [x] Ruff check passes
- [x] Import verify: platforms confirmed as `[alpaca, binance, kraken, ibkr]`

---

## Completion Note

Added `Platform.IBKR` to the `platforms` list in `create_portfolio_manager()` in
`parrot/finance/agents/monitoring.py` (line 35). `create_portfolio_manager_profile()` in
schemas.py already had IBKR. Both verified via import. Ruff clean.

---

## Agent Instructions

1. Open `parrot/finance/agents/monitoring.py`
2. Find PM platform list and add `Platform.IBKR`
3. Run `ruff check parrot/finance/agents/monitoring.py`
4. Run import verify command
