# TASK-178: IBKR Executor Prompt

**Feature**: Multi-Executor Integration (FEAT-026)
**Spec**: `sdd/specs/finance-multi-executor-integration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-177
**Assigned-to**: unassigned

---

## Context

> Create the `EXECUTOR_IBKR` system prompt that instructs the IBKR executor agent
> on available tools (place_limit_order, place_stop_order, place_bracket_order,
> cancel_order, get_positions, get_account_summary, request_market_data) and
> multi-asset coverage (STK, OPT, FUT).

---

## Scope

- Add `EXECUTOR_IBKR` prompt constant to `parrot/finance/prompts.py`
- Add `ibkr_executor` entry to `MODEL_RECOMMENDATIONS` dict
- Prompt follows same XML-tagged structure as `EXECUTOR_STOCK`

**NOT in scope**: Agent factory, orchestrator registration, toolkit changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/prompts.py` | MODIFY | Add EXECUTOR_IBKR prompt and MODEL_RECOMMENDATIONS entry |

---

## Implementation Notes

- Study `EXECUTOR_STOCK` and `EXECUTOR_CRYPTO` for structure
- IBKR-specific tools: `place_limit_order`, `place_stop_order`, `place_bracket_order`, `cancel_order`, `get_positions`, `get_account_summary`, `request_market_data`
- Cover sec_types: STK (stocks/ETFs), OPT (options), FUT (futures)
- Include DRY_RUN awareness (IBKR toolkit supports it)
- Safety constraints: always use limit orders, require bracket orders for new positions, etc.

---

## Acceptance Criteria

- [ ] `EXECUTOR_IBKR` prompt exists in `prompts.py`
- [ ] Prompt covers STK, OPT, FUT order types
- [ ] Prompt lists all IBKR tools with descriptions
- [ ] `ibkr_executor` entry in `MODEL_RECOMMENDATIONS`
- [ ] Ruff check passes

---

## Agent Instructions

1. Read `EXECUTOR_STOCK` and `EXECUTOR_CRYPTO` in `parrot/finance/prompts.py` for structure
2. Read `IBKRWriteToolkit` in `parrot/finance/ibkr_write.py` for tool names and parameters
3. Create `EXECUTOR_IBKR` prompt following the same XML structure
4. Add `ibkr_executor` to `MODEL_RECOMMENDATIONS`
5. Run `ruff check parrot/finance/prompts.py`
