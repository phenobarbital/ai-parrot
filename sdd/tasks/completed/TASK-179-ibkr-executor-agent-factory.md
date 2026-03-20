# TASK-179: IBKR Executor Agent Factory

**Feature**: Multi-Executor Integration (FEAT-026)
**Spec**: `sdd/specs/finance-multi-executor-integration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-177, TASK-178
**Assigned-to**: unassigned

---

## Context

> Create the `create_ibkr_executor()` factory function and add `ibkr` to
> `create_all_executors()`. Follows the same pattern as
> `create_crypto_executor_kraken()`.

---

## Scope

- Add `create_ibkr_executor()` function to `parrot/finance/agents/executors.py`
- Add `ibkr` key to `create_all_executors()` return dict

**NOT in scope**: Orchestrator registration, toolkit changes, prompt creation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/agents/executors.py` | MODIFY | Add create_ibkr_executor() and update create_all_executors() |

---

## Implementation Notes

- Follow `create_crypto_executor_kraken()` pattern
- Use `EXECUTOR_IBKR` prompt from TASK-178
- Use `create_ibkr_executor_profile()` from TASK-177
- Agent name: `"IBKR Executor"`, agent_id: `"ibkr_executor"`
- `use_tools=True`

---

## Acceptance Criteria

- [ ] `create_ibkr_executor()` function exists in `executors.py`
- [ ] Returns agent with correct name, agent_id, prompt, use_tools=True
- [ ] `create_all_executors()` includes `"ibkr"` key
- [ ] Import resolves: `from parrot.finance.agents.executors import create_ibkr_executor`
- [ ] Ruff check passes

---

## Agent Instructions

1. Read existing executor factories in `parrot/finance/agents/executors.py`
2. Add `create_ibkr_executor()` following `create_crypto_executor_kraken()` pattern
3. Update `create_all_executors()` to include `"ibkr"` key
4. Run `ruff check parrot/finance/agents/executors.py`
5. Run: `python -c "from parrot.finance.agents.executors import create_ibkr_executor, create_all_executors; print('OK:', list(create_all_executors().keys()))"`
