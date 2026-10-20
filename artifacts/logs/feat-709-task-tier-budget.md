# FEAT-709 Task-tier Gate Budget Evidence

**Generated**: 2026-10-20 (orchestrator, replacing the coder's placeholder)
**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate

## Budget

`.parrot/test_runners.toml`: pytest `timeout_s = 60`.

## Integration test

`packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_task_tier_end_to_end.py::test_task_tier_end_to_end_pytest`
runs in the feature worktree: 1 passed, call time ~0.4 s (red gate on attempt 1, same-seat repair seeded from the red
branch, green gate, merged).

## Wall clock of FEAT-699 task validation commands (this worktree, process wall time incl. interpreter start)

| Task | Command target | Tests | Wall clock (s) | Under 60 s budget |
|------|----------------|-------|----------------|-------------------|
| TASK-4445 | test_scope/test_select_contract_mode.py | 4 | 3.69 | yes |
| TASK-4447 | test_scope/test_green_cache.py | 16 | 4.21 | yes |
| TASK-4451 | not measured (validation commands not recoverable from its note) | — | — | — |

## Caveats

- This measures the tasks' pytest validation commands directly on the current worktree, not a replay of the engine
  task-tier gate against each historical merge commit.
- No budget change is proposed.
