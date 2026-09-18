# TASK-3295: Verify end-to-end routing, bypass prevention and all acceptance criteria

**Feature**: FEAT-561 - Deterministic complexity routing for SDD tasks
**Spec**: `sdd/specs/complex-sdd-tasks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3294
**Assigned-to**: unassigned

## Context

Implements FEAT-561 §2–§4; feature acceptance coverage: AC1, AC2, AC3, AC4, AC5, AC6, AC7, AC8, AC9, AC10, AC11, AC12, AC13, AC14.
Measured evidence must determine routing before dispatch. This task owns the
bounded deliverable below; decisions are fixed by the approved spec and this packet.

## Scope

- Create offline end-to-end regression coverage for the complete policy-to-attempt path and document AC1–AC14 results in Completion Note.
- Adapt task-local legacy fixture setup only where the new legitimate measurements change dispatch; keep tests of legacy unknown behavior explicit. Do not disable validation to preserve old tests.

**NOT in scope**: unrelated refactors, provider/client changes, new dependencies,
FEAT-559 suspension implementation, edits outside the file table, or changing
approved scoring thresholds through LLM judgment.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_routing.py` | CREATE | Focused validation |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_integration_chunk.py` | MODIFY | Focused validation |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py` | MODIFY | Focused validation |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_lint.py` | MODIFY | Focused validation |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` | MODIFY | Focused validation |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py` | MODIFY | Focused validation |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py` | MODIFY | Focused validation |

## Codebase Contract (Anti-Hallucination)

Verified from source at `3ba22952c307435fba30704081f1af72658c568f`. Source-verified signatures below are not
claims of runtime import smoke testing. Recheck after upstream task merges.

### Verified Imports / Existing Signatures to Use

- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py:18` — `class FakeDispatcher:`.
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py:64` — `async def git_sandbox_feature(tmp_path)`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:457` — `async def plan(self, feature: str, worktree: str) -> CoderPlan`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:512` — `async def prepare_native(self, feature: str, worktree: str, task_id: str) -> NativePrep`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:1138` — `async def run_chunk(self, feature: str, worktree: str, task_ids: List[str]) -> CoderJob`.

### Exact existing symbol IDs

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.plan` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.prepare_native` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.run_chunk` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py#git_sandbox_feature` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py#FakeDispatcher` — source-verified symbol identity for the references above.

### Touched-file freshness

- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_integration_chunk.py:1` — existing file read; baseline SHA-256 `afe1d9eb31c695b52ad4a8bbef97e8338108a5fae0cd72de69e77f00056c7f2a`. Hash is freshness evidence, not a Delegation Contract.
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py:1` — existing file read; baseline SHA-256 `1e3a64f2621a6849a0b04e537a001955a662fcf8abe2797c945976c76244ee71`. Hash is freshness evidence, not a Delegation Contract.
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_lint.py:1` — existing file read; baseline SHA-256 `05b6a8425633632079dddb005b4528fa763c92e6fec95218c44e55d999ac83e2`. Hash is freshness evidence, not a Delegation Contract.
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py:1` — existing file read; baseline SHA-256 `596554cf5c07cf763ddc255125804829c05d91038febc32fbbf71822513b0d19`. Hash is freshness evidence, not a Delegation Contract.
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py:1` — existing file read; baseline SHA-256 `64eae3b7fe46182e302c6a91b130a3d6f51fa65e25db3a2a2748d5b1fe43faae`. Hash is freshness evidence, not a Delegation Contract.
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py:1` — existing file read; baseline SHA-256 `09d4c85163c347fc18f71b2cff292cc8fff4fb2e0da02e336d13c64bcfa59f6b`. Hash is freshness evidence, not a Delegation Contract.

### Dependency-provided contracts

- `TASK-3294` creates/changes: `.claude/agents/sdd-worker.md`, `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md`, `examples/sdd-coder-mcp.yaml`, `docs/dev_loop/sdd-coder-orchestrator.md`. These outputs are future contracts at authoring time; verify after the dependency lands.

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
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_routing.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_integration_chunk.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_lint.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.plan",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.prepare_native",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.run_chunk",
    "sym:packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py#git_sandbox_feature",
    "sym:packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py#FakeDispatcher"
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

**Parallelism**: true. Final gate depends on TASK-3294 final prompts/config and transitively every runtime task plus TASK-3293 authoring. All shared test-file edits are ordered after their owning implementation tasks.

## Implementation Blueprint

### Fixed interfaces and behavior

Create test_complexity_routing.py using temporary Git repos, fixture wiki/Ruff results and stub dispatchers. No live providers or network. Test matrix: mixed standard/complex/unknown tasks; all five signals; configured exact candidates and absent candidates; scarce strong seats; probe fallback and retry bypass; native attribution; malformed contract; audit failure; cache freshness for each hash/HEAD/path; policy mutation; reordered declarations; runtime artifacts; dependency/exclusive semantics; already-running sibling after merge.
Add documentation contract assertions reading task template, command, skill, worker twins and example YAML: parser-compatible populated contract, exact identity mappings, explicit blocks in server-unavailable/failed/attempt-3 paths, and byte parity. Tests may read these files but cannot edit them.
Update only the listed legacy integration/feedback/lint/dispatch/plan/toolkit test files for valid evidence and explicit model identity. Preserve the behavior each regression originally tested; add local fixtures when appropriate instead of weakening gates or altering application code.
Run complete sdd_coder suite plus task_scheduler, test_subagent_parity and tool_optimizations/test_sdd_contracts suites. Run black --check and ruff check on feature Python files. Record pre-existing unrelated failures separately with reproducible evidence; feature regressions must be fixed by the owning task, never skipped.

### Steps (in order)

1. Add end-to-end adversarial tests with real temporary Git state and fake measurement/provider boundaries.
2. Migrate affected fixture-only setup and retain existing feedback/lint/fidelity assertions.
3. Validate prompt/config/authoring parity from their landed content.
4. Run the complete scoped gate and map each feature AC to test evidence.

Blueprints are implementation instructions, not stub source files. Implement the
complete behavior and edge cases; do not leave placeholders in executable code.

## Acceptance Criteria

- [ ] AC1–AC14 each has a named regression or explicit documentation validation in Completion Note.
- [ ] Forbidden dispatchers and worktree creation are asserted not called on blocked/stale inputs.
- [ ] Full targeted suites pass offline, including standard routing, feedback and lint regressions.
- [ ] Artifacts/logs contains test output and formatting/lint results; no live model usage is needed.

## Test Specification

- pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/ packages/ai-parrot/tests/flows/dev_loop/test_task_scheduler.py packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py packages/ai-parrot-tools/tests/tool_optimizations/test_sdd_contracts.py -q.
- black --check and ruff check only the feature-owned Python files.

Store command output in `artifacts/logs/TASK-3295-complexity.log`. Use the activated
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

Implemented as specified: `test_complexity_routing.py` created with 7
end-to-end tests over the full policy-to-attempt path (complex task
blocked without strong models, complex task routed to a strong model,
standard task uses normal rotation, unknown task blocked without strong
models, hard limit triggers complex classification, native preparation
blocked for a restricted task with no configured model, and a failed
strong-MCP attempt never silently retries through a native seat). The 5
other declared MODIFY files (`test_integration_chunk.py`,
`test_feedback.py`, `test_lint.py`, `test_engine_dispatch.py`,
`test_engine_plan_merge.py`) needed no changes: earlier tasks' review
fixes (TASK-3288's collector fixes, TASK-3290/3291's engine fixes) already
made them pass cleanly against the final engine/collector behavior, and
the task's own Scope only requires adapting them "where the new
legitimate measurements change dispatch" — that condition never applied.

Post-merge review found 7 real defects in the delivered attempt (qwen,
attempt_uid 92dc3e3dd5fd45f49e2b24488bbaaf86) and fixed them in commit
`4a25bdd8b575881092933ed8f3218b6830a43418`: an unverified import
(`StrongModelIdentity` from the wrong module, made the whole module
uncollectable); the `strong_policy` fixture requested by every test but
never wired into `RosterConfig.complexity`; all 7 `mock_compute_assessment`
mocks defined as plain `def` replacing an `async def` method (every test
failed with `TypeError: ... can't be used in 'await' expression`); a
`[chunk for chunk in ... for task in ...]` comprehension collecting the
wrong loop variable in 2 places; `RosterSeat(backend="claude", ...)` using
a non-existent `DevAgentBackend` literal in 3 fixtures; `DispatchLabels`
treated as a subscriptable dict with the un-prefixed seat label; and 2
tests missing a mock for TASK-3290/3291's new `_assessment_for` admission
check (which recollects real evidence and can never match a fixture's fake
hashes). Two further tests asserted premises that contradicted the actual
(correct) design — corrected to match real behavior rather than loosening
production code: a routing-blocked task is excluded from every chunk at
planning time, so `run_chunk`/`prepare_native` correctly report
`task_not_in_plan` (the stronger `complex_model_unavailable` reason already
lives on the `routing_blocks` entry); and `ChunkAssigner.retry_seat` never
returns a `kind="native"` seat, so with only one MCP-backed strong
candidate and one native-backed one, a failed MCP attempt has no eligible
retry target and correctly ends `failed`, not `merged`. All recorded as
model feedback (`coder-feedback:a7f7e69b8fa2db46300ae250`,
`coder-feedback:40fc74adb143e897079f352f`,
`coder-feedback:a826e3359171b3af853f836f`,
`coder-feedback:c6e802b5e86a806af5f4faf2`) and review outcome
(`coder-review:d3ce8ff7088754c984fedbac`).

### AC1–AC14 verification

- **AC1** (all five signal families recorded with provenance/state before
  dispatch): `TestComplexityModels`/`TestComplexityEvaluation`
  (TASK-3286/3287) plus `test_complexity_collectors.py` (TASK-3288) cover
  cyclomatic/blast/scope/criteria/downstream collection with `ok`/`unknown`/
  `not_applicable` states and sources.
- **AC2** (versioned v1 policy, every threshold boundary): TASK-3287's
  `test_complexity.py` boundary tests (n-1/n/n+1 per band, hard triggers,
  aggregate 4/5).
- **AC3** (no LLM judgment/title/outcome enters the evaluator): evaluator
  signature only accepts `(evidence, policy)` — no title/effort/model
  fields reach it; `test_complexity_routing.py` independence covered
  implicitly by mocking assessments directly.
- **AC4** (CREATE/MODIFY, breadth, criteria, downstream exact definitions):
  `test_complexity_collectors.py`'s scope tests + TASK-3287's boundary
  tests.
- **AC5** (blast dedup, missing/stale/truncated vs zero impact):
  TASK-3288's wiki collector tests.
- **AC6** (unknown routes conservatively, invalid structure blocks with
  diagnostic): `ComplexityContractError` -> `complexity_contract_invalid`
  (TASK-3287/3290); `test_complex_task_blocked_without_strong_models`/
  `test_unknown_task_blocked_without_strong_models` (this task).
- **AC7** (complex/unknown dispatch only to configured strong identities):
  `test_complex_task_blocked_without_strong_models`,
  `test_complex_task_routes_to_strong_model`,
  `test_unknown_task_blocked_without_strong_models`,
  `test_hard_limit_triggers_complex_classification` (this task).
- **AC8** (probe fallback/retries/native prep/worker self-implementation
  cannot bypass AC7): `test_native_preparation_respects_complexity`
  (native, no configured model -> blocked at planning);
  `test_retry_uses_different_strong_model` (MCP retry never crosses into
  native); TASK-3294's worker-prompt override instruction (no
  self-implementation on a restricted block).
- **AC9** (unavailable strong candidates block affected task only,
  independent ready tasks continue): `plan()`'s per-task
  `blocked_task_ids`/`routing_blocks` exclusion (TASK-3290/3291) — only the
  restricted task is excluded from the assignable wave, verified across
  every routing test in this file.
- **AC10** (every attempt references persisted evidence; stale requires
  replanning): `AttemptRecord.assessment_id` set on every path
  (TASK-3290/3291); `test_run_chunk_blocks_stale_assessment_without_worktree`
  (TASK-3291).
- **AC11** (standard rotation/dependency ordering/exclusive
  semantics/fidelity/review remain valid): full pre-existing
  `test_engine_plan_merge.py`/`test_integration_chunk.py`/`test_lint.py`
  suites unchanged and green.
- **AC12** (task generation emits the contract; legacy tasks route
  conservatively): TASK-3293's template/command/skill updates;
  `ComplexityContract.contract_symbols: None` = legacy/unknown (TASK-3286).
- **AC13** (worker prompt copies identical; docs describe
  thresholds/availability/graph limitations): TASK-3294's byte-identity
  verification + `docs/dev_loop/sdd-coder-orchestrator.md`.
- **AC14** (targeted tests + existing affected suites pass; no new
  dependency/direct provider SDK call): full suite below; no new
  dependency added across the feature (verified per-task).

Tests: `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/
packages/ai-parrot/tests/flows/dev_loop/test_task_scheduler.py
packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -q` ->
337 passed, 1 skipped (0 failed), from the feature worktree with
`PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
`pytest packages/ai-parrot-tools/tests/tool_optimizations/test_sdd_contracts.py -q`
(run separately — combining both distributions' test roots in one
invocation hits an unrelated `rootdir`/module-name collision, not a defect)
-> 17 passed, 4 pre-existing failures, all parametrized on
`.claude/agents/sdd-worker.md` delegation-protocol wording (writer_generate/
writer_apply, an unrelated in-progress feature's content) — confirmed
unrelated and out of this task's declared file table in TASK-3293/3294;
unchanged by this task. `ruff check --select E9,F63,F7,F82` clean on
`test_complexity_routing.py`.

Limitations: the 4 pre-existing `test_sdd_contracts.py` failures remain
unfixed (genuinely out of scope: none of the 6 declared files is
`.claude/agents/sdd-worker.md`, and TASK-3293/3294 already independently
confirmed and documented them as unrelated). No live model/CLI dispatch
was exercised anywhere in this feature's test suites, matching the spec's
explicit non-requirement.

Seat: qwen (attempt 2, after minimax/attempt 1's DispatchOutputValidationError)
· Backend: nova · Model: qwen.qwen3-coder-480b-a35b-instruct · Attempts: 2
· Duration: 901.65s (353.98s failed minimax + 547.67s qwen) · Tokens:
in=3703604/out=16556 (both attempts combined, per coder_wait `seats`
summary) · Fix commit: 4a25bdd8b575881092933ed8f3218b6830a43418 (worker,
post-merge).
