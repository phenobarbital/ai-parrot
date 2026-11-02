---
id: F019
query_id: Q036
type: git_log
intent: "Recent history of sdd_coder - how fast the execution boundary is changing under a new ingestor."
executed_at: 2026-10-30T22:39:00Z
duration_ms: 850
parent_id: null
depth: 0
lane: git
merged_from: ['FG-002']
---

# F019 — sdd_coder: engine.py is the hottest file in the repo; a usage ingestor lands on moving ground

## Summary

30+ commits in 90 days, and `engine.py` is touched by most of them — including
one **today** (3c96b4002c, 2026-10-30). The dominant themes are the FEAT-709
task-tier validation gate (TASK-4520→4542, merged PR #1751 on 2026-10-21),
per-seat effort resolution (two HOTFIX briefs, 2026-10-27/28), brief-task-id
admission (TASK-4673/4674), and stdin isolation (HOTFIX-995ad869e502-1). The
practical consequence for FEAT-783: **the `coder_begin_execution` /
`coder_end_execution` boundary in `engine.py` is the single most contended file
in the dev-loop package**, so a usage ingestor added there will rebase-conflict
with whatever hotfix is in flight. `models.py` and `optimization_models.py` are
almost as hot. The quieter seams are `telemetry.py` and `roster.py`, neither of
which appears in any commit in the window — evidence that the existing
telemetry sink is stable and a safer attachment point than the engine.

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`
  symbol: `coder_begin_execution / coder_end_execution host`
  excerpt: |
    3c96b4002c|2026-10-30|feat(sdd-coder-engine-fixes-3): TASK-4936 — task-tier gate: declared tests
                           use the override marker; pytest exit 5 is no_tests, not failed  -> engine.py
    4920dd9ef8|2026-10-28|fix(sdd-coder): apply RosterSeat.effort to native seats
                           -> effort.py, engine.py, models.py
    21b5d3e26d|2026-10-27|feat(sdd-coder): HOTFIX-sdd-coder-seat-effort-2 -> effort.py, engine.py

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py`
  symbol: `execution / attempt models`
  excerpt: |
    74bbb816fd|2026-10-27|HOTFIX-sdd-coder-seat-effort-1 — effort fields + codex reasoning_effort
                           -> complexity_models.py, models.py
    e9dd83cd04|2026-10-24|TASK-4673 — models.py accepts brief task ids and tier='task'
    085865d1c3|2026-10-23|fix(sdd_coder): admit brief task ids and tier='task'
                           -> background.py, complexity.py, complexity_models.py, models.py, optimization_models.py

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/`
  symbol: `FEAT-709 language-agnostic-validation-runners`
  excerpt: |
    41a64a58d9|2026-10-21|Merge pull request #1751 from phenobarbital/feat-FEAT-709-language-agnostic-validation-runners
    da1ed31771|2026-10-21|TASK-4542 — retire the dead escalation-ledger writes
    57744323d0|2026-10-20|TASK-4540 — the task-tier gate fails closed
    9104cc6a70|2026-10-20|TASK-4532 — engine task-tier gate and same-seat repair
    873599f1ec|2026-10-20|TASK-4531 — verdict models, validation_failed outcome

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py`
  symbol: `MCP spawn sites`
  excerpt: |
    911b157fd4|2026-10-28|fix(sdd-coder-stdin-isolation): HOTFIX-995ad869e502-1 — isolate stdin at
                           every MCP-served spawn site

## Notes

`telemetry.py`, `roster.py` and `evidence.py` have **no commits** in the 90-day
window, in contrast to `engine.py`/`models.py`. TASK-4542's subject —
"retire the dead escalation-ledger writes" — is a warning worth carrying into
the proposal: a previous dev-loop→ledger write path was built and then removed
as dead.

[cross-lane: type=read, intent=read sdd_coder/telemetry.py in full — it is untouched for 90 days yet named after exactly this concern]
[cross-lane: type=grep, intent=find what TASK-4542 "dead escalation-ledger writes" removed, to avoid rebuilding a path already judged dead]
