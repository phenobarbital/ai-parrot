# TASK-3514: Execute the approved pilot and publish its audited decision

**Feature**: FEAT-580 - SDD LSP Research Pilot
**Spec**: `sdd/specs/sdd-research-lsp.spec.md`
**Status**: in-progress (blocked on operator-provided live-run manifest/prices/seats/budget — see Completion Note)
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

### Scope correction (2026-09-20, operator-approved)

`benchmarks/sdd_lsp/runner.py` requires `SeatSpec.argv` to be a real,
already-operator-provided CLI — "never invents a provider SDK
integration" (spec §3 M5). None existed for any of the five arms; without
one, M6 cannot launch a single live attempt. The operator selected
`minimax.minimax-m2.5` over AWS Bedrock-Mantle (live-verified reachable
on the operator's account via
`packages/ai-parrot/tests/clients/test_bedrock_live_matrix.py -k "mantle and minimax"`,
2026-09-20) as the one pinned model for all five arms (spec: "Identical
... model settings ... apply" across arms). Driving it requires composing
already-existing framework primitives only — `LLMFactory`'s
`"mantle:<model>"` string (`BedrockMantleClient`), `parrot.bots.Agent`'s
existing tool-calling loop, `parrot_tools.lsp.toolkit.LSPToolkit` for the
three LSP arms, and a handful of new small local tools for the `wiki_ast`
control condition (index-free, since each pilot attempt is a fresh
never-indexed fixture directory the repo's wiki graph knows nothing
about) — never a new LLM client class or CLI dispatcher, so this stays
inside the "NOT in scope: implementing new host adapters" boundary.

Added files (operator-approved, this scope-correction section is their
record per this task's own Agent Instructions step 3):

| File | Action | Description |
|---|---|---|
| `benchmarks/sdd_lsp/seats/__init__.py` | CREATE | Package marker |
| `benchmarks/sdd_lsp/seats/tools.py` | CREATE | Bounded, cwd-scoped local tools: file read/write/list, investigation answer submission, index-free AST find-definition/find-references, text search |
| `benchmarks/sdd_lsp/seats/bedrock_mantle_seat.py` | CREATE | The seat entry point (`python -m benchmarks.sdd_lsp.seats.bedrock_mantle_seat`) — same `argv` for all five arms, branches on `PARROT_LSP_PILOT_ARM`/`_TOOLS` env vars; satisfies `runner.py`'s full seat contract (env vars in, `answer.json`/edited `entry_point` + `trace.jsonl` out) |
| `packages/ai-parrot-tools/tests/lsp/test_bedrock_mantle_seat.py` | CREATE | Offline, network-free tests for the local tools and the trace/answer-writing contract (a fake/stub client, never a real Bedrock call) |

Per-arm tool loadout (operator-confirmed 2026-09-20):

| Arm | Tools beyond `read_file`/`write_file`/`list_dir`/`submit_answer` |
|---|---|
| `current` | none |
| `wiki_ast` | + `ast_find_definition`, `ast_find_references`, `text_search` |
| `lsp_navigation` | `wiki_ast`'s tools + `lsp_definition`, `lsp_references` |
| `lsp_diagnostics` | `wiki_ast`'s tools + `lsp_diagnostics`, `lsp_diagnostic_delta` |
| `lsp_combined` | `wiki_ast`'s tools + all four LSP tools |

The `fix-unavailable-server` forced condition
(`PARROT_LSP_PILOT_FORCE_UNAVAILABLE=1`) is simulated by constructing
`LSPConfig` with `environment_id=OPERATOR_UNCONFIGURED_ENVIRONMENT_ID`
for that one attempt regardless of arm, so every `lsp_*` call reports
`status="unavailable"` before any process spawns — reusing the toolkit's
own documented sentinel behavior rather than inventing new simulation
logic.

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

**NOT DONE — intentionally left `in-progress`, per this task's own
instructions.** M6 is explicitly not delegation-eligible (spec §3 Module
Breakdown: "Requires provisioned CLI seats, actual usage/pricing, and
human acceptance review; results cannot be manufactured"). This session
had no operator-reviewed manifest, no real CLI seats, no actual prices,
and no approved spending ceiling — exactly the external blocker spec §8's
one remaining open question describes. Per "If prerequisites or trace
coverage are missing, record the external blocker and leave this task
unfinished... A complete no-go result is a valid deliverable; retain
opt-in deployment," this task is **not marked done** and remains
`in-progress` in the per-spec index; its file is **not** moved to
`sdd/tasks/completed/`.

**What was implemented** (the portion achievable without fabricating live
evidence):
- `packages/ai-parrot-tools/tests/lsp/test_live_pilot_report.py`: report-
  integrity checking logic (`check_live_report_integrity`,
  `manifest_digest`) validated against synthetic fixtures shaped like a
  compliant live report — proving the CHECKING LOGIC works, never
  claiming a live run occurred. Verifies: a report must not be
  `synthetic`; its manifest must match a reviewed manifest's digest
  exactly (tamper-evident); every one of the 180 planned attempts must be
  present exactly once (no missing/duplicated ids); every launched
  attempt must carry either raw trace refs or an explicit failure reason
  (no silent gaps). Also verifies `evaluate_gate` is deterministically
  re-derivable from raw attempt data and reacts correctly to tampered
  acceptance data (three required tests, all present and passing).
- `docs/sdd/lsp-pilot-results.md`: an honest, clearly-marked
  **NOT YET RUN** placeholder — explains exactly what is blocking the
  live run (referencing spec §8 and the "Operator run checklist" in
  `docs/sdd/lsp-pilot.md`), what IS implemented and ready (M1–M5, all
  complete and tested offline), and the exact command an operator runs
  once the manifest/prices/seats/budget are reviewed. Contains
  deliberately **zero** go/no_go/cost/quality/latency claims.

**What was NOT done** (the actual scope of this task, honestly
unfulfilled): the real 12-task × 3-repetition × 5-arm (180-attempt) live
run was never executed; no real cost/trace/acceptance evidence exists;
no audited `go`/`no_go`/`inconclusive` decision was published; no human
acceptance review occurred. `lsp-pilot-results.md` explicitly does not
claim otherwise.

Validation: `pytest packages/ai-parrot-tools/tests/lsp/test_live_pilot_report.py -q`
→ 3 passed. Full `packages/ai-parrot-tools/tests/lsp/` regression: 135
collected, 132 passed, 3 skipped (unrelated real-Pyright tests). `black
-l 120`/`ruff check` clean.

Seat: sonnet (native, no MCP seat) — implemented directly by the
sdd-worker orchestrator per the human-authorized exception (see
TASK-3508's completion note for the routing-gap blocker context; that
blocker is unrelated to this task's OWN, separate M6 execution blocker
described above).
