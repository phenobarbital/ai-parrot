# FEAT-709 Task-tier Gate Budget Evidence

**Generated**: 2026-10-20 (TASK-4541, replacing the direct-timing evidence)
**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Supersedes**: the earlier revision of this file, which timed the FEAT-699 tasks' pytest validation
commands directly rather than replaying the gate, and left TASK-4451 unmeasured (`issue:3edabb9b953e`).

## What is measured

A real replay of the task-tier gate: `ValidationSupervisor.start(tier="task", base_ref=…)` followed by
`wait_verdict`, exactly the pair `SddCoderEngine._task_tier_gate` calls.

Each FEAT-699 task's merge commit `C` is checked out in its own detached worktree with
`base_ref = C^`, so `diff(base_ref..HEAD)` is **that task's change alone** — the same scope production
gives the gate, where `base_ref` is the attempt branch's fork SHA from `_consolidate_diff_base`.

> An earlier attempt pointed `base_ref` at the merge commit while the worktree sat at the FEAT-709
> branch tip, 84 commits later. The gate then diffed the whole range, escalated to five pytest
> invocations across distributions and reported `timed_out` at 92–97 s. Those numbers describe a
> diff production never sees and are not reported here.

Planning runs in-process (the FEAT-709 planner plus `.parrot/test_runners.toml`, copied into each
replay worktree since the config postdates those commits); only pytest runs inside the replayed tree.

## Budgets

`.parrot/test_runners.toml`: pytest `timeout_s = 60` — **per invocation**.
`RosterConfig.runners.gate_overall_timeout_s = 600` — the whole gate.

## Results

| Task | Merge commit | Changed files | Invocations | Tests | Gate wall clock (s) | Slowest invocation (s) | Verdict |
|---|---|---|---|---|---|---|---|
| TASK-4445 | `613b206f6` | 3 | 2 (`pytest:ai-parrot`, `pytest:root`) | 68 | 44.41 | 19.77 | passed |
| TASK-4447 | `078513cd7` | 4 | 1 (`pytest:ai-parrot`) | 16 | 20.56 | 4.74 | passed |
| TASK-4451 | `3cc466f72` | 3 | 1 (`pytest:ai-parrot`) | 40 | 38.80 | 20.99 | failed (2 of 40) |

Per-invocation detail:

| Task | Suite | Tests | Passed | Failed | Duration (s) | Exit | Status |
|---|---|---|---|---|---|---|---|
| TASK-4445 | ai-parrot | 47 | 47 | 0 | 19.77 | 0 | ok |
| TASK-4445 | root | 21 | 21 | 0 | 8.84 | 0 | ok |
| TASK-4447 | ai-parrot | 16 | 16 | 0 | 4.74 | 0 | ok |
| TASK-4451 | ai-parrot | 40 | 38 | 2 | 20.99 | 1 | failed |

## Reading

- **Against the pytest `timeout_s = 60` budget**: the worst invocation observed is **20.99 s**, 35 % of
  the budget — roughly 2.9× headroom. The budget is validated, not a placeholder, and the measurements
  support keeping it at 60 s. No change is proposed (spec §8 Q4 is the user's call).
- **Against `gate_overall_timeout_s = 600`**: the worst gate is **44.41 s**, 7 % of the cap.
- **Fixed overhead** is `gate_s − Σ(invocation duration_s)`: 15.80 s, 15.82 s, 17.81 s — a consistent
  **≈ 16–18 s** of planning, Bubblewrap sandbox setup and interpreter start, independent of test count.
  It dominates small tasks: TASK-4447 spends 4.74 s running 16 tests and 15.8 s getting ready. Anyone
  tuning these budgets should treat ~18 s as the floor for any gate run, and note that a task spanning
  two distributions pays the per-invocation cost twice.

## Caveats

- TASK-4451's two failures are a property of the **replay**, not of the gate: that commit's tree runs
  against today's virtualenv, and TASK-4451 is recorded `partial` in the FEAT-699 per-spec index. The
  gate behaved correctly in turning a red run into a `failed` verdict. The failures were not
  investigated further — this run measures cost, not the health of a historical commit.
- Wall clocks are from one run each on one host; they are a budget sanity check, not a benchmark.
- `pytest` here is the sandboxed runner the supervisor spawns, so the numbers include Bubblewrap setup
  as production does.

## Reproducing

`scripts` are not committed for this one-off; the harness used is recorded in the TASK-4541 Completion
Note. The shape is: for each `(task_id, merge_commit)`, `git worktree add --detach <tmp> <commit>`,
copy `.parrot/test_runners.toml` in, then `ValidationSupervisor.start(tier="task",
base_ref=<commit>^, index_path=<tmp>/sdd/tasks/index/tests-optimization-sdd-flow.json)` +
`wait_verdict`, timing the pair. Pin `asyncio.DefaultEventLoopPolicy()` first — importing `parrot`
installs uvloop's policy, whose `get_child_watcher()` raises on 3.12 when the stdlib subprocess
transport asks for one, and the gate spawns its runners via `create_subprocess_exec`.
