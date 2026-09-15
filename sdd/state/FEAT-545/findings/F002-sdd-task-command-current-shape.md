---
id: F002
query_id: Q004
type: read
intent: Current /sdd-task command: guardrails on code, per-task Codebase Contract
executed_at: 2026-09-10T01:00:00Z
duration_ms: 700
parent_id: null
depth: 0
---

# F002 — /sdd-task today: "tasks are plans, not code", but already names Haiku/Sonnet as the executor

## Summary

`/sdd-task` (292 lines) repeats the no-code guardrail (line 14) and mandates a per-task Codebase Contract (lines 96-112) whose stated rationale is exactly the source's premise: "The implementing agent (often Sonnet or Haiku) WILL hallucinate if not given explicit, verified code anchors" (line 111). Task files are rendered from `sdd/templates/task.md` (line 116, 154-159) and committed to base_branch (§5) before the worktree is created (§6). Any richer per-task guidance therefore belongs in the template + §3/§4 of this command.

## Citations

- path: `.claude/commands/sdd-task.md`
  lines: 10-15
  symbol: Guardrails
  excerpt: |
    - Only decompose specs with `status: approved`.
    - Each task must be independently implementable and testable.
    - Do NOT write implementation code — tasks are plans, not code.
    - Mark tasks that can run in parallel worktrees with `parallel: true`.

- path: `.claude/commands/sdd-task.md`
  lines: 96-112
  symbol: §3 CRITICAL — Codebase Contract per Task
  excerpt: |
    1. **Extract from the spec's Section 6 (Codebase Contract)** ...
    2. **Verify freshness**: `read` or `grep` each referenced file ...
    5. **Include the "Does NOT Exist" section** ...
    **Quality bar**: A task without a populated Codebase Contract section is incomplete.
    The implementing agent (often Sonnet or Haiku) WILL hallucinate if not given
    explicit, verified code anchors.

- path: `.claude/commands/sdd-task.md`
  lines: 114-159
  symbol: §4 Generate Tasks
  excerpt: |
    2. Read the task template at `sdd/templates/task.md`.
    3. **Reserve task IDs** ... reserve_ids.py --kind task --count <N>
    4. For each task, create `sdd/tasks/active/<id>-<slug>.md` using the template

- path: `.claude/commands/sdd-task.md`
  lines: 84-88
  symbol: §3 Plan Task Decomposition
  excerpt: |
    - One task per module, class, or distinct deliverable.
    - Aim for tasks completable in 1–4 hours each.

## Notes

Line 111 is evidence the premise of the request is already acknowledged by the pipeline; what is missing is the *mechanism* (executor-ready code + explanation), not the diagnosis.
