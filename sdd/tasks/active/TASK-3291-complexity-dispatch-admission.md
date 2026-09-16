# TASK-3291: Enforce complexity restrictions at every actual coder attempt

**Feature**: FEAT-561 - Deterministic complexity routing for SDD tasks
**Spec**: `sdd/specs/complex-sdd-tasks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3290
**Assigned-to**: unassigned

## Context

Implements FEAT-561 §2–§4; feature acceptance coverage: AC7, AC8, AC10, AC11, AC14.
Measured evidence must determine routing before dispatch. This task owns the
bounded deliverable below; decisions are fixed by the approved spec and this packet.

## Scope

- Use the planning assessment at run_chunk, every MCP attempt/retry and native preparation, before allocating worktrees or invoking a coder.
- Bind attempt/native telemetry to assessment IDs; preserve configured and actually reported model identities and existing feedback attribution.

**NOT in scope**: unrelated refactors, provider/client changes, new dependencies,
FEAT-559 suspension implementation, edits outside the file table, or changing
approved scoring thresholds through LLM judgment.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | Scoped implementation/documentation |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` | MODIFY | Focused validation |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py` | MODIFY | Focused validation |

## Codebase Contract (Anti-Hallucination)

Verified from source at `3ba22952c307435fba30704081f1af72658c568f`. Source-verified signatures below are not
claims of runtime import smoke testing. Recheck after upstream task merges.

### Verified Imports / Existing Signatures to Use

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:871` — `async def _run_attempt(self, ctx: _FeatureCtx, task: PlannedTask, seat: RosterSeat, *, attempt: int, job_id: str) -> Tuple[AttemptRecord, Optional[DevelopmentOutput], str, SubWorktreeManager, str, str]`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:1057` — `async def _run_task(self, ctx: _FeatureCtx, task: PlannedTask, seat: RosterSeat, *, job_id: str) -> TaskResult`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:512` — `async def prepare_native(self, feature: str, worktree: str, task_id: str) -> NativePrep`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:1138` — `async def run_chunk(self, feature: str, worktree: str, task_ids: List[str]) -> CoderJob`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:222` — `def record(self) -> AttemptRecord`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py:189` — `def retry_seat(self, failed_label: str, exclude: Set[str]) -> Optional[RosterSeat]`.

### Exact existing symbol IDs

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#AttemptTelemetryCollector.record` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._run_attempt` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._run_task` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.prepare_native` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.run_chunk` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py#ChunkAssigner.retry_seat` — source-verified symbol identity for the references above.

### Touched-file freshness

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:1` — existing file read; baseline SHA-256 `c6d82898a4c0ca6ad5935ddefd14a0c245b015b07e2effa8ec76a8fd94a80bb3`. Hash is freshness evidence, not a Delegation Contract.
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py:1` — existing file read; baseline SHA-256 `596554cf5c07cf763ddc255125804829c05d91038febc32fbbf71822513b0d19`. Hash is freshness evidence, not a Delegation Contract.
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py:1` — existing file read; baseline SHA-256 `64eae3b7fe46182e302c6a91b130a3d6f51fa65e25db3a2a2748d5b1fe43faae`. Hash is freshness evidence, not a Delegation Contract.

### Dependency-provided contracts

- `TASK-3290` creates/changes: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`, `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py`, `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py`. These outputs are future contracts at authoring time; verify after the dependency lands.

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
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#AttemptTelemetryCollector.record",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._run_attempt",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._run_task",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.prepare_native",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.run_chunk",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py#ChunkAssigner.retry_seat"
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

**Parallelism**: true. Depends on TASK-3290 helpers and fixtures; serializes engine.py and test_engine_plan_merge.py edits. Toolkit/prompt work consumes the final admission behavior.

## Implementation Blueprint

### Fixed interfaces and behavior

Public signatures remain unchanged. Before side effects call _assessment_for(ctx, planned) from TASK-3290 and eligible_seats with the current available subset. Never infer eligibility from the original roster when the effective/probed model differs. Check the constructed dispatch profile's model before dispatcher.dispatch: a missing or changed effective model is ineligible on restricted tasks. No implicit defaults. Exact identity mappings come only from policy.
Invoke retry_seat(..., eligible_labels=<current restricted MCP labels>) after failure, preserving its exclude set; if none exists return a visible blocked/failed result with complex_model_unavailable diagnostic, preserving previous attempts. Do not use retry_native or ask the worker to implement on an unknown model. Stale evidence ends admission with complexity_plan_stale, without retrying the same stale plan.
Set AttemptRecord.assessment_id on every real attempt, including error paths; NativePrep returns assessment_id and the exact planned effective model, never seat.model-or-haiku for restricted tasks. Retain native assessment binding until merge emits its AttemptRecord (inside engine.py). A provider-reported resolved_model outside the allowlist is a model mismatch: record it and refuse consolidation as successful delivery; it must not be relabeled as an allowed model. No provider SDK edits.
Preflight hashes apply to the feature baseline for the attempt. A preceding task merge can advance HEAD: report stale and require coder_plan, rather than recalculating silently. Already admitted running attempts keep their recorded evidence and are not canceled just because a sibling merges. Existing feedback/review IDs, error journal and merge fidelity stay intact.

### Steps (in order)

1. Apply shared admission helper in run_chunk and before native/MCP worktree allocation.
2. Validate effective profile model and set assessment attribution on all paths.
3. Gate retry selection with current eligibility and preserve diagnostics.
4. Add negative tests proving forbidden dispatcher/worktree functions are never called.

Blueprints are implementation instructions, not stub source files. Implement the
complete behavior and edge cases; do not leave placeholders in executable code.

## Acceptance Criteria

- [ ] Weak probe fallbacks, weak retries, empty models and implicit aliases never dispatch a restricted task.
- [ ] Native preparation returns the exact eligible model and assessment ID before the worker constructs its Agent call.
- [ ] Stale or tampered assessments allocate no new worktree and invoke no coder.
- [ ] Every attempted delivery and retry retains assessment attribution, including failures and native merge.
- [ ] Reported unexpected resolved models cannot be consolidated as an allowed successful delivery.

## Test Specification

- Extend fake dispatcher builder to carry the explicitly requested model; never hide a missing profile model by disabling validation.
- Tests: weak/strong retry ladder, blocked native model, profile mismatch, stale attempt, native merge attribution, concurrent admitted sibling completing after HEAD advances.
- Run pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py -q.

Store command output in `artifacts/logs/TASK-3291-complexity.log`. Use the activated
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

Not started. On completion record files changed, acceptance evidence, tests,
commit SHA, remaining limitations and actual model/attempt/assessment attribution.
