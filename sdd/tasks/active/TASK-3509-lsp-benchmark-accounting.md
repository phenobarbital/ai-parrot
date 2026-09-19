# TASK-3509: Define pilot manifests and cache-aware usage accounting

**Feature**: FEAT-580 - SDD LSP Research Pilot
**Spec**: `sdd/specs/sdd-research-lsp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement M5 of the approved specification: define pilot manifests and cache-aware usage accounting. The reported 13% cost, 12% token and 24% call reductions are hypotheses; only the specified evaluation can establish local benefit. Read the complete spec's contracts, acceptance criteria and relevant module before implementation.

## Scope

- Define PilotManifest, ModelUsage, PriceBook, AttemptRecord, PilotReport and GateResult contracts from §2 Evaluation; retain unknown values and provenance.
- Validate five arm names, 12 tasks, three repetitions, pinned commit/model/environment/price semantics, seat argv, timeout and explicit spending ceiling before live execution.
- Implement disjoint cache/read/write/output/reasoning billing and actual-billed-cost precedence; never double-count provider totals.
- Detect missing/duplicate request identifiers, unknown/inconsistent usage and failed/retry costs; avoid reusing the older two-rate benchmark model unchanged.
- Include a positive per-attempt cost reservation in the manifest and validate it against the total spending ceiling; the runner consumes this field before launch.

**NOT in scope**: Provider SDK adapters, actual prices, process execution, outcome gate and fabricated measurements.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `benchmarks/sdd_lsp/__init__.py` | CREATE | Task implementation |
| `benchmarks/sdd_lsp/models.py` | CREATE | Task implementation |
| `benchmarks/sdd_lsp/accounting.py` | CREATE | Task implementation |
| `packages/ai-parrot-tools/tests/lsp/test_benchmark_accounting.py` | CREATE | Acceptance and regression tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

- `from pydantic import BaseModel, ConfigDict, Field` — verified in `benchmarks/tool_optimizations/accounting.py`; use only where relevant.

### Existing Signatures to Use

- `UsageRecord` — `benchmarks/tool_optimizations/accounting.py:68`: existing BaseModel with stage, tokens: Optional[int], source and elapsed_ms; not sufficient for the new normalized provider record.
- `PriceRow` — `benchmarks/tool_optimizations/accounting.py:86`: existing two-rate input/output model lacks cache categories; do not silently reuse it for pilot billing.
- `cost_usd` — `benchmarks/tool_optimizations/accounting.py:133`: cost_usd(records: list[UsageRecord], model: str, prices: CostModel) -> Optional[float]; existing benchmark precedent only, not the new gate API.

### Dependency-produced contracts

- No implementation prerequisites. Existing repository conventions and the approved spec apply.

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
      "path": "benchmarks/sdd_lsp/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "benchmarks/sdd_lsp/models.py",
      "action": "CREATE"
    },
    {
      "path": "benchmarks/sdd_lsp/accounting.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/lsp/test_benchmark_accounting.py",
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
- Independent root task; may run alongside tasks with disjoint targets. Owns lsp-benchmark-accounting targets only.
- Activate the main repository virtual environment when using a shell in a worktree; do not create a worktree venv. Store test output in `artifacts/logs/`.
- Format touched Python with black and run ruff for touched Python files. These supplement the file-level test contract below.

## Implementation Blueprint

The following are required interfaces or artifact contracts, not claims that the symbols already exist:

- `Models exported by benchmarks.sdd_lsp.models; accounting helpers consume normalized records without provider SDKs.`
- `PriceBook uses explicit currency/rate units, effective date and provenance; absent prices or ambiguous categories produce unknown cost.`

1. Define typed normalized records and referential integrity between attempts/seats/requests before runner/report consumers are implemented.
2. Implement auditable billing aggregation with Decimal or equivalent exact decimal arithmetic and explicit category semantics.
3. Test known and missing costs, cache overlaps, reasoning already in output, duplicate IDs and failed attempts.

Use complete implementations, with no placeholder methods or unfinished public tools. Test fixtures must be deterministic and independent of live providers unless explicitly opted in.

## Acceptance Criteria

- [ ] Define PilotManifest, ModelUsage, PriceBook, AttemptRecord, PilotReport and GateResult contracts from §2 Evaluation; retain unknown values and provenance.
- [ ] Validate five arm names, 12 tasks, three repetitions, pinned commit/model/environment/price semantics, seat argv, timeout and explicit spending ceiling before live execution.
- [ ] Implement disjoint cache/read/write/output/reasoning billing and actual-billed-cost precedence; never double-count provider totals.
- [ ] Detect missing/duplicate request identifiers, unknown/inconsistent usage and failed/retry costs; avoid reusing the older two-rate benchmark model unchanged.
- [ ] Include a positive per-attempt cost reservation in the manifest and validate it against the total spending ceiling; the runner consumes this field before launch.
- [ ] All target files are complete and file-level validation passes.
- [ ] No unrelated files or actual developer host configuration are changed.
- [ ] Failures, unavailable prerequisites and verification limitations are recorded honestly in the completion note.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/lsp/test_benchmark_accounting.py -q`

## Test Specification

- `test_manifest_dimensions_and_explicit_budget`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_cache_categories_are_disjoint`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_unknown_usage_never_becomes_zero`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_actual_cost_precedence_and_duplicate_requests`: cover the corresponding scope invariant with both successful and adversarial inputs.

## Agent Instructions

1. Read the approved spec and this task; verify prerequisites in `sdd/tasks/index/sdd-research-lsp.json`.
2. Mark only this task in-progress with assignment/start timestamp before implementing.
3. Reverify existing and dependency-produced contracts; follow the file scope and update the task first if an approved scope correction is needed.
4. Implement and run the validation above; record actual results and any external blockers.
5. Run the required SDD review, then commit only task-scoped implementation plus this task and its per-spec index state. Do not use the historical monolithic index.
6. Mark done only when every acceptance criterion is satisfied. Leave blocked external execution unfinished.

## Completion Note

Not completed. The implementing agent must record changed behavior, validation results, commit, review outcome and remaining limitations here.
