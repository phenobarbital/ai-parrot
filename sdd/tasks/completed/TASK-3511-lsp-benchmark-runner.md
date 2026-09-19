# TASK-3511: Run bounded CLI pilot attempts with normalized trace collection

**Feature**: FEAT-580 - SDD LSP Research Pilot
**Spec**: `sdd/specs/sdd-research-lsp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3507, TASK-3509, TASK-3510
**Assigned-to**: unassigned

## Context

Implement M5 of the approved specification: run bounded cli pilot attempts with normalized trace collection. The reported 13% cost, 12% token and 24% call reductions are hypotheses; only the specified evaluation can establish local benefit. Read the complete spec's contracts, acceptance criteria and relevant module before implementation.

## Scope

- Implement run_pilot(manifest, output_dir) with 180 planned task attempts, counterbalanced arm order, isolated starting states and explicit arm-specific tool filtering.
- Launch only operator-provided CLI argv commands without a shell; require normalized trace JSONL output plus raw-log references from each seat.
- Collect acceptance results and failure/timeouts, retries, resource/cold/warm metrics and spending; retain unsuccessful attempts and incomplete coverage in reports.
- Stop launching further attempts on unknown cost or a budget condition; before launch reserve a manifest-defined per-attempt maximum so a single in-flight request cannot silently overspend.
- Clean up owned subprocesses and disposable worktrees, preserving diagnostic evidence and never touching unrelated worktrees.

**NOT in scope**: Choosing host/provider adapters or prices, live spending, report presentation and changing acceptance outcomes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `benchmarks/sdd_lsp/runner.py` | CREATE | Task implementation |
| `packages/ai-parrot-tools/tests/lsp/test_benchmark_runner.py` | CREATE | Acceptance and regression tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

- `from pydantic import BaseModel, ConfigDict, Field` — verified in `benchmarks/tool_optimizations/accounting.py`; use only where relevant.
- `from parrot.mcp.toolkit_server import create_toolkit_mcp_server` — verified in `packages/ai-parrot/src/parrot/mcp/toolkit_server.py`; use only where relevant.

### Existing Signatures to Use

- `UsageRecord` — `benchmarks/tool_optimizations/accounting.py:68`: existing BaseModel with stage, tokens: Optional[int], source and elapsed_ms; not sufficient for the new normalized provider record.
- `PriceRow` — `benchmarks/tool_optimizations/accounting.py:86`: existing two-rate input/output model lacks cache categories; do not silently reuse it for pilot billing.
- `cost_usd` — `benchmarks/tool_optimizations/accounting.py:133`: cost_usd(records: list[UsageRecord], model: str, prices: CostModel) -> Optional[float]; existing benchmark precedent only, not the new gate API.
- `create_toolkit_mcp_server` — `packages/ai-parrot/src/parrot/mcp/toolkit_server.py:29`: create_toolkit_mcp_server(name: str, root: Path = Path.cwd(), **overrides: Any) -> StdioMCPServer; imports under stdout redirection, constructs toolkit kwargs, filters and registers tools. Currently does not retain a resource owner.

### Dependency-produced contracts

- TASK-3507 supplies `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/lsp.yaml`, `examples/lsp-mcp.yaml`, `docs/sdd/lsp-pilot.md`. Read its completed implementation and tests before consuming its API; these are planned deliverables, not verified existing symbols.
- TASK-3509 supplies `benchmarks/sdd_lsp/__init__.py`, `benchmarks/sdd_lsp/models.py`, `benchmarks/sdd_lsp/accounting.py`. Read its completed implementation and tests before consuming its API; these are planned deliverables, not verified existing symbols.
- TASK-3510 supplies `benchmarks/sdd_lsp/tasks.yaml`, `benchmarks/sdd_lsp/fixtures/scenarios.py`, `benchmarks/sdd_lsp/fixtures/acceptance.py`. Read its completed implementation and tests before consuming its API; these are planned deliverables, not verified existing symbols.

### Does NOT Exist

- The files marked CREATE are new task deliverables; do not assume their modules or exports already exist.
- Files marked MODIFY that are created by a prerequisite must be verified after that prerequisite lands.
- No existing LSP client, persistent diagnostic baseline API or five-arm pilot harness is established by the references above.
- Do not assume generic MCP transport implements LSP framing, or AST line spans provide identifier columns.
- Verify any additional symbol before use; do not invent provider adapters or methods.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "benchmarks/sdd_lsp/runner.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/lsp/test_benchmark_runner.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:benchmarks/tool_optimizations/accounting.py#UsageRecord",
    "sym:benchmarks/tool_optimizations/accounting.py#PriceRow",
    "sym:benchmarks/tool_optimizations/accounting.py#cost_usd",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_server.py#create_toolkit_mcp_server"
  ]
}
```

## Implementation Notes

- Follow the uv workspace source layout, strict type hints and async-first resource ownership. Use stdlib and already-declared Pydantic; do not add dependencies without authorization.
- Keep changes within the target table. If implementation reveals an additional target or a conflict with project conventions, report it before expanding scope.
- May run alongside tasks outside its dependency chain with disjoint targets. Requires TASK-3507, TASK-3509, TASK-3510 for the contracts and deliverables described below.
- Activate the main repository virtual environment when using a shell in a worktree; do not create a worktree venv. Store test output in `artifacts/logs/`.
- Format touched Python with black and run ruff for touched Python files. These supplement the file-level test contract below.

## Implementation Blueprint

The following are required interfaces or artifact contracts, not claims that the symbols already exist:

- `async def run_pilot(manifest: PilotManifest, output_dir: Path) -> PilotReport`

1. Expand and validate the full matrix before launching any paid command; create deterministic attempt IDs.
2. Use async subprocesses and controlled worktrees for configured seats/checks with timeout/cancellation and normalized trace integrity checks.
3. Test the full matrix with fake CLI executables, budget reservations, missing traces, retries, failures and shutdown; never run live commands during this task.

Use complete implementations, with no placeholder methods or unfinished public tools. Test fixtures must be deterministic and independent of live providers unless explicitly opted in.

## Acceptance Criteria

- [ ] Implement run_pilot(manifest, output_dir) with 180 planned task attempts, counterbalanced arm order, isolated starting states and explicit arm-specific tool filtering.
- [ ] Launch only operator-provided CLI argv commands without a shell; require normalized trace JSONL output plus raw-log references from each seat.
- [ ] Collect acceptance results and failure/timeouts, retries, resource/cold/warm metrics and spending; retain unsuccessful attempts and incomplete coverage in reports.
- [ ] Stop launching further attempts on unknown cost or a budget condition; before launch reserve a manifest-defined per-attempt maximum so a single in-flight request cannot silently overspend.
- [ ] Clean up owned subprocesses and disposable worktrees, preserving diagnostic evidence and never touching unrelated worktrees.
- [ ] All target files are complete and file-level validation passes.
- [ ] No unrelated files or actual developer host configuration are changed.
- [ ] Failures, unavailable prerequisites and verification limitations are recorded honestly in the completion note.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/lsp/test_benchmark_runner.py -q`

## Test Specification

- `test_pilot_manifest_and_matrix`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_arm_filters_and_isolated_working_states`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_budget_unknown_cost_and_timeout_stop`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_trace_coverage_and_failed_attempts_retained`: cover the corresponding scope invariant with both successful and adversarial inputs.

## Agent Instructions

1. Read the approved spec and this task; verify prerequisites in `sdd/tasks/index/sdd-research-lsp.json`.
2. Mark only this task in-progress with assignment/start timestamp before implementing.
3. Reverify existing and dependency-produced contracts; follow the file scope and update the task first if an approved scope correction is needed.
4. Implement and run the validation above; record actual results and any external blockers.
5. Run the required SDD review, then commit only task-scoped implementation plus this task and its per-spec index state. Do not use the historical monolithic index.
6. Mark done only when every acceptance criterion is satisfied. Leave blocked external execution unfinished.

## Completion Note

Not completed. The implementing agent must record changed behavior, validation results, commit, review outcome and remaining limitations here.
