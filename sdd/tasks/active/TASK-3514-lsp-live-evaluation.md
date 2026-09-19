# TASK-3514: Execute the approved pilot and publish its audited decision

**Feature**: FEAT-580 - SDD LSP Research Pilot
**Spec**: `sdd/specs/sdd-research-lsp.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3513
**Assigned-to**: unassigned

## Context

Implement M6 of the approved specification: execute the approved pilot and publish its audited decision. The reported 13% cost, 12% token and 24% call reductions are hypotheses; only the specified evaluation can establish local benefit. Read the complete spec's contracts, acceptance criteria and relevant module before implementation.

## Scope

- Require the operator's reviewed manifest, exact CLI/model/environment identities, prices, spending ceiling and pre-reviewed task ground truth before launching paid runs.
- Run the complete 12-task x 3-repetition x 5-arm matrix through the completed harness; preserve failed attempts, retries, missing traces and raw-log references.
- Audit and publish real go/no_go/inconclusive evidence with task-level and cohort cost/quality/latency results and limitations; do not substitute synthetic data.
- Add report-integrity tests for the committed lightweight summary and manifest digest; ordinary fixture-only tests cannot complete the real-run acceptance requirement.
- If prerequisites or trace coverage are missing, record the external blocker and leave this task unfinished. A complete no-go result is a valid deliverable; retain opt-in deployment.

**NOT in scope**: Changing success criteria, choosing unsupported pricing, implementing new host adapters and auto-enabling rollout.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/sdd/lsp-pilot-results.md` | CREATE | Operator-facing evidence or guidance |
| `packages/ai-parrot-tools/tests/lsp/test_live_pilot_report.py` | CREATE | Acceptance and regression tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

- `from pydantic import BaseModel, ConfigDict, Field` — verified in `benchmarks/tool_optimizations/accounting.py`; use only where relevant.

### Existing Signatures to Use

- `UsageRecord` — `benchmarks/tool_optimizations/accounting.py:68`: existing BaseModel with stage, tokens: Optional[int], source and elapsed_ms; not sufficient for the new normalized provider record.
- `PriceRow` — `benchmarks/tool_optimizations/accounting.py:86`: existing two-rate input/output model lacks cache categories; do not silently reuse it for pilot billing.
- `cost_usd` — `benchmarks/tool_optimizations/accounting.py:133`: cost_usd(records: list[UsageRecord], model: str, prices: CostModel) -> Optional[float]; existing benchmark precedent only, not the new gate API.

### Dependency-produced contracts

- TASK-3513 supplies `docs/sdd/lsp-pilot.md`. Read its completed implementation and tests before consuming its API; these are planned deliverables, not verified existing symbols.

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
      "path": "docs/sdd/lsp-pilot-results.md",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/lsp/test_live_pilot_report.py",
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
- Exclusive use of paid CLI seats and the approved spending budget; TASK-3513 supplies readiness evidence.
- Activate the main repository virtual environment when using a shell in a worktree; do not create a worktree venv. Store test output in `artifacts/logs/`.
- Format touched Python with black and run ruff for touched Python files. These supplement the file-level test contract below.

## Implementation Blueprint

The following are required interfaces or artifact contracts, not claims that the symbols already exist:

- `docs/sdd/lsp-pilot-results.md is an evidence-backed report, not a predicted savings claim.`
- `test_live_pilot_report requires the actual run artifacts to certify matrix/trace/gate coverage; synthetic fixtures test validation logic only.`

1. Check all predecessor verification and operator-provided readiness data; never infer approval from missing budget/environment fields.
2. Execute or resume auditable task attempts under the fixed manifest, honoring timeouts/spending and preserving failed-attempt cost.
3. Reconcile coverage and billing, validate report integrity, and publish the honest adoption disposition; only mark done after complete live evidence.

Use complete implementations, with no placeholder methods or unfinished public tools. Test fixtures must be deterministic and independent of live providers unless explicitly opted in.

## Acceptance Criteria

- [ ] Require the operator's reviewed manifest, exact CLI/model/environment identities, prices, spending ceiling and pre-reviewed task ground truth before launching paid runs.
- [ ] Run the complete 12-task x 3-repetition x 5-arm matrix through the completed harness; preserve failed attempts, retries, missing traces and raw-log references.
- [ ] Audit and publish real go/no_go/inconclusive evidence with task-level and cohort cost/quality/latency results and limitations; do not substitute synthetic data.
- [ ] Add report-integrity tests for the committed lightweight summary and manifest digest; ordinary fixture-only tests cannot complete the real-run acceptance requirement.
- [ ] If prerequisites or trace coverage are missing, record the external blocker and leave this task unfinished. A complete no-go result is a valid deliverable; retain opt-in deployment.
- [ ] All target files are complete and file-level validation passes.
- [ ] No unrelated files or actual developer host configuration are changed.
- [ ] Failures, unavailable prerequisites and verification limitations are recorded honestly in the completion note.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/lsp/test_live_pilot_report.py -q`

## Test Specification

- `test_live_pilot_report`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_live_report_rejects_synthetic_or_missing_attempts`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_live_gate_agrees_with_recorded_cost_and_acceptance`: cover the corresponding scope invariant with both successful and adversarial inputs.

Completion additionally requires all 180 real attempts and auditable trace/cost coverage. Fixture-only passes do not satisfy this task. Missing operator manifest, budget, seats or prices is an external execution blocker, not approval to fabricate defaults.

## Agent Instructions

1. Read the approved spec and this task; verify prerequisites in `sdd/tasks/index/sdd-research-lsp.json`.
2. Mark only this task in-progress with assignment/start timestamp before implementing.
3. Reverify existing and dependency-produced contracts; follow the file scope and update the task first if an approved scope correction is needed.
4. Implement and run the validation above; record actual results and any external blockers.
5. Run the required SDD review, then commit only task-scoped implementation plus this task and its per-spec index state. Do not use the historical monolithic index.
6. Mark done only when every acceptance criterion is satisfied. Leave blocked external execution unfinished.

## Completion Note

Not completed. The implementing agent must record changed behavior, validation results, commit, review outcome and remaining limitations here.
