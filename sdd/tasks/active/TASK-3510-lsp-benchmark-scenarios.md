# TASK-3510: Curate the twelve pilot tasks and executable ground truth

**Feature**: FEAT-580 - SDD LSP Research Pilot
**Spec**: `sdd/specs/sdd-research-lsp.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3509
**Assigned-to**: unassigned

## Context

Implement M5 of the approved specification: curate the twelve pilot tasks and executable ground truth. The reported 13% cost, 12% token and 24% call reductions are hypotheses; only the specified evaluation can establish local benefit. Read the complete spec's contracts, acceptance criteria and relevant module before implementation.

## Scope

- Define the four investigation, four change and four fix tasks exactly as named in the spec, with bounded descriptions, required evidence and behavior acceptance commands.
- Produce deterministic fixture repositories and independent expected-evidence/check definitions; include aliases, inherited receivers, namespaces, decorators, registry strings and unavailable-server fallback.
- Preserve identical task checks across all arms and pin fixture content/hashes; include policy requiring supplementary text search for dynamic cases.
- Ground truth must be reviewable before live measurement and must test outcomes, not count whether LSP was called.

**NOT in scope**: Live runs, choosing commercial model seats, billing totals and automatic ground-truth generation with an LLM.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `benchmarks/sdd_lsp/tasks.yaml` | CREATE | Explicit declarative configuration |
| `benchmarks/sdd_lsp/fixtures/scenarios.py` | CREATE | Task implementation |
| `benchmarks/sdd_lsp/fixtures/acceptance.py` | CREATE | Task implementation |
| `packages/ai-parrot-tools/tests/lsp/test_benchmark_scenarios.py` | CREATE | Acceptance and regression tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

- `from pydantic import BaseModel, ConfigDict, Field` — verified in `benchmarks/tool_optimizations/accounting.py`; use only where relevant.

### Existing Signatures to Use

- `UsageRecord` — `benchmarks/tool_optimizations/accounting.py:68`: existing BaseModel with stage, tokens: Optional[int], source and elapsed_ms; not sufficient for the new normalized provider record.
- `PriceRow` — `benchmarks/tool_optimizations/accounting.py:86`: existing two-rate input/output model lacks cache categories; do not silently reuse it for pilot billing.
- `cost_usd` — `benchmarks/tool_optimizations/accounting.py:133`: cost_usd(records: list[UsageRecord], model: str, prices: CostModel) -> Optional[float]; existing benchmark precedent only, not the new gate API.

### Dependency-produced contracts

- TASK-3509 supplies `benchmarks/sdd_lsp/__init__.py`, `benchmarks/sdd_lsp/models.py`, `benchmarks/sdd_lsp/accounting.py`. Read its completed implementation and tests before consuming its API; these are planned deliverables, not verified existing symbols.

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
      "path": "benchmarks/sdd_lsp/tasks.yaml",
      "action": "CREATE"
    },
    {
      "path": "benchmarks/sdd_lsp/fixtures/scenarios.py",
      "action": "CREATE"
    },
    {
      "path": "benchmarks/sdd_lsp/fixtures/acceptance.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/lsp/test_benchmark_scenarios.py",
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
- May run alongside tasks outside its dependency chain with disjoint targets. Requires TASK-3509 for the contracts and deliverables described below.
- Activate the main repository virtual environment when using a shell in a worktree; do not create a worktree venv. Store test output in `artifacts/logs/`.
- Format touched Python with black and run ruff for touched Python files. These supplement the file-level test contract below.

## Implementation Blueprint

The following are required interfaces or artifact contracts, not claims that the symbols already exist:

- `tasks.yaml defines 12 stable IDs, category, prompt, fixture selector, required evidence and file-level acceptance commands.`
- `fixtures/scenarios.py builds temporary fixture trees; fixtures/acceptance.py evaluates independently prepared evidence/behavior.`

1. Map all twelve approved scenarios to stable IDs and explicit success/failure cases.
2. Build small deterministic fixture generators and acceptance checks whose expected outcomes do not depend on a particular retrieval arm.
3. Validate each fixture's baseline, intended change and counterexample so vacuous tests cannot report acceptance.

Use complete implementations, with no placeholder methods or unfinished public tools. Test fixtures must be deterministic and independent of live providers unless explicitly opted in.

## Acceptance Criteria

- [ ] Define the four investigation, four change and four fix tasks exactly as named in the spec, with bounded descriptions, required evidence and behavior acceptance commands.
- [ ] Produce deterministic fixture repositories and independent expected-evidence/check definitions; include aliases, inherited receivers, namespaces, decorators, registry strings and unavailable-server fallback.
- [ ] Preserve identical task checks across all arms and pin fixture content/hashes; include policy requiring supplementary text search for dynamic cases.
- [ ] Ground truth must be reviewable before live measurement and must test outcomes, not count whether LSP was called.
- [ ] All target files are complete and file-level validation passes.
- [ ] No unrelated files or actual developer host configuration are changed.
- [ ] Failures, unavailable prerequisites and verification limitations are recorded honestly in the completion note.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/lsp/test_benchmark_scenarios.py -q`

## Test Specification

- `test_twelve_scenarios_cover_approved_matrix`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_acceptance_rejects_incorrect_changes`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_dynamic_cases_require_additional_evidence`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_fixture_hashes_and_prompts_are_stable`: cover the corresponding scope invariant with both successful and adversarial inputs.

## Agent Instructions

1. Read the approved spec and this task; verify prerequisites in `sdd/tasks/index/sdd-research-lsp.json`.
2. Mark only this task in-progress with assignment/start timestamp before implementing.
3. Reverify existing and dependency-produced contracts; follow the file scope and update the task first if an approved scope correction is needed.
4. Implement and run the validation above; record actual results and any external blockers.
5. Run the required SDD review, then commit only task-scoped implementation plus this task and its per-spec index state. Do not use the historical monolithic index.
6. Mark done only when every acceptance criterion is satisfied. Leave blocked external execution unfinished.

## Completion Note

Not completed. The implementing agent must record changed behavior, validation results, commit, review outcome and remaining limitations here.
