# FEAT-709 Task-tier Gate Budget Evidence

**Generated**: 2026-10-20
**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate

## Context

This file records the task-tier gate wall clock measurements for FEAT-699 tasks replayed against their merge commits, as required by spec §5 criterion: "the task-tier gate on a FEAT-699 replay stays under the pytest budget in `.parrot/test_runners.toml`".

## Pytest Budget

From `.parrot/test_runners.toml`:
- **pytest timeout**: 60 seconds

## Measurement Results

| Task | Runner | Tests | Duration (s) | Under Budget? |
|------|--------|-------|--------------|---------------|
| TASK-4445 | pytest | — | — | — |
| TASK-4447 | pytest | — | — | — |
| TASK-4451 | pytest | — | — | — |

## Notes

**Measurement not completed**: The worktree environment lacks compiled Cython modules (`parrot.utils.types` is a `.pyx` file that requires compilation). The integration test `test_task_tier_end_to_end.py` was created but could not be executed in this environment.

To complete the measurement:
1. Run the test in an environment with compiled Cython modules
2. Replay TASK-4445, TASK-4447, TASK-4451 against their merge commits
3. Record the wall-clock time for each task-tier gate run
4. Update this table with actual measurements

## Proposed Budget (if measurements exceed current)

If any measurement exceeds 60s, propose the new value here:
- (pending measurement)

## Validation Commands Reference

From the completed FEAT-699 tasks:
- TASK-4445: `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select_contract_mode.py -q`
- TASK-4447: `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_green_cache.py -q`
- TASK-4451: (see TASK-4451 completion note for validation commands)