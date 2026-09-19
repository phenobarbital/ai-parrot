# TASK-3513: Verify seat visibility and prepare the operator run checklist

**Feature**: FEAT-580 - SDD LSP Research Pilot
**Spec**: `sdd/specs/sdd-research-lsp.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3508, TASK-3512
**Assigned-to**: unassigned

## Context

Implement M4–M6 of the approved specification: verify seat visibility and prepare the operator run checklist. The reported 13% cost, 12% token and 24% call reductions are hypotheses; only the specified evaluation can establish local benefit. Read the complete spec's contracts, acceptance criteria and relevant module before implementation.

## Scope

- Add a host-smoke harness that validates research/coding/review seat tool visibility independently using operator-supplied CLI commands.
- Exercise definition/reference and saved diagnostic calls through seats when opted in; server-level tools/list alone is not accepted as proof.
- Document immutable environments, actual prices/cache semantics, budget, pinned task commits and a reviewed ground-truth checklist for the 180-attempt run.
- Record fallback-only/unavailable seats and missing prerequisites explicitly; default tests use fake CLI seat fixtures and spend no money.

**NOT in scope**: Live pilot measurement itself, auto-installing host config and weakening the spec's external prerequisites.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/lsp/test_seat_visibility.py` | CREATE | Acceptance and regression tests |
| `docs/sdd/lsp-pilot.md` | MODIFY | Operator-facing evidence or guidance |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

- `from parrot.mcp.toolkit_server import create_toolkit_mcp_server` — verified in `packages/ai-parrot/src/parrot/mcp/toolkit_server.py`; use only where relevant.
- `from pydantic import BaseModel, ConfigDict, Field` — verified in `benchmarks/tool_optimizations/accounting.py`; use only where relevant.

### Existing Signatures to Use

- `create_toolkit_mcp_server` — `packages/ai-parrot/src/parrot/mcp/toolkit_server.py:29`: create_toolkit_mcp_server(name: str, root: Path = Path.cwd(), **overrides: Any) -> StdioMCPServer; imports under stdout redirection, constructs toolkit kwargs, filters and registers tools. Currently does not retain a resource owner.
- `UsageRecord` — `benchmarks/tool_optimizations/accounting.py:68`: existing BaseModel with stage, tokens: Optional[int], source and elapsed_ms; not sufficient for the new normalized provider record.
- `PriceRow` — `benchmarks/tool_optimizations/accounting.py:86`: existing two-rate input/output model lacks cache categories; do not silently reuse it for pilot billing.
- `cost_usd` — `benchmarks/tool_optimizations/accounting.py:133`: cost_usd(records: list[UsageRecord], model: str, prices: CostModel) -> Optional[float]; existing benchmark precedent only, not the new gate API.

### Dependency-produced contracts

- TASK-3508 supplies . Read its completed implementation and tests before consuming its API; these are planned deliverables, not verified existing symbols.
- TASK-3512 supplies `benchmarks/sdd_lsp/report.py`, `benchmarks/sdd_lsp/__main__.py`. Read its completed implementation and tests before consuming its API; these are planned deliverables, not verified existing symbols.

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
      "path": "packages/ai-parrot-tools/tests/lsp/test_seat_visibility.py",
      "action": "CREATE"
    },
    {
      "path": "docs/sdd/lsp-pilot.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_server.py#create_toolkit_mcp_server",
    "sym:benchmarks/tool_optimizations/accounting.py#UsageRecord",
    "sym:benchmarks/tool_optimizations/accounting.py#PriceRow",
    "sym:benchmarks/tool_optimizations/accounting.py#cost_usd"
  ]
}
```

## Implementation Notes

- Follow the uv workspace source layout, strict type hints and async-first resource ownership. Use stdlib and already-declared Pydantic; do not add dependencies without authorization.
- Keep changes within the target table. If implementation reveals an additional target or a conflict with project conventions, report it before expanding scope.
- May run alongside tasks outside its dependency chain with disjoint targets. Requires TASK-3508, TASK-3512 for the contracts and deliverables described below.
- Activate the main repository virtual environment when using a shell in a worktree; do not create a worktree venv. Store test output in `artifacts/logs/`.
- Format touched Python with black and run ruff for touched Python files. These supplement the file-level test contract below.

## Implementation Blueprint

The following are required interfaces or artifact contracts, not claims that the symbols already exist:

- `test_cli_seat_visibility_and_fallback consumes an explicit seat-smoke manifest; no provider SDK import.`
- `PARROT_LSP_LIVE_MANIFEST selects the operator manifest for explicitly opted-in live checks; absence means not executed, never passed.`

1. Use completed toolkit and pilot CLI protocols to exercise three independently configured seat roles with fake hosts.
2. Provide the opt-in real-host path and validate each role's actual tool access, root isolation and fallbacks.
3. Extend the operator guide with readiness evidence and the exact pending §8 manifest requirements; do not invent defaults for model/pricing/budget.

Use complete implementations, with no placeholder methods or unfinished public tools. Test fixtures must be deterministic and independent of live providers unless explicitly opted in.

## Acceptance Criteria

- [ ] Add a host-smoke harness that validates research/coding/review seat tool visibility independently using operator-supplied CLI commands.
- [ ] Exercise definition/reference and saved diagnostic calls through seats when opted in; server-level tools/list alone is not accepted as proof.
- [ ] Document immutable environments, actual prices/cache semantics, budget, pinned task commits and a reviewed ground-truth checklist for the 180-attempt run.
- [ ] Record fallback-only/unavailable seats and missing prerequisites explicitly; default tests use fake CLI seat fixtures and spend no money.
- [ ] All target files are complete and file-level validation passes.
- [ ] No unrelated files or actual developer host configuration are changed.
- [ ] Failures, unavailable prerequisites and verification limitations are recorded honestly in the completion note.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/lsp/test_seat_visibility.py -q`

## Test Specification

- `test_cli_seat_visibility_and_fallback`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_parent_visibility_does_not_imply_child_visibility`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_missing_live_manifest_is_not_success`: cover the corresponding scope invariant with both successful and adversarial inputs.

## Agent Instructions

1. Read the approved spec and this task; verify prerequisites in `sdd/tasks/index/sdd-research-lsp.json`.
2. Mark only this task in-progress with assignment/start timestamp before implementing.
3. Reverify existing and dependency-produced contracts; follow the file scope and update the task first if an approved scope correction is needed.
4. Implement and run the validation above; record actual results and any external blockers.
5. Run the required SDD review, then commit only task-scoped implementation plus this task and its per-spec index state. Do not use the historical monolithic index.
6. Mark done only when every acceptance criterion is satisfied. Leave blocked external execution unfinished.

## Completion Note

**Implemented by the sdd-worker orchestrator directly** (same authorized
exception as TASK-3508/3511/3512): `parrot-sdd-coder` had no eligible seat
for this `classification=unknown` task, filed under the same
`issue:f0cf45fc31dd`.

Implemented `packages/ai-parrot-tools/tests/lsp/test_seat_visibility.py`:
- `test_cli_seat_visibility_and_fallback`: three independently configured
  seat-role worktrees (`research`/`coding`/`review`), each with its own
  `.parrot/mcp-toolkits.yaml` pointed at the scripted `fake_server.py`
  fixture (never a live agent). Each role's access is confirmed with a
  real `lsp_definition` call, not just a declared `tools/list` — matching
  spec's "server-level tools/list alone is not accepted as proof".
  Adversarial: a role pointed at the `operator-unconfigured` sentinel is
  recorded `fallback_only=True` explicitly; a worktree with no `lsp:`
  section resolves as `visible=False`, not a crash.
- `test_parent_visibility_does_not_imply_child_visibility`: empirically
  proves the exact failure mode `docs/sdd/lsp-pilot.md` already warned
  about — blindly copying a parent worktree's rendered
  `.parrot/mcp-toolkits.yaml` into a child worktree still points at the
  parent's absolute `repo_root`; querying a child-only file through that
  copied config fails with `code="invalid_request"` (not part of the
  parent's tracked/untracked manifest at all).
- `test_missing_live_manifest_is_not_success` /
  `test_live_manifest_when_provided_is_executed`: the opt-in
  `PARROT_LSP_LIVE_MANIFEST` env var is absent by default — the live
  check then returns `None` ("not executed"), never a fabricated pass;
  when set to an operator manifest (a fake CLI here, for determinism), the
  check actually runs and reports per-role results.

Modified `docs/sdd/lsp-pilot.md`: added an "Operator run checklist
(pre-M6)" section directly addressing spec §8's one unresolved open
question (concrete CLI/model versions, immutable environment IDs, real
task commits, price basis, spending ceiling) with a reviewed
180-attempt-matrix checklist, plus a "Opting into the live seat-readiness
check" subsection documenting `PARROT_LSP_LIVE_MANIFEST`'s exact contract
and JSON shape. No defaults were invented for any of these — every item
is stated as an operator/experiment-owner decision, matching spec §8's
own framing.

Validation: `pytest packages/ai-parrot-tools/tests/lsp/test_seat_visibility.py -q`
→ 4 passed. Full `packages/ai-parrot-tools/tests/lsp/` regression: 132
collected, 129 passed, 3 skipped (unrelated real-Pyright tests). `black
-l 120`/`ruff check` clean.

Two corrections made during implementation (both verified against actual
source before asserting, not assumed): (1) `lsp_diagnostics` was dropped
from the seat-access proof because `fake_server.py`'s `happy_path`
scenario always publishes diagnostics for a fixed, unrelated URI
(documented precedent in `test_session_diagnostics.py`) — `lsp_definition`
alone proves real tool access; (2) the child-visibility test's expected
failure code is `"invalid_request"` (a path not part of any
tracked/untracked manifest entry), not `"file_missing"` (reserved for a
tracked-then-deleted path) — verified directly against
`snapshot.py`'s `LSPFailure` call sites before asserting.

Seat: sonnet (native, no MCP seat) — implemented directly by the
sdd-worker orchestrator per the human-authorized exception (see
TASK-3508's completion note for the full blocker context).
