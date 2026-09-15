# TASK-3273: Document exclusive task rounds and parallel-width sizing

**Feature**: FEAT-560 - Dev-Loop Pool Honours Exclusive Tasks
**Spec**: `sdd/specs/dev-loop-pool-exclusive-tasks.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: No dependencies: documentation derives from the approved spec and owns only dev-flow-model-plan.md. It can run with TASK-3269 and changes no executable or shared generated files.

## Context

Implement spec §3 Module 5 so operators can understand idle seats during exclusive rounds and how the planner determines capacity.

## Scope

- Extend Planner interaction with max(1, parallel_width(first_wave)), capped by development_pool_max, retaining explicit brief overrides.
- Add an Exclusive tasks section describing parallel_semantics: exclusive plus parallel: false, exclusive-first ascending-id singleton rounds, and re-planning after every round.
- Explain isolated-mode merge/refresh, identical sdd-coder dispatch semantics and unchanged legacy parallel-flag interpretation.
- Link the repository sdd-task Task graph rules and scripts/sdd/check_task_graph.py.

**NOT in scope**: Changing skills, graph checker, runtime behavior or any other documentation file.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/dev_loop/dev-flow-model-plan.md` | MODIFY | Extend planner interaction and add Exclusive tasks section |

## Codebase Contract (Anti-Hallucination)

Verified against dev on 2026-09-16. Re-read these references before implementation;
refresh this contract if a dependency changes it. Verify any additional API before use.

### Verified Imports

No Python imports are introduced by this documentation-only task.

### Existing Signatures to Use

- `docs/dev_loop/dev-flow-model-plan.md:205` — Existing ## Planner interaction section documents backend distribution.
- `.claude/commands/sdd-task.md:104` — Task graph rules define depends_on as ordering and parallel:false as exclusive under the header.
- `scripts/sdd/check_task_graph.py` — CLI accepts one or more index paths, --root and --json; reports cycles, missing dependencies and concurrent file overlap.
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/planner.py:287` — PlannerNode._resolve_pool preserves brief override precedence and sizes from wave 1 only.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py:134` — ChunkAssigner.assign already dispatches exclusive singleton chunks first.

### Does NOT Exist

- ## Exclusive tasks is not yet in dev-flow-model-plan.md; this task adds it.
- There is no respect_exclusive opt-out flag or maximum-over-all-waves pool sizing behavior.

## Implementation Notes

No dependencies: documentation derives from the approved spec and owns only dev-flow-model-plan.md. It can run with TASK-3269 and changes no executable or shared generated files.

Keep changes limited to declared files. Follow AGENTS.md; add no dependencies.
Preserve existing public signatures and use the repository logging conventions.
Read-only reference files are not additional write targets.

## Implementation Blueprint

### Steps (in order)

1. Extend the existing Planner interaction section without rewriting unrelated model-plan documentation.
2. Add a concise Exclusive tasks section with a valid JSON index example containing the exclusive header and parallel flags.
3. Describe one mixed-wave example and the merge/refresh/re-plan sequence. Clarify that the graph determines readiness and newly unblocked tasks are reconsidered each round.
4. Use relative links to ../../.claude/commands/sdd-task.md and ../../scripts/sdd/check_task_graph.py; verify both targets exist.

This blueprint fixes the scope and sequence; implement in the existing files without
replacing their unrelated contents. No Delegation Contract is supplied: the normal
implementation route owns the bounded code and test details.

## Acceptance Criteria

- [ ] AC-10: documentation explains both exclusive rounds and parallel-width pool sizing.
- [ ] Header-driven opt-in, exclusive-first order, sdd-coder consistency and legacy behavior are explicit.
- [ ] Examples and links are valid; no executable files are changed.

## Test Specification

- Read the finished section against spec §2/3/7 and verify the mixed-wave example has exclusive tasks alone.
- Resolve both relative links from docs/dev_loop and check the referenced Task graph rules heading.
- Validate any JSON example syntax and run git diff --check. No new automated tests are required.

### Validation

Run in the activated project environment and save test output under
`artifacts/logs/task-3273.log`.

```bash
git diff --check

```

## Output

1. Implement and validate only this task's declared scope.
2. Move this artifact to `sdd/tasks/completed/TASK-3273-exclusive-pool-task-documentation.md`.
3. Update this task in `sdd/tasks/index/dev-loop-pool-exclusive-tasks.json` with status, assignment/completion timestamps,
   and completed artifact path; do not use the historical monolithic index.
4. Add the completion evidence below and commit the scoped code plus SDD state.

## Completion Note

Extended `docs/dev_loop/dev-flow-model-plan.md` §Planner interaction with the
`parallel_width(first_wave)` capped-by-`development_pool_max` sizing rule
(brief overrides preserved), and added a new `## Exclusive tasks` section
covering `parallel_semantics: exclusive` + `parallel: false`, exclusive-first
ascending-id singleton rounds, re-planning after every round, a mixed-wave
JSON example, isolated-mode merge/refresh + identical sdd-coder dispatch
semantics, and unchanged legacy parallel-flag interpretation. Linked
`.claude/commands/sdd-task.md` (Task graph rules) and
`scripts/sdd/check_task_graph.py`. No executable files changed;
`git diff --check` clean.

Code review: 1 finding, fixed. The `#task-graph-rules` link fragment
targeted bold prose in `sdd-task.md:104` (inside `### 3. Plan Task
Decomposition`), not an actual heading, so the anchor never resolves.
Fixed in commit `218e324407bd286a1017e059830d25b2c7d5bb26` by removing the
fragment and naming the section in prose instead. Feedback recorded:
`coder-feedback:e5cda9c5360d19e6f8502dd0`.

Seat: mistral · Backend: nova · Model: mistral.devstral-2-123b · Attempts: 1 · Duration: 374.1s · Tokens: 169776/1936
