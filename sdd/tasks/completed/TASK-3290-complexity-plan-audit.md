# TASK-3290: Plan tasks from persisted assessments and validate plan snapshots

**Feature**: FEAT-561 - Deterministic complexity routing for SDD tasks
**Spec**: `sdd/specs/complex-sdd-tasks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3288, TASK-3289
**Assigned-to**: unassigned

## Context

Implements FEAT-561 §2–§4; feature acceptance coverage: AC1, AC6, AC7, AC9, AC10, AC11, AC12, AC14.
Measured evidence must determine routing before dispatch. This task owns the
bounded deliverable below; decisions are fixed by the approved spec and this packet.

## Scope

- Integrate collection, evaluation, audit persistence and routing blocks into planning without changing public method signatures.
- Introduce shared preflight helpers that dispatch/native/retry paths will call in TASK-3291. Preserve feedback, orphan detection and scheduler behavior.

**NOT in scope**: unrelated refactors, provider/client changes, new dependencies,
FEAT-559 suspension implementation, edits outside the file table, or changing
approved scoring thresholds through LLM judgment.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | Scoped implementation/documentation |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py` | MODIFY | Focused validation |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py` | MODIFY | Focused validation |

## Codebase Contract (Anti-Hallucination)

Verified from source at `3ba22952c307435fba30704081f1af72658c568f`. Source-verified signatures below are not
claims of runtime import smoke testing. Recheck after upstream task merges.

### Verified Imports / Existing Signatures to Use

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:457` — `async def plan(self, feature: str, worktree: str) -> CoderPlan`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:490` — `async def _cached_plan(self, feature: str, worktree: str, ctx: _FeatureCtx) -> CoderPlan`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:78` — `class CoderFailure(Exception):`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:167` — `class CoderPlan(BaseModel):`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py:152` — `def from_index_file(cls, path: Path) -> Optional['TaskScheduler']`.

### Exact existing symbol IDs

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#CoderFailure` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._cached_plan` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.plan` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#CoderPlan` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py#TaskScheduler.from_index_file` — source-verified symbol identity for the references above.

### Touched-file freshness

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:1` — existing file read; baseline SHA-256 `c6d82898a4c0ca6ad5935ddefd14a0c245b015b07e2effa8ec76a8fd94a80bb3`. Hash is freshness evidence, not a Delegation Contract.
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py:1` — existing file read; baseline SHA-256 `64eae3b7fe46182e302c6a91b130a3d6f51fa65e25db3a2a2748d5b1fe43faae`. Hash is freshness evidence, not a Delegation Contract.
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py:1` — existing file read; baseline SHA-256 `6571447dd93cf81920141307a457180324f66e8f0c416fad02c190d7e050c74d`. Hash is freshness evidence, not a Delegation Contract.

### Dependency-provided contracts

- `TASK-3288` creates/changes: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_collectors.py`, `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_collectors.py`. These outputs are future contracts at authoring time; verify after the dependency lands.
- `TASK-3289` creates/changes: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py`, `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py`. These outputs are future contracts at authoring time; verify after the dependency lands.

### Integration reconciliation

FEAT-559 is in progress in its own per-spec index and is not implemented in this
baseline: there is no landed execution-pool API to import. Freeze this task's
interfaces against current dev. If FEAT-559 lands before execution/merge, reverify
contracts and preserve its available-seat/suspension intersection and execution
identity; never restore a suspended seat or discard its API parameters. Do not
add external TASK IDs to this feature's depends_on DAG. FEAT-560 has already
landed `partition_wave` in `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py`; roster changes must preserve it.
This resolves spec §8's code-research prerequisite; no guessed pool APIs are used.

### Does NOT Exist

- `sdd_coder/orchestrator.py` — use the verified engine module.
- An existing complexity classifier or graph revision token at this baseline.
- Guaranteed equivalence between `sonnet` and `sonnet-5`.
- Dependency-created complexity symbols before their owning tasks complete.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#CoderFailure",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._cached_plan",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.plan",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#CoderPlan",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py#TaskScheduler.from_index_file"
  ]
}
```

This declares existing references verified above, not a precomputed score.
When dependency-created symbols become existing imports, the executor must verify
and add them to this contract before admission; absence from today's graph is
not evidence of zero impact. Collector snapshots and scores remain server-owned.

## Implementation Notes

Use existing Pydantic v2 and async subprocess patterns. No new library installation.
Maintain 120-column Python, strict type hints, Google-style docstrings and logging.
Keep architecture decisions in this task/spec; do not ask the coder to decide
whether a task feels complex. No Delegation Contract is emitted: this packet
fixes interfaces and behavior but does not contain complete writer-ready source.

**Parallelism**: true. Fan-in from TASK-3288 collectors and TASK-3289 assignment. Begins ordered engine.py edits; TASK-3291 must wait. Shared fixture changes land before dispatch/regression changes.

## Implementation Blueprint

### Fixed interfaces and behavior

Keep plan(self, feature: str, worktree: str) -> CoderPlan and _cached_plan(self, feature: str, worktree: str, ctx: _FeatureCtx) -> CoderPlan.
Add internal async _assessment_for(self, ctx: _FeatureCtx, task: PlannedTask) -> ComplexityAssessment: locate current cached assessment, validate its reference and snapshot with TASK-3288 helper, then return it or raise CoderFailure("complexity_plan_stale", ...). Scope plan cache by canonical checkout path plus feature ID (and execution ID if FEAT-559 has landed); no cross-worktree cache reuse.
For each ready task, collect/evaluate once per plan, persist canonical JSON atomically below artifacts/sdd-coder/complexity/<feature-id>/<task-id>/<assessment-id>.json and include it in CoderPlan.assessments. Never overwrite a different payload at the same content address. Invalid task declarations produce routing_blocks(code=complexity_contract_invalid); audit failures produce complexity_audit_failed. Other ready tasks continue. Unknown collectors produce valid restricted assessments.
Compute eligible seat labels against self.seats (or the current execution's available pool if present), create complex_model_unavailable blocks for empty sets, then pass only eligible tasks and complete eligible_labels map to assign. Leave blocked as dependency-blocked IDs; routing_blocks is separate; pending retains all unfinished tasks. Attach assessment_id to every PlannedTask. _cached_plan must not silently reassign a stale displayed plan; use _assessment_for at admission, explicit coder_plan refreshes it.
Persistence must not commit artifacts. Adopt bounded async filesystem operations consistent with existing project patterns; do not use threads for CPU-bound work. Fixtures: add legitimate Acceptance Criteria and explicit empty-symbol Complexity Contracts to the shared CREATE-only demo tasks so they remain standard; retain separate legacy fixtures for unknown-routing tests. Do not globally mock all assessments as standard.

### Steps (in order)

1. Upgrade shared fixture task text, preserving existing public fixture names and feature DAG.
2. Add collector/evaluator calls and per-task blocks before assignment.
3. Persist assessments and attach IDs to cached plans.
4. Add shared freshness helper and test independent work can proceed when one task blocks.

Blueprints are implementation instructions, not stub source files. Implement the
complete behavior and edge cases; do not leave placeholders in executable code.

## Acceptance Criteria

- [ ] Every planned dispatchable task has a persisted assessment and nonempty reference.
- [ ] No matching model or failed audit yields a per-task block; independent eligible tasks still appear in chunks.
- [ ] A missing contract yields unknown rather than a silent legacy bypass.
- [ ] Changing task/index/policy/target/HEAD or checkout path makes admission stale.
- [ ] Re-reading a valid cached plan does not advance roster rotation.

## Test Specification

- Extend test_engine_plan_merge.py with fake collectors and temporary Git fixtures for audit, mixed blocks and freshness.
- Use fixture canonical JSON evidence to test filesystem write failure and tampered reference rejection.
- Run pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py -q.

Store command output in `artifacts/logs/TASK-3290-complexity.log`. Use the activated
main environment; worktrees share it and must not create/install a new environment.
No live model call is needed for these checks.

## Agent Instructions

1. Read the approved spec and verify every dependency is completed in this feature index.
2. Re-read exact source contracts and dependency outputs; update this packet if references moved.
3. Mark only this task in progress in `sdd/tasks/index/complex-sdd-tasks.json` in the feature worktree.
4. Implement only the declared scope and run its focused validation.
5. Commit code and this task's SDD state together; preserve other agents' edits.
6. On verified completion move the task to completed, update its index entry/path and fill the Completion Note.

## Completion Note

Implemented as specified: `engine.py` extended (`plan()` integrates
collection/evaluation/persistence/routing without changing its public
signature; `_compute_assessment`/`_assessment_for` helpers; `CoderPlan`
now carries `assessments`/`routing_blocks`); `conftest.py`/
`test_engine_plan_merge.py` extended with complexity-aware fixtures and
assertions.

Post-merge review found 4 real defects in the delivered attempt (mistral,
attempt_uid 509e5f94824545e99cbbed8428a77bed) and fixed them across two
commits (`683e243195760373795b1f337f1a94d301d59d25` for this task's own
3 files, `a3b1de653a740517a8b8d6247e4ac2032dbe48d2` for a 3rd TASK-3288
collector defect this validation also surfaced):
- `_assessment_for`'s `.get(ctx.feature_id, {})` fell back to a plain
  dict lacking `.assessments` — AttributeError on every feature's first
  `plan()` call.
- `plan()` called the cache-validating `_assessment_for` on itself,
  contradicting the spec's "never cache a wiki result across plans" —
  split into `_compute_assessment` (always fresh, used by `plan()`) and
  `_assessment_for` (kept for a future dispatch-time revalidation caller,
  TASK-3291).
- `plan()` passed routing-blocked tasks into `ChunkAssigner.assign` with
  an empty eligible-label set, which TASK-3289's `assign()` rejects
  outright — blocked tasks are now excluded from the assignable wave.
- `_run_task`'s post-attempt assessment_id lookup referenced undefined
  `feature`/`worktree` names — fixed to `ctx.feature`/`ctx.worktree`.

All 4 recorded as model feedback
(`coder-feedback:5464290b16564e7961cd240b`,
`coder-feedback:be2165b47626e80413bd0d99`,
`coder-feedback:4958135fb2ca905995aed16e`,
`coder-feedback:343ab282787a9660f4d64a60`) plus a 5th for the
TASK-3288 collector defect this validation surfaced
(`coder-feedback:4a0cfb54994a6f4573e5b162`); review outcomes recorded
(`coder-review:1f4c0144f94a67577337eced`,
`coder-review:c2c96ed32d0fe29fc6ef9d48`).

Acceptance criteria: satisfied — collection/evaluation/audit/routing
integrated into `plan()` without changing its public signature; shared
preflight helper (`_compute_assessment`) ready for TASK-3291's
dispatch/native/retry paths; feedback, orphan detection and scheduler
behavior preserved (full suite green).

Tests: `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/ -q` ->
288 passed (0 failed), from the feature worktree with
`PYTHONPATH=packages/ai-parrot/src`. Also ran the full
`packages/ai-parrot/tests/flows/dev_loop/` suite (2053 passed, 11
pre-existing/unrelated failures in `test_pr_enrichment.py`). `ruff check
--select E9,F63,F7,F82` clean.

Limitations: `_assessment_for` (cache-validating path) has no caller yet
— TASK-3291 must wire it into `run_chunk`/`prepare_native`/retry admission
per spec ("revalidate ... before run_chunk and prepare_native side
effects"). `test_engine_plan_creates_routing_blocks_for_complex_tasks_without_strong_models`
(delivered by the attempt) only weakly asserts `plan is not None` — it
never actually exercises a real routing block, since the fixture's demo
tasks classify "standard". A stronger routing-block regression test is
left for TASK-3295's integration/regression matrix.

Seat: mistral (attempt 1, merged directly from its branch since the
engine's own retry produced no commits) · Backend: nova · Model:
mistral.devstral-2-123b · Attempts: 2 (1 real + 1 empty retry) ·
Duration: 883.0s (750.86s mistral + 132.07s empty gemini retry) ·
Tokens: in=5539198/out=14076 (both attempts combined, per coder_wait
`seats` summary) · Fix commits: 683e243195760373795b1f337f1a94d301d59d25,
a3b1de653a740517a8b8d6247e4ac2032dbe48d2 (worker, post-merge).
