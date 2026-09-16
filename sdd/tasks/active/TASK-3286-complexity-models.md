# TASK-3286: Typed complexity evidence, policy and response contracts

**Feature**: FEAT-561 - Deterministic complexity routing for SDD tasks
**Spec**: `sdd/specs/complex-sdd-tasks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implements FEAT-561 §2–§4; feature acceptance coverage: AC1, AC2, AC6, AC7, AC10, AC14.
Measured evidence must determine routing before dispatch. This task owns the
bounded deliverable below; decisions are fixed by the approved spec and this packet.

## Scope

- Define independent Pydantic v2 complexity models and validation; add backward-readable assessment fields and the four spec error codes to existing payloads.
- Keep policy/evidence models free of imports from engine.py or models.py to avoid an import cycle. Preserve every existing payload field and validator.

**NOT in scope**: unrelated refactors, provider/client changes, new dependencies,
FEAT-559 suspension implementation, edits outside the file table, or changing
approved scoring thresholds through LLM judgment.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_models.py` | CREATE | Scoped implementation/documentation |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | Scoped implementation/documentation |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py` | MODIFY | Focused validation |

## Codebase Contract (Anti-Hallucination)

Verified from source at `3ba22952c307435fba30704081f1af72658c568f`. Source-verified signatures below are not
claims of runtime import smoke testing. Recheck after upstream task merges.

### Verified Imports / Existing Signatures to Use

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:45` — `class RosterSeat(BaseModel):`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:116` — `class RosterConfig(BaseModel):`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:138` — `class PlannedTask(BaseModel):`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:167` — `class CoderPlan(BaseModel):`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:181` — `class AttemptRecord(BaseModel):`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:238` — `class NativePrep(BaseModel):`.

### Exact existing symbol IDs

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#AttemptRecord` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#CoderPlan` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#NativePrep` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#PlannedTask` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterConfig` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterSeat` — source-verified symbol identity for the references above.

### Touched-file freshness

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:1` — existing file read; baseline SHA-256 `3e7da69a050cbaae97258a8d54e09575713db296611fc01354ae23a7124a1ec1`. Hash is freshness evidence, not a Delegation Contract.
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py:1` — existing file read; baseline SHA-256 `61cadea3d3d0dfa1932baf81e10a0f06da69f220b2c861a5df144282be5751bc`. Hash is freshness evidence, not a Delegation Contract.

### Dependency-provided contracts

- None; use existing dependencies only.

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
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#AttemptRecord",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#CoderPlan",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#NativePrep",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#PlannedTask",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterConfig",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterSeat"
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

**Parallelism**: true. Root deliverable creates the types consumed by TASK-3287; finishes shared models.py/test_models.py edits before integration tasks.

## Implementation Blueprint

### Fixed interfaces and behavior

New in complexity_models.py (all structured values use Pydantic models, extra fields forbidden):
- MetricEvidence: state Literal["ok", "unknown", "not_applicable"], value int | None, reason str, source str. Unknown may carry an observed lower bound; unavailable is None. Non-applicable has None, not a fabricated measurement.
- ComplexityTarget: path str, action Literal["CREATE", "MODIFY"]. ComplexityContract: schema_version Literal[1], targets tuple[ComplexityTarget, ...], contract_symbols tuple[str, ...] | None. None is legacy missing coverage; an empty tuple is an explicit declaration.
- StrongModelIdentity: canonical_model str, backend str (including native), model str (exact deployed identifier). ComplexityPolicy: version str = "v1", strong_models tuple[StrongModelIdentity, ...] = (), bands dict[str, tuple[int,int]], hard_limits dict[str,int], score_threshold int = 5, timeout_seconds int = 30, max_output_bytes int = 8388608, max_concurrency int = 4. Default bands and hard_limits are exactly spec §2. Reject negative/nonascending bands, unknown metric keys, duplicate/ambiguous backend+model mappings and nonpositive bounds. No provider/model IDs hard-coded in Python; the example configuration supplies the two requested candidates.
- ComplexityEvidence: task_id str, contract ComplexityContract, metrics dict[str, MetricEvidence], head_sha str, task_sha256 str, index_sha256 str, policy_sha256 str, target_hashes dict[str,str | None], wiki_evidence_hashes dict[str,str], collector_versions dict[str,str], details dict[str, object]. Metrics keys: cyclomatic_max, blast_symbols, weighted_files, modules, acceptance_criteria, downstream_tasks. Details retain direct dependents, CREATE/MODIFY counts, impacted files, per-function values and raw collector results. A CREATE hash is None with explicit absence validation.
- ComplexityAssessment: schema_version Literal[1], policy_version str, task_id str, classification Literal["standard","complex","unknown"], total_points int, component_points dict[str,int], reason_codes tuple[str,...], evidence ComplexityEvidence, assessment_id str. Freeze models and own/copy nested values so later caller mutations cannot change persisted assessments.
- ComplexityBlock: task_id str, assessment_id str | None, code str, message str, details dict[str,object]. Invalid contracts can block before an assessment exists.
Add RosterConfig.complexity: ComplexityPolicy via default factory. Add PlannedTask.assessment_id and AttemptRecord.assessment_id as str default ""; NativePrep.assessment_id likewise. Add CoderPlan.assessments: dict[str,ComplexityAssessment] and routing_blocks: list[ComplexityBlock], empty defaults. Defaults permit old reports only; engine admission later rejects empty current assessments.
Register complexity_contract_invalid, complexity_plan_stale, complex_model_unavailable, complexity_audit_failed in ERROR_CODES.

### Steps (in order)

1. Define model validation and independent imports first.
2. Extend existing payloads additively, including NativePrep so the worker can attribute native attempts.
3. Add serialization/backward-compatibility and invalid-policy tests to test_models.py.

Blueprints are implementation instructions, not stub source files. Implement the
complete behavior and edge cases; do not leave placeholders in executable code.

## Acceptance Criteria

- [ ] All evidence states and policy defaults reproduce the approved spec without introducing a guessed model alias.
- [ ] Old plan/attempt/native payloads deserialize; new fields survive JSON round trips.
- [ ] Mutation of caller-owned input cannot change an assessment snapshot.
- [ ] Every new error code validates and unknown codes remain rejected.

## Test Specification

- Policy thresholds, missing metric values, conflicting exact model mappings and nested immutable snapshot tests.
- Run pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py -q.

Store command output in `artifacts/logs/TASK-3286-complexity.log`. Use the activated
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
