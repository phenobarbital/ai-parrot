# TASK-2618: Rebuild build_usage_report on the ledger

**Feature**: FEAT-479 — Dev-Flow / Dev-Loop Telemetry Accounting on the Lifecycle Bus
**Spec**: `sdd/specs/devflow-telemetry-accounting.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2615
**Assigned-to**: unassigned

---

## Context

Implements the builder half of spec §3 Module 7 (Module 7a).

`build_usage_report` reads `snapshot.state.nodes` — the session-state view that
overwrites on retry and never sees pool workers. This task repoints it at the
`RunLedgerRecorder`, which has neither defect.

It also **deletes** `_single_worker_summary_for_node` (`usage_report.py:79`),
whose docstring concedes it only works when a pool has exactly one worker and
otherwise "returns `None` — never a guess". The model is real data now; the
heuristic is obsolete.

Rendering is TASK-2619. This task produces the model the renderers consume.

---

## Scope

- Reshape `UsageReport` / `AgentUsage` to express **node → cycle → worker**.
- Rewrite `build_usage_report` to take a `RunLedgerRecorder` (or its
  `by_seat()` output) instead of a `Snapshot`.
- Carry `partial` / `partial_reason` onto `UsageReport` (spec §8 Q1).
- Delete `_single_worker_summary_for_node` and its call site.
- Update `_close_host`'s call site to pass the run's ledger.
- Update the existing FEAT-405 tests, stating the rationale for each change.

**NOT in scope**: markdown/HTML rendering and the Failures section
(TASK-2619) — but keep `render_usage_markdown` / `render_usage_html` importable
and passing, even if temporarily rendering the totals row only.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/usage_report.py` | MODIFY | Reshape models; rewrite builder; delete the heuristic |
| `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | MODIFY | Pass the ledger at the `_close_host` call site |
| `packages/ai-parrot/tests/flows/dev_loop/test_usage_report.py` | MODIFY | Update for the new source |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# from TASK-2615:
from parrot.observability.recorders.run_ledger import RunLedgerRecorder, SeatUsage
# verified: packages/ai-parrot/src/parrot/flows/dev_loop/run_bundle.py
from parrot.flows.dev_loop.run_bundle import _sum_optional_int  # imported at usage_report.py:~30
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/usage_report.py
class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

class AgentUsage(_Frozen):                                 # ~line 38
    seat: str
    node_id: str
    backend: str = ""
    model: str = ""
    rounds: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    duration_seconds: float | None = None

class UsageReport(_Frozen):                                # line 64
    run_id: str
    generated_at: float = Field(default_factory=time.time)
    agents: list[AgentUsage] = Field(default_factory=list)
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    total_rounds: int | None = None

def _single_worker_summary_for_node(node_id, shared): ...  # line 79  <-- DELETE
def build_usage_report(snapshot: Snapshot, run_id: str, *,
                       shared: Mapping | None = None) -> UsageReport: ...  # line 104  <-- REWRITE
def _fmt_value(value) -> str: ...                          # ~line 205  ("—" when None)
def render_usage_markdown(report: UsageReport) -> str: ... # line 210
def render_usage_html(report: UsageReport) -> str: ...     # line 293

# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py — the call site
    usage_path = out_dir / f"{host.state.run_id}.usage.json"    # line 733
    usage_report = build_usage_report(                          # line 742
        ...,
    )
    usage_html_path.write_text(render_usage_html(usage_report)) # line 746
    usage_markdown = render_usage_markdown(usage_report)        # line 747
```

### Does NOT Exist

- ~~`Snapshot.state.nodes[...].dispatch.model`~~ — `DispatchState` has no
  `model` field. That absence is exactly why the deleted heuristic existed.
- ~~`SeatUsage.rounds` as a provider-reported value~~ — derive it from
  `len(cycles)` unless the ledger supplies one; do not invent a field.
- ~~`UsageRecord.cache_creation_input_tokens` / `.cache_read_input_tokens`~~ —
  **not on `UsageRecord`** (`recorders/models.py:45-58`). They exist on
  `DispatchState` only. Either drop these columns or source them separately —
  do NOT assume the ledger provides them.
- ~~`UsageReport.partial`~~ — this task adds it.

### ⚠ Cache-token columns — decide explicitly

The current report renders `cache_creation_input_tokens` /
`cache_read_input_tokens` from `DispatchState`. The ledger's `UsageRecord`
does **not** carry them. Options, in order of preference:

1. Drop the columns (simplest; they are absent for most backends anyway).
2. Keep them sourced from session state, clearly marked as a different plane.

Pick one, state it in the Completion Note, and do not silently render `—` for
data that exists elsewhere without saying so.

---

## Implementation Notes

### Target shape

```python
class CycleUsage(_Frozen):
    cycle: int
    model: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_seconds: float | None = None
    status: str = "completed"
    error_type: str = ""

class AgentUsage(_Frozen):
    seat: str
    node_id: str
    backend: str = ""
    model: str = ""
    rounds: int | None = None
    input_tokens: int | None = None      # summed across cycles
    output_tokens: int | None = None
    duration_seconds: float | None = None
    cycles: list[CycleUsage] = Field(default_factory=list)
    failures: int = 0

class UsageReport(_Frozen):
    run_id: str
    generated_at: float = Field(default_factory=time.time)
    agents: list[AgentUsage] = Field(default_factory=list)
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    total_rounds: int | None = None
    partial: bool = False                 # §8 Q1
    partial_reason: str = ""
```

### Preserve the `—` convention

`_sum_optional_int` and `_fmt_value` already implement "never fabricate `0`".
Keep using them, and honour `usage_reported=False` from the ledger. A seat whose
records are all unreported must total `None`, not `0`.

### Ordering

Emit seats in a stable order — parent node first, then its workers
(`development`, `development.w1`, `development.w2`, then `qa`, …) — so the
renderer can indent without re-sorting, and so report diffs stay readable
across runs.

### Key Constraints

- Pure function: no filesystem, no Redis, no network (the current builder's
  docstring promises this — keep it true).
- A run with an empty ledger must return a valid, empty report, not raise.
- Models stay `frozen=True, extra="forbid"`.
- When the run's ledger is missing at `_close_host` time (cross-process
  resume), set `partial=True` with a reason rather than reporting a short total.
- Pricing is a Non-Goal — do not surface `cost_usd`.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/run_bundle.py` — `_sum_optional_int`, `NodeReport`
- `packages/ai-parrot/src/parrot/flows/dev_loop/usage_report.py:205` — `_fmt_value`

---

## Acceptance Criteria

- [ ] `build_usage_report` sources from the ledger, not `Snapshot`.
- [ ] `_single_worker_summary_for_node` is **deleted**, with no remaining callers.
- [ ] A seat with two cycles reports the **sum**, and both cycles are present.
- [ ] Pool-worker seats appear with their own model.
- [ ] All-unreported seats total `None`, never `0`.
- [ ] `partial` / `partial_reason` are carried onto `UsageReport`.
- [ ] An empty ledger yields a valid empty report.
- [ ] The builder remains pure.
- [ ] The cache-token decision is recorded in the Completion Note.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_usage_report.py -v` passes.
- [ ] `render_usage_markdown` / `render_usage_html` still import and run.
- [ ] `ruff check` and `mypy` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_usage_report.py  (UPDATE)

def test_report_sums_cycles_per_seat(ledger_with_two_cycles):
    report = build_usage_report(ledger_with_two_cycles, run_id="run-1")
    (agent,) = report.agents
    assert agent.input_tokens == 3000        # not 2000 (the last cycle)
    assert [c.cycle for c in agent.cycles] == [1, 2]


def test_report_includes_pool_workers(ledger_with_pool):
    report = build_usage_report(ledger_with_pool, run_id="run-1")
    seats = {a.seat for a in report.agents}
    assert {"development.w1", "development.w2"} <= seats
    assert all(a.model for a in report.agents if a.seat.startswith("development."))


def test_report_never_fabricates_zero(ledger_unreported):
    report = build_usage_report(ledger_unreported, run_id="run-1")
    assert report.agents[0].input_tokens is None
    assert report.total_input_tokens is None


def test_empty_ledger_yields_valid_report():
    report = build_usage_report(RunLedgerRecorder(run_id="run-1"), run_id="run-1")
    assert report.agents == []
    assert report.total_input_tokens is None


def test_partial_flag_propagates(ledger_partial):
    report = build_usage_report(ledger_partial, run_id="run-1")
    assert report.partial is True
    assert report.partial_reason


def test_single_worker_summary_helper_is_gone():
    """The pool-size-1 guess is obsolete — the model is real data now."""
    import parrot.flows.dev_loop.usage_report as ur
    assert not hasattr(ur, "_single_worker_summary_for_node")
```

**Note on existing tests**: `test_usage_report.py` currently builds reports from
a `Snapshot`. Rewrite those fixtures onto the ledger. Where an existing
assertion no longer makes sense (e.g. the pool-size-1 model heuristic), delete
it and say why in the Completion Note — do not weaken an assertion to make it
pass.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §3 Module 7
2. **Check dependencies** — TASK-2615 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm the `UsageRecord` fields TASK-2614
   added, especially which token fields do NOT exist
4. **Update status** in `sdd/tasks/index/devflow-telemetry-accounting.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2618-usage-report-from-ledger.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** — including the cache-token decision

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.5)
**Date**: 2026-08-31
**Notes**: Reshaped `usage_report.py` to node → cycle → worker: added
`CycleUsage` (one retained ledger record: `cycle`, `model`, tokens,
`duration_seconds`, `status`, `error_type`), reshaped `AgentUsage` to add
`cycles: list[CycleUsage]` and `failures: int`, and added `partial`/
`partial_reason` to `UsageReport` (§8 Q1). Deleted
`_single_worker_summary_for_node` entirely (its only caller was the old
`build_usage_report`, also rewritten) — `grep -rn
_single_worker_summary_for_node` across `packages/ai-parrot/` now returns
nothing. Rewrote `build_usage_report(ledger: RunLedgerRecorder, run_id: str)
-> UsageReport`: iterates `ledger.by_seat()` through a new `_ordered_seats()`
helper (stable order — groups by `node_id` in first-appearance order, bare
node before its pool workers, workers sorted by seat name), maps each
`SeatUsage` to an `AgentUsage` (`backend` sourced from `SeatUsage.provider`
— see cache-token note below for why not `client_name`) and each of its
retained `UsageRecord` cycles to a `CycleUsage` (tokens null'd out when
`usage_reported=False`, never coerced), and reads `ledger.partial`/
`.partial_reason` straight onto the report. Totals still use the existing
`_sum_optional_int` (`run_bundle.py`); added a `duration_seconds` sum via
the existing `_sum_optional_float` (also `run_bundle.py`, already existed —
not newly added). `render_usage_markdown`/`render_usage_html` both gained a
visible "⚠️ Partial usage report" banner when `report.partial` (§8 Q1's
"never present a short total as complete"); the column set (Seat/Node/
Backend/Model/Rounds/Tokens/Duration) is otherwise unchanged, satisfying
"keep renderers importable and passing, even if temporarily rendering the
totals row only" without actually needing to fall back to a totals-only
render — TASK-2619's Failures section is additive on top of this.
`_persist_run_bundle`'s call site now does `ledger = self.get_run_ledger
(host.state.run_id)`; when `None` (cross-process resume, §8 Q1), constructs
a fresh `RunLedgerRecorder` and calls `mark_partial(...)` on it before
passing it to `build_usage_report` — this task's own "missing ledger"
handling lives at the call site, not inside `build_usage_report` itself
(kept pure, per the Key Constraints). Verified the ledger is still present
at this point because `_discard_run_registry` (TASK-2616) runs strictly
*after* `_close_host`/`_persist_run_bundle` returns in all three of
`run()`/`_run_feature()`/`run_revision()`.

Rewrote `test_usage_report.py` fully onto ledger-based fixtures: kept
`TestRendering`/`TestSerialization` unchanged (they exercise `UsageReport`/
renderers directly, not the builder); rewrote `TestBuild` onto a new
`ledger_with_two_agents` async fixture plus the task's own 6-test Test
Specification verbatim (`test_report_sums_cycles_per_seat`,
`test_report_includes_pool_workers`, `test_report_never_fabricates_zero`,
`test_empty_ledger_yields_valid_report`, `test_partial_flag_propagates`,
`test_single_worker_summary_helper_is_gone`), plus one extra
(`test_failed_cycle_retained_and_counted`); **deleted**
`test_single_worker_summary_supplies_model`,
`test_ambiguous_multi_worker_leaves_model_blank`, and
`test_no_shared_leaves_model_blank` — all three tested the now-deleted
pool-size-1 heuristic directly, and are obsolete by design (the model
arrives as real per-seat data now, not a guess); `TestBundleIntegration`
kept its own `Snapshot` fixture (unrelated to usage_report — it exercises
`build_run_bundle`) but now builds the usage half from
`ledger_with_two_agents`. All 20 tests pass.

**Deviation not in the task's declared scope**: `test_nova_integration.py`
(`TestUsageArtifacts::test_usage_report_written_at_run_end`) called
`build_usage_report(snapshot, run_id=...)` with the OLD signature and broke
immediately (`AttributeError: 'Snapshot' object has no attribute
'by_seat'`) — a direct, unavoidable consequence of this task's required
signature change, not a pre-existing issue. Rewrote its `_completed_snapshot`
usage into an async `_completed_ledger()` helper feeding
`build_usage_report`, and kept a slimmed-down `_completed_snapshot()` (now
just `RunCreated`/`NodeStarted`/`NodeCompleted`/`RunClosed`, no `Dispatch*`
actions — `DevLoopSessionState.nodes` verified empty-by-default, so a bare
lifecycle sequence is enough) purely to keep the test's OWN separate
`build_run_bundle(...)` sanity assertion (`bundle.nodes` truthy, unrelated
to usage_report) working. Removed the now-unused `DispatchCompleted`/
`DispatchQueued`/`DispatchStarted` imports. All 7 tests in that file pass.
Per CLAUDE.md/WORKFLOW.md "run pytest after any logic change — no
exceptions" and this feature's own precedent (TASK-2614's `test_bootstrap.py`
fix), documented here rather than silently expanding the task's file list.

**Cache-token columns**: **dropped** (option 1, the task's stated
preference). `UsageRecord` (the ledger's per-cycle unit) does not carry
`cache_creation_input_tokens`/`cache_read_input_tokens` at all
(`recorders/models.py`) — only `DispatchState` did, and that plane is
explicitly out of scope for this feature (session state stays the
live-UI-only projection). Neither `AgentUsage` nor `CycleUsage` carries
these fields; `render_usage_markdown`/`render_usage_html`'s column sets are
unchanged (they never rendered these columns as their own — they were
folded into the combined "Tokens" cell's underlying `input_tokens`/
`output_tokens` only, per the pre-existing `_fmt_agent_tokens`/
`_fmt_agent_tokens_html` helpers, both untouched). No renderer change was
needed to honor this decision — it falls out naturally from `CycleUsage`
simply not having the fields to render.

**Deviations from spec**: `AgentUsage.backend` is sourced from
`SeatUsage.provider` (`recorders/run_ledger.py`'s roll-up), not from a raw
`client_name`-equivalent — `SeatUsage` (a file NOT in this task's declared
scope) does not expose `client_name`, only the normalized `provider` (the
`gen_ai.system` value, e.g. `"anthropic"`/`"openai"`, resolved via
`resolve_gen_ai_system`). This is a slightly different identifier than the
pre-FEAT-479 report's `backend` (which came from `DispatchState.dispatcher`,
e.g. `"claude-code"`/`"nova"` — the dispatcher class name). Both answer
"which backend served this seat," just at a different normalization layer;
widening `SeatUsage` to also carry `client_name` would require touching
`recorders/run_ledger.py`, outside this task's file list.
