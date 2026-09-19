# TASK-3512: Evaluate the adoption gate and expose the pilot CLI

**Feature**: FEAT-580 - SDD LSP Research Pilot
**Spec**: `sdd/specs/sdd-research-lsp.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3511
**Assigned-to**: unassigned

## Context

Implement M5 of the approved specification: evaluate the adoption gate and expose the pilot cli. The reported 13% cost, 12% token and 24% call reductions are hypotheses; only the specified evaluation can establish local benefit. Read the complete spec's contracts, acceptance criteria and relevant module before implementation.

## Scope

- Implement evaluate_gate(attempts, prices) and deterministic JSON/Markdown reports with cohort total cost divided by accepted count, charging all failed attempts/retries.
- Compare combined LSP to wiki_ast against the exact 10% cost, no acceptance/correctness regression and <=10% median wall-time criteria.
- Report per-task paired outcomes, pooled totals, medians/p95, correction cycles and cold/warm timings; unknown/incomplete/zero-success inputs cannot pass.
- Expose an offline-default CLI with explicit --live and complete manifest, calling the runner only on live opt-in; label synthetic reports so they cannot satisfy acceptance.

**NOT in scope**: Paid execution, inventing price data, alternate weaker adoption gate and modifying earlier accounting semantics.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `benchmarks/sdd_lsp/report.py` | CREATE | Task implementation |
| `benchmarks/sdd_lsp/__main__.py` | CREATE | Task implementation |
| `packages/ai-parrot-tools/tests/lsp/test_benchmark_report.py` | CREATE | Acceptance and regression tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

- `from pydantic import BaseModel, ConfigDict, Field` — verified in `benchmarks/tool_optimizations/accounting.py`; use only where relevant.

### Existing Signatures to Use

- `UsageRecord` — `benchmarks/tool_optimizations/accounting.py:68`: existing BaseModel with stage, tokens: Optional[int], source and elapsed_ms; not sufficient for the new normalized provider record.
- `PriceRow` — `benchmarks/tool_optimizations/accounting.py:86`: existing two-rate input/output model lacks cache categories; do not silently reuse it for pilot billing.
- `cost_usd` — `benchmarks/tool_optimizations/accounting.py:133`: cost_usd(records: list[UsageRecord], model: str, prices: CostModel) -> Optional[float]; existing benchmark precedent only, not the new gate API.

### Dependency-produced contracts

- TASK-3511 supplies `benchmarks/sdd_lsp/runner.py`. Read its completed implementation and tests before consuming its API; these are planned deliverables, not verified existing symbols.

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
      "path": "benchmarks/sdd_lsp/report.py",
      "action": "CREATE"
    },
    {
      "path": "benchmarks/sdd_lsp/__main__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/lsp/test_benchmark_report.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:benchmarks/tool_optimizations/accounting.py#UsageRecord",
    "sym:benchmarks/tool_optimizations/accounting.py#PriceRow",
    "sym:benchmarks/tool_optimizations/accounting.py#cost_usd"
  ]
}
```

## Implementation Notes

- Follow the uv workspace source layout, strict type hints and async-first resource ownership. Use stdlib and already-declared Pydantic; do not add dependencies without authorization.
- Keep changes within the target table. If implementation reveals an additional target or a conflict with project conventions, report it before expanding scope.
- May run alongside tasks outside its dependency chain with disjoint targets. Requires TASK-3511 for the contracts and deliverables described below.
- Activate the main repository virtual environment when using a shell in a worktree; do not create a worktree venv. Store test output in `artifacts/logs/`.
- Format touched Python with black and run ruff for touched Python files. These supplement the file-level test contract below.

## Implementation Blueprint

The following are required interfaces or artifact contracts, not claims that the symbols already exist:

- `def evaluate_gate(attempts: list[AttemptRecord], prices: PriceBook) -> GateResult`
- `python -m benchmarks.sdd_lsp: explicit manifest/output arguments and opt-in --live; no live default.`

1. Compute complete cohort and paired statistics without dropping missing/failed records.
2. Implement deterministic gate disposition and reporting, including task-level regressions and unknown usage.
3. Wire CLI argument validation to run_pilot and gate/report output; test exact threshold boundaries and no network/process launch in offline mode.

Use complete implementations, with no placeholder methods or unfinished public tools. Test fixtures must be deterministic and independent of live providers unless explicitly opted in.

## Acceptance Criteria

- [ ] Implement evaluate_gate(attempts, prices) and deterministic JSON/Markdown reports with cohort total cost divided by accepted count, charging all failed attempts/retries.
- [ ] Compare combined LSP to wiki_ast against the exact 10% cost, no acceptance/correctness regression and <=10% median wall-time criteria.
- [ ] Report per-task paired outcomes, pooled totals, medians/p95, correction cycles and cold/warm timings; unknown/incomplete/zero-success inputs cannot pass.
- [ ] Expose an offline-default CLI with explicit --live and complete manifest, calling the runner only on live opt-in; label synthetic reports so they cannot satisfy acceptance.
- [ ] All target files are complete and file-level validation passes.
- [ ] No unrelated files or actual developer host configuration are changed.
- [ ] Failures, unavailable prerequisites and verification limitations are recorded honestly in the completion note.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/lsp/test_benchmark_report.py -q`

## Test Specification

- `test_cache_accounting_and_gate`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_threshold_boundaries_and_per_task_regressions`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_incomplete_and_zero_success_are_inconclusive`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_cli_offline_default_and_live_validation`: cover the corresponding scope invariant with both successful and adversarial inputs.

## Agent Instructions

1. Read the approved spec and this task; verify prerequisites in `sdd/tasks/index/sdd-research-lsp.json`.
2. Mark only this task in-progress with assignment/start timestamp before implementing.
3. Reverify existing and dependency-produced contracts; follow the file scope and update the task first if an approved scope correction is needed.
4. Implement and run the validation above; record actual results and any external blockers.
5. Run the required SDD review, then commit only task-scoped implementation plus this task and its per-spec index state. Do not use the historical monolithic index.
6. Mark done only when every acceptance criterion is satisfied. Leave blocked external execution unfinished.

## Completion Note

Not completed. The implementing agent must record changed behavior, validation results, commit, review outcome and remaining limitations here.
