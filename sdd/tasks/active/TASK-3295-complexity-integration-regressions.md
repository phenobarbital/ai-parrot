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

Not started. On completion record files changed, acceptance evidence, tests,
commit SHA, remaining limitations and actual model/attempt/assessment attribution.
