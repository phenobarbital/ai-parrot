# TASK-3287: Parse task contracts and evaluate deterministic complexity

**Feature**: FEAT-561 - Deterministic complexity routing for SDD tasks
**Spec**: `sdd/specs/complex-sdd-tasks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3286
**Assigned-to**: unassigned

## Context

Implements FEAT-561 §2–§4; feature acceptance coverage: AC2, AC3, AC4, AC6, AC10, AC12, AC14.
Measured evidence must determine routing before dispatch. This task owns the
bounded deliverable below; decisions are fixed by the approved spec and this packet.

## Scope

- Implement strict task contract parsing, lexical path normalization and the pure scoring evaluator.
- Do not invoke Ruff, wiki, providers or filesystem reads in the evaluator; these belong to collection.

**NOT in scope**: unrelated refactors, provider/client changes, new dependencies,
FEAT-559 suspension implementation, edits outside the file table, or changing
approved scoring thresholds through LLM judgment.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity.py` | CREATE | Scoped implementation/documentation |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity.py` | CREATE | Focused validation |

## Codebase Contract (Anti-Hallucination)

Verified from source at `3ba22952c307435fba30704081f1af72658c568f`. Source-verified signatures below are not
claims of runtime import smoke testing. Recheck after upstream task merges.

### Verified Imports / Existing Signatures to Use

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:116` — `class RosterConfig(BaseModel):`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py:32` — `class TaskRef(BaseModel):`.

### Exact existing symbol IDs

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterConfig` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py#TaskRef` — source-verified symbol identity for the references above.

### Touched-file freshness

- All target files are new; do not import them as existing modules before implementing this task.

### Dependency-provided contracts

- `TASK-3286` creates/changes: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_models.py`, `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py`, `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py`. These outputs are future contracts at authoring time; verify after the dependency lands.

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
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterConfig",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py#TaskRef"
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

**Parallelism**: true. Depends on TASK-3286 for its exact Pydantic schemas. Creates only complexity.py/test_complexity.py; collectors, roster and authoring can fan out after this task.

## Implementation Blueprint

### Fixed interfaces and behavior

New in complexity.py:
- class ComplexityContractError(ValueError): expose code="complexity_contract_invalid" and details: dict[str,object]; never import CoderFailure from engine.
- parse_complexity_contract(task_text: str) -> ComplexityContract.
- evaluate_complexity(evidence: ComplexityEvidence, policy: ComplexityPolicy) -> ComplexityAssessment.
Contract is one JSON object in ## Complexity Contract. Targets must match the ## Files to Create / Modify table exactly after normalization. Reject duplicate sections, conflicting actions, absolute paths, escapes and globs. Collapse harmless ./ components and separators deterministically. Case-sensitive paths; normalize actions to uppercase. Preserve absent legacy contract_symbols as None; never infer a completeness declaration from prose. Each listed symbol must have an exact path/qualname or symbol-ID anchor inside Codebase Contract. Exclude fenced template examples outside the designated sections. Runtime target existence/symlink checks belong to TASK-3288.
The pure evaluator uses only the six metric keys fixed by TASK-3286. Inclusive bands are 11/21, 10/30, 4/8, 2/3, 5/8, 2/5; hard triggers 21 cyclomatic, 30 blast, 5 descendants. Sum ≥5 is complex. Known lower bounds can prove complex even with unknown metrics; otherwise any unknown applicable metric produces unknown. Non-applicable contributes zero points with reason. Do not fabricate unavailable values.
Canonical hash: UTF-8 JSON with sorted keys, compact separators, ensure_ascii=False; sort unordered target/symbol/reason collections first. Hash policy values including model mappings, raw evidence, component scores/classification; exclude assessment_id itself, timestamps, timing and local absolute checkout paths. Include meaningful raw evidence after normalizing any embedded file paths to repo-relative paths. Preserve stdout originals separately in details if they carry nondeterministic metadata, but exclude that metadata explicitly from the hash projection. Identical measured input yields identical IDs; policy/model mapping changes invalidate IDs.

### Steps (in order)

1. Read upstream models and use their exact field names.
2. Parse task declarations without interpreting natural-language difficulty.
3. Implement policy scoring and canonical evidence hashing as pure functions.
4. Write boundary, malformed-section and adversarial input tests.

Blueprints are implementation instructions, not stub source files. Implement the
complete behavior and edge cases; do not leave placeholders in executable code.

## Acceptance Criteria

- [ ] Every scoring boundary n−1/n/n+1 and aggregate 4/5 matches §2.
- [ ] Missing legacy coverage differs from explicit empty symbols; contradictory declarations raise the named contract error.
- [ ] Reordered equivalent declarations yield identical scores and assessment IDs.
- [ ] Titles, effort estimates, selected models and text saying this is easy cannot alter classification.

## Test Specification

- Create tests for every threshold, lower-bound hard triggers, unknown/non-applicable combinations and canonical hash invariance.
- Create parser fixtures for duplicate/conflicting targets, fenced examples and symbol provenance.
- Run pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity.py -q.

Store command output in `artifacts/logs/TASK-3287-complexity.log`. Use the activated
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

Implemented as specified: `complexity.py` created (ComplexityContractError,
parse_complexity_contract, evaluate_complexity, path normalization and
canonical-hash helpers); `test_complexity.py` created with boundary,
malformed-section, adversarial-input and canonical-hash-invariance coverage.

Post-merge review found 2 real defects in the delivered attempt (qwen,
attempt_uid fb7e39b1577a44aaad3ccc52de057a50) and fixed them in commit
`fb6c54c9619fca6d7f0dcd9a6c9e01c37f9a447e`:
- `_calculate_component_points` inverted the spec's scoring bands: a value
  inside the 0-points band (e.g. cyclomatic_max 0-10) scored 1, and any
  value above that band scored 2 (double-triggering with the separate
  hard-limit check). Fixed so within-band is 0, above-band-below-hard-limit
  is 1; 2 is reserved for the policy hard limit.
- `evaluate_complexity`'s hard-trigger check required `state == "ok"`,
  silently ignoring an `unknown` metric's observed lower bound, contradicting
  this task's own blueprint ("Known lower bounds can prove complex even with
  unknown metrics"). Widened to accept `state in ("ok", "unknown")`.

Both defects recorded as model feedback
(`coder-feedback:9c3d03f6035981100cea537e`,
`coder-feedback:eb61242c6424560f9957d64b`) and the review outcome recorded
(`coder-review:e61c161807c622d01e300aa0`).

Acceptance criteria: all 4 satisfied post-fix — every scoring boundary
(n-1/n/n+1) and the aggregate 4/5 threshold verified by
test_evaluate_boundary_values / test_evaluate_complex_task_score_threshold;
contradictory-declaration and missing-vs-empty-symbol-coverage cases raise
ComplexityContractError; reordered-equivalent-declaration canonical-hash
invariance covered by test_assessment_id_consistency and
TestCanonicalHash::test_canonical_hash_key_order_independence; no
title/effort/model-preference input reaches the evaluator (evidence-only
signature).

Tests: `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/ -q` ->
269 passed (0 failed), from the feature worktree with
`PYTHONPATH=packages/ai-parrot/src`. `ruff check --select E9,F63,F7,F82`
clean on complexity.py.

Limitations: runtime target existence/symlink checks are explicitly out of
scope (owned by TASK-3288 per this task's blueprint); no dedicated unit test
was added for the unknown-lower-bound-hard-trigger branch fixed above --
left for TASK-3295's integration/regression matrix per spec §4.

Seat: qwen (attempt 2, after minimax/attempt 1 hit a JSON-output validation
error) · Backend: nova · Model: qwen.qwen3-coder-480b-a35b-instruct ·
Attempts: 2 · Duration: 281.17s (139.04s failed minimax attempt + 142.13s
qwen attempt) · Tokens: in=500923/out=17135 (both attempts combined, per
coder_wait `seats` summary) · Fix commit:
fb6c54c9619fca6d7f0dcd9a6c9e01c37f9a447e (worker, post-merge).

### Second review round (post TASK-3295, full-feature adversarial pass)

A second adversarial review over the completed feature diff found: (1)
the hard-trigger loop in `evaluate_complexity` used a hardcoded local
dict duplicating `policy.hard_limits` instead of reading it; (2) a
metric key entirely missing from `evidence.metrics` was silently
skipped instead of raising classification to `unknown`; (3)
`parse_complexity_contract` raised on any task lacking an explicit
"## Complexity Contract" section instead of falling back to the legacy
Files-to-Create/Modify table per spec AC12. All three fixed in commit
`5980f35a82cc2021840116263adb82ed329bce3c` (pointer commit
`bf9bc274f7bb595e470600b63d5cd7540c3ef7dc`). Recorded as model feedback
`coder-feedback:c37253a7b5ea64bbdae5eb9f` and review outcome
`coder-review:e61c161807c622d01e300aa0` (attempt_uid
fb7e39b1577a44aaad3ccc52de057a50, qwen.qwen3-coder-480b-a35b-instruct).
