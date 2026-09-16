# TASK-3292: Expose complexity policy and diagnostics through the existing MCP surface

**Feature**: FEAT-561 - Deterministic complexity routing for SDD tasks
**Spec**: `sdd/specs/complex-sdd-tasks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3291
**Assigned-to**: unassigned

## Context

Implements FEAT-561 §2–§4; feature acceptance coverage: AC6, AC7, AC9, AC10, AC14.
Measured evidence must determine routing before dispatch. This task owns the
bounded deliverable below; decisions are fixed by the approved spec and this packet.

## Scope

- Pass explicit complexity configuration through both roster input forms; retain all existing MCP method names and envelopes.
- Describe assessment and routing-block semantics in tool docstrings without introducing a tool that accepts LLM difficulty scores.

**NOT in scope**: unrelated refactors, provider/client changes, new dependencies,
FEAT-559 suspension implementation, edits outside the file table, or changing
approved scoring thresholds through LLM judgment.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` | MODIFY | Scoped implementation/documentation |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py` | MODIFY | Focused validation |

## Codebase Contract (Anti-Hallucination)

Verified from source at `3ba22952c307435fba30704081f1af72658c568f`. Source-verified signatures below are not
claims of runtime import smoke testing. Recheck after upstream task merges.

### Verified Imports / Existing Signatures to Use

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:56` — `def __init__(self, *, roster: Union[List[Dict[str, Any]], RosterConfig], redis_url: Optional[str]=None, worktree_base_path: Optional[str]=None, telemetry_dir: Optional[str]=None, lint: Optional[Dict[str, Any]]=None, feedback: Optional[Dict[str, Any]]=None, **kwargs: Any) -> None`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:126` — `async def _run(self, operation: str, coro: Awaitable[BaseModel]) -> CoderResult`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:149` — `async def coder_plan(self, feature: str, worktree: str) -> CoderResult`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:298` — `class CoderResult(BaseModel):`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:116` — `class RosterConfig(BaseModel):`.

### Exact existing symbol IDs

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#CoderResult` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterConfig` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py#SddCoderToolkit.__init__` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py#SddCoderToolkit._run` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py#SddCoderToolkit.coder_plan` — source-verified symbol identity for the references above.

### Touched-file freshness

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:1` — existing file read; baseline SHA-256 `2704c533cd59209f3681eebf8bcb8c21e549c6328ff81cd4f865c27ba8b5cf54`. Hash is freshness evidence, not a Delegation Contract.
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py:1` — existing file read; baseline SHA-256 `09d4c85163c347fc18f71b2cff292cc8fff4fb2e0da02e336d13c64bcfa59f6b`. Hash is freshness evidence, not a Delegation Contract.

### Dependency-provided contracts

- `TASK-3291` creates/changes: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`, `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py`, `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py`. These outputs are future contracts at authoring time; verify after the dependency lands.

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
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#CoderResult",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterConfig",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py#SddCoderToolkit.__init__",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py#SddCoderToolkit._run",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py#SddCoderToolkit.coder_plan"
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

**Parallelism**: true. Depends on TASK-3291 final engine behavior for adapter integration tests; owns toolkit.py/test_toolkit.py only.

## Implementation Blueprint

### Fixed interfaces and behavior

Extend SddCoderToolkit.__init__ with keyword-only complexity: Optional[Dict[str,Any]] = None before **kwargs. With list roster: build RosterConfig(..., complexity=complexity or {}). With RosterConfig and complexity omitted: preserve that object's policy. With both object and explicit complexity: validate a copied config with the explicit override; do not mutate caller input or silently ignore it. Pydantic validation must run on overrides (model_copy alone does not validate).
Keep coder_plan/coder_run_chunk/coder_prepare_native signatures unchanged. Existing _run/_post_execute must serialize assessments, routing_blocks and the new error codes with standard CoderResult JSON; round-trip rather than converting typed data to repr. Per-task routing blocks remain status=ok plan data; command-level admission failures use status=error. Do not register a complexity override MCP argument or new tool. Preserve FEAT-559 execution arguments if present at integration.

### Steps (in order)

1. Validate and forward complexity config for both list and typed roster inputs.
2. Update relevant tool descriptions and maintain envelope serialization.
3. Add MCP adapter tests for blocks, stale admission and invalid policies.

Blueprints are implementation instructions, not stub source files. Implement the
complete behavior and edge cases; do not leave placeholders in executable code.

## Acceptance Criteria

- [ ] Both configuration paths deliver the same policy to the engine.
- [ ] Explicit override is validated and leaves caller-owned RosterConfig unchanged.
- [ ] Plans expose assessments/routing blocks; stale/invalid admission returns the named error rather than internal_error.
- [ ] Existing MCP tool set and strict argument validation remain intact.

## Test Specification

- Extend test_toolkit.py for constructor precedence, malformed policy and nested response JSON.
- Run pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py -q.

Store command output in `artifacts/logs/TASK-3292-complexity.log`. Use the activated
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
