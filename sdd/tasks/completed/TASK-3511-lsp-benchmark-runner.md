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

**Implemented by the sdd-worker orchestrator directly** (same authorized
exception as TASK-3508): `parrot-sdd-coder` rejected this task on every
probed seat with `CoderFailure: ... is not eligible for unknown task
TASK-3511` (`classification=unknown`, `reason_codes=["metric_unknown"]`).
Filed under the same `issue:f0cf45fc31dd` as TASK-3508.

Implemented `async def run_pilot(manifest: PilotManifest, output_dir:
Path) -> PilotReport` in `benchmarks/sdd_lsp/runner.py`, matching the
spec's exact interface skeleton (2 params, no extra ones — cost tracking
therefore relies solely on `ModelUsage.actual_cost_usd`, never an internal
`PriceBook`, which the fixed signature has no room to accept):

- `build_attempt_matrix`/`_ordered_pairs` expand a validated manifest into
  exactly 180 deterministic `AttemptSpec`s. An explicit
  `counterbalanced_order` (`"{task_id}|{arm}"` tokens) is honored verbatim
  and validated (malformed token / incomplete coverage both raise
  `ValueError` explicitly); otherwise a documented default rotates the arm
  order per repetition.
- `ARM_TOOL_FILTER` makes each arm's LSP tool visibility explicit
  (`current`/`wiki_ast`: none; `lsp_navigation`:
  definition+references; `lsp_diagnostics`: diagnostics+delta;
  `lsp_combined`: all four) — communicated to the seat via
  `PARROT_LSP_PILOT_TOOLS` since the seat's own MCP wiring is out of this
  task's scope (explicitly "NOT in scope: choosing host/provider
  adapters").
- Each attempt gets a freshly materialized, isolated directory
  (`build_fixture(task_id).materialize(...)`) and launches the seat's
  exact configured `argv` via `asyncio.create_subprocess_exec` (no shell),
  bounded by `SeatSpec.timeout_s`, with `PARROT_LSP_PILOT_FORCE_UNAVAILABLE=1`
  set for the one task whose fixture requires a simulated unavailable
  semantic server (`fix-unavailable-server`), regardless of arm.
- Investigation-task answers are read from `answer.json` and checked via
  `check_definition_answer`; change/fix edits are checked in place via
  `run_behavior_check`. Usage is read from `trace.jsonl`
  (`ModelUsage`-shaped JSON lines); a missing trace is recorded in
  `coverage_manifest["missing_trace"]`, never silently dropped, and never
  treated as zero cost.
- Budget discipline: before each launch, remaining budget is checked
  against `per_attempt_cost_reservation_usd`; after each attempt,
  `accounting.attempt_cost_usd` (empty `PriceBook`, so only
  `actual_cost_usd` is trusted) determines spend — an unknown cost or an
  exhausted budget stops launching further attempts, but every
  not-yet-launched attempt is still retained in the report with an
  explicit `"not_launched: ..."` failure_reason. Nothing is silently
  dropped.
- All blocking I/O (`asyncio.create_subprocess_exec`'s bounded wait aside)
  is wrapped in `asyncio.to_thread` — directory materialization, trace/
  answer file reads, `run_behavior_check`'s subprocess call, and cleanup —
  per the async-first convention; `ruff`'s `ASYNC240` finding was fixed,
  not suppressed.

Tests (`test_benchmark_runner.py`) use a small fake CLI seat script
(written to `tmp_path` at test setup, never committed) driven purely by
an argv mode token, never a live provider:
`test_pilot_manifest_and_matrix` (180 deterministic attempts, explicit
counterbalanced order honored/validated, malformed order rejected);
`test_arm_filters_and_isolated_working_states` (full `ARM_TOOL_FILTER`
mapping verified; a full successful 180-attempt run proves per-attempt
isolation via scoped usage records); `test_budget_unknown_cost_and_
timeout_stop` (unknown-cost stop after 1 of 180 launches; budget
exhaustion stop; a hung seat is bounded by its own tiny per-seat timeout
across the full matrix); `test_trace_coverage_and_failed_attempts_
retained` (missing trace recorded as coverage without affecting
acceptance; a crashing seat still yields 180 retained, unaccepted
records).

Validation: `pytest packages/ai-parrot-tools/tests/lsp/test_benchmark_runner.py -q`
→ 4 passed (~56s — 180-attempt full-matrix subprocess runs, expected for
this task's scale). Full `packages/ai-parrot-tools/tests/lsp/` regression
after this change: 123 collected, 120 passed, 3 skipped (real-Pyright
tests, unrelated). `black -l 120`/`ruff check` clean.

**Design choices made where the spec leaves the exact mechanism open**
(all documented inline in `runner.py`'s module docstring): the
`PARROT_LSP_PILOT_*` env-var contract for arm/tool-filter signaling to an
external seat, and the `answer.json`/`trace.jsonl` file conventions for
reading back a seat's investigation answer / normalized usage. No
existing convention was available to verify against (this is the first
task to define the seat-launch contract), so these are original design
decisions, not verified pre-existing symbols — flagged per the Codebase
Contract's anti-hallucination discipline.

Seat: sonnet (native, no MCP seat) — implemented directly by the
sdd-worker orchestrator per the human-authorized exception (see
TASK-3508's completion note for the full blocker context).

**Review-fix round (post-merge adversarial review, two independent
reviewers, both CONFIRM):**
- 🔴 CRITICAL, fixed: an attempt with NO trace ever observed (seat
  crashed before flushing `trace.jsonl`, or a well-behaved seat's
  attempt that simply never produced one) was priced at `0.0` by
  `accounting.attempt_cost_usd`'s general "no usage = known zero"
  contract, not `None` — this defeated the budget/unknown-cost stop
  entirely and, at the report layer, could fabricate a false 100% cost
  reduction / `"go"`. **Correction to this file's earlier claim**: the
  original completion note above said a missing trace is "never treated
  as zero cost" — that was false at the time, per direct reproduction
  during review. Fixed with a new `runner.effective_attempt_cost_usd()`
  wrapper (used by both the budget loop and `report.py`'s cohort cost
  math) that returns `None` whenever no trace was ever observed,
  reserving `accounting.attempt_cost_usd`'s `0.0` for a trace that was
  present and explicitly reported zero-cost categories. Regression tests:
  rewrote `test_trace_coverage_and_failed_attempts_retained`'s two
  scenarios (`no_trace` and `crash` modes) to assert the run now halts
  after the first untraced attempt instead of completing all 180 with a
  fabricated zero-cost/accepted result; added
  `test_missing_trace_is_never_priced_as_free` in
  `test_benchmark_report.py` reproducing the exact false-`"go"` scenario
  end to end.
- 🔴 CRITICAL, fixed: an accepted attempt's `trace.jsonl` was deleted
  with its scratch directory and never persisted anywhere else — the
  returned `AttemptRecord.raw_trace_refs` pointed at a file that no
  longer existed, and the full `PilotReport` (all per-attempt records)
  was never written to disk, only the aggregated `report.json`/`report.md`.
  Fixed: the trace is now archived to a durable
  `output_dir/evidence/<attempt_id>/trace.jsonl` before any cleanup
  (`raw_trace_refs` points at that durable copy), and `run_pilot` writes
  the complete `PilotReport` to `output_dir/pilot_report.json` before
  returning. New assertions added to
  `test_arm_filters_and_isolated_working_states` proving the evidence
  survives cleanup and the persisted report round-trips.
- 🟠 IMPORTANT, deferred to ledger (`issue:65185c6c4f4a`): `tool_calls`,
  `lsp_operations`, `correction_cycles`, and `retries` are never
  populated on `AttemptRecord` by this runner — they silently default to
  `0`. Fixing this needs a seat-protocol addition (a way for the seat to
  report these back), out of scope for a same-session review fix.
- 🟠 IMPORTANT, fixed: `benchmarks/sdd_lsp/__main__.py`'s `_amain` called
  `path.read_text()`/`write_reports()` synchronously inside an `async
  def`, inconsistent with this module's own `asyncio.to_thread`
  discipline. Wrapped both in `asyncio.to_thread`.

Full `packages/ai-parrot-tools/tests/lsp/` regression after these fixes:
133 passed, 3 skipped (real-Pyright, unrelated). `black -l 120`/
`ruff check` clean. Feedback NOT recorded via `coder_record_feedback`
(this attempt has no resolvable `attempt_uid` — see TASK-3511's original
completion note; the parrot-sdd-coder MCP server never dispatched this
task).
