# TASK-1851: DevLoopRunner as AHP-style host — registry, root catalogue, sweep, commands

**Feature**: FEAT-322 — AHP-style Session State, Host & HITL Approval Gates for dev-loop
**Spec**: `sdd/specs/agent-host-protocol-session-state.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1849
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. `DevLoopRunner` becomes the AHP-style host: it owns one
`SessionHost` per run (registry keyed by run_id — NEVER a captured
reference, because one `AgentsFlow` serves concurrent runs), the
root-channel run catalogue, the envelope sink to Redis, the gate-expiry
sweep, and the command methods the REST layer (TASK-1855) adapts.

---

## Scope

Modify `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py`:

- **Host registry**: `self._hosts: Dict[str, SessionHost]`; public
  `get_host(run_id) -> Optional[SessionHost]`.
- **Root catalogue**: `self._registry: RunRegistryState`; public
  `registry_state` property. Fold `RunAdded` on run start,
  `RunSummaryChanged` on phase/summary changes (derive `RunSummary` from
  the host's state incl. `pending_gate_count`), `RunRemoved` when the host
  is discarded after terminal handling.
- **Lifecycle wiring** in `run()` (:153) and `run_revision()` (:211):
  - before `run_flow`: create `SessionHost(rid, on_envelope=<sink>)`,
    register it, `host.apply(RunCreated(run_id=rid, revision=..., work_kind=brief.kind, summary=brief.summary))`,
    apply `RunAdded` to the root registry, and seed
    `shared["session_host"] = host` (nodes read it from shared state —
    nodes never import the runner).
  - after `run_flow` (in `finally`/post): apply `RunClosed` with outcome
    mapped from `result.status` + known jira/pr fields; persist the
    terminal `Snapshot` as a run artifact (JSON file under the run's
    artifacts dir or logger-documented location); schedule stream deletion
    per retention; apply `RunSummaryChanged`/`RunRemoved`.
- **Envelope sink**: async-safe callable that XADDs
  `envelope.model_dump_json()` to `flow:{rid}:actions` with
  `maxlen=100_000, approximate=True`; lazy Redis from `self._redis_url`;
  EVERY failure swallowed and logged (never break a run). If
  `self._redis_url` is None → sink is a no-op (host still folds in-memory).
- **Expiry sweep**: one `asyncio.Task` per active run (or a single periodic
  task iterating `_hosts`) calling `host.expire_due_gates()` every ~30s;
  started when the first run registers, cancelled cleanly when the runner
  has no active runs. Sweep failures swallowed.
- **Command methods**:
  - `async def resolve_gate(self, run_id, gate_id, resolution, resolved_by, comment="") -> ActionEnvelope`
    — look up host (KeyError with clear message if unknown run), delegate to
    `host.resolve_gate` (exceptions propagate for the REST layer to map).
  - `async def cancel_run(self, run_id, requested_by) -> ActionEnvelope` —
    `host.apply(RunCancelled(requested_by=requested_by))`.
- **Conf keys** in `packages/ai-parrot/src/parrot/conf.py` (near the
  existing dev-loop block at :925):
  `DEV_LOOP_GATE_TTL_DEPLOYMENT=86400`, `DEV_LOOP_GATE_TTL_MANUAL=259200`,
  `DEV_LOOP_GATE_TTL_REVISION=86400`, `DEV_LOOP_GATE_TTL_PLAN=14400`
  (ints, seconds), `DEV_LOOP_ACTIONS_RETENTION_DAYS=7`. Expose a small
  helper `gate_ttl_for(kind) -> int` in session_state or runner (runner
  preferred — conf stays out of the pure module).
- Export new public names from `parrot/flows/dev_loop/__init__.py`
  (`SessionHost`, `ActionEnvelope`, `Snapshot`, state models, exceptions).
- Unit tests (`test_runner.py` extend / new `test_runner_host.py`):
  lifecycle (host created/removed, RunAdded/RunClosed folded), registry
  isolation for two concurrent runs (distinct hosts, distinct streams),
  resolve_gate routing + unknown-run error, cancel terminal-sticky,
  sink-failure resilience (fake redis raising), legacy
  `DevLoopRunner(flow)` construction still works with hosts active and
  sink disabled (no redis_url).

**NOT in scope**: publisher/dispatcher shims (TASK-1852); node gate opening
(TASK-1853); REST endpoints (TASK-1855); streaming (TASK-1854).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | MODIFY | host registry + lifecycle + sweep + commands |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | 5 new conf keys (dev-loop block, :925 area) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py` | MODIFY | export session-state public names |
| `packages/ai-parrot/tests/flows/dev_loop/test_runner_host.py` | CREATE | host-lifecycle unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.session_state import (      # TASK-1848/1849
    ActionEnvelope, ActionOrigin, RunAdded, RunCancelled, RunClosed,
    RunCreated, RunRegistryState, RunRemoved, RunSummary,
    RunSummaryChanged, SessionHost, Snapshot, reduce_root,
)
from parrot import conf                                # runner.py:25 (existing)
import redis.asyncio as aioredis                       # lazy-import pattern, flow.py:125
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
class DevLoopRunner:                                            # :100
    def __init__(self, flow, *, max_concurrent_runs=None, dispatcher=None,
                 jira_toolkit=None, git_toolkit=None, redis_url=None,
                 codereview_dispatcher=None) -> None: ...       # :109
    # self._semaphore = asyncio.Semaphore(...)  :126
    # self._active: Set[str]                    :127
    # self._redis_url stored                    :134
    active_runs: Set[str]                                       # property :143
    def is_active(self, run_id: str) -> bool: ...               # :147
    async def run(self, brief: WorkBrief, *, run_id=None, initial_task="",
                  extra_shared=None) -> FlowResult: ...         # :153
        # rid = run_id or f"run-{uuid4().hex[:8]}"              :177
        # shared = {"bug_brief","work_brief","run_id"}          :178-182  ← seed session_host HERE
        # async with self._semaphore: ... run_flow(ctx) ... finally discard  :191-204
    async def run_revision(self, brief: RevisionBrief, *, run_id=None)
                  -> FlowResult: ...                            # :211 (rid rev-<hex8> :245; shared :284-297)

# WorkBrief fields used for RunSummary/RunCreated (models.py:118):
#   kind, summary, escalation_assignee (:161)
# FlowResult has .status (runner.py:207 logs it) — map to RunClosed outcome:
#   verify actual status values via parrot/bots/flows/core/result.py before use
# conf.py dev-loop block anchor: DEV_LOOP_JIRA_TRANSITIONS_READY :925
# XADD pattern to copy: flow.py:113-118 (maxlen=..., approximate=True, swallow)
# __init__.py current exports: FlowEventPublisher :25, DevLoopRunner :26,
#   FlowStreamMultiplexer/flow_stream_ws :28-31, __all__ block :78-84
```

### Does NOT Exist
- ~~`DevLoopRunner._hosts` / `.get_host` / `.registry_state` / `.resolve_gate` / `.cancel_run`~~ — this task creates them
- ~~`DEV_LOOP_GATE_TTL_*` / `DEV_LOOP_ACTIONS_RETENTION_DAYS` in conf.py~~ — verified absent 2026-07-21; this task adds them
- ~~`flow:{run_id}:actions` stream~~ — new
- ~~a runner-owned aiohttp app~~ — REST wiring is TASK-1855, not here
- ~~`FlowResult.outcome`~~ — the field is `status`; verify its Literal values in `parrot/bots/flows/core/result.py` before mapping

---

## Implementation Notes

### Key Constraints
- Registry-based host resolution is the load-bearing design decision
  (spec §2, §7 Patterns): `run()` seeds `shared["session_host"]`; shims and
  nodes resolve per run — never store "the current host" on the flow.
- The sink is passed INTO SessionHost as `on_envelope`; the host stays
  transport-free.
- Semaphore semantics unchanged (spec §8: `awaiting_gate` keeps its slot).
- Terminal snapshot: `host.snapshot().model_dump_json()` — where run
  artifacts live is implementer's choice but must be logged at INFO with the
  path; retention deletion may be a TODO-logged stub if the finished-run
  sweep utility is not found (verify what exists — do NOT invent
  `sweep_finished_worktrees` imports; see spec §6 Does-NOT-Exist).
- Preserve legacy behavior: everything new is additive and guarded so
  `DevLoopRunner(flow)` (no redis_url, no deps) still runs (tests exist:
  `packages/ai-parrot/tests/flows/dev_loop/test_runner.py`).

---

## Acceptance Criteria

- [ ] `run()`/`run_revision()` create + register a host, apply RunCreated/RunAdded, seed `shared["session_host"]`, and on completion apply RunClosed + persist terminal snapshot + update root registry
- [ ] Two concurrent runs: distinct hosts, distinct `flow:{rid}:actions` streams, no cross-contamination (test with fake redis)
- [ ] `resolve_gate`/`cancel_run` route to the right host; unknown run → clear KeyError
- [ ] Expiry sweep fires policies (observable via injected short TTL in test)
- [ ] Sink failures swallowed; state still folds in-memory (fake redis raising on xadd)
- [ ] Legacy `DevLoopRunner(flow)` construction + existing `test_runner.py` pass unchanged
- [ ] 5 conf keys added with documented defaults; `gate_ttl_for(kind)` helper
- [ ] New names exported from `parrot.flows.dev_loop`; `ruff check` clean
- [ ] Tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_runner_host.py
async def test_run_creates_and_closes_host(fake_flow, fake_redis): ...
async def test_registry_isolation_two_concurrent_runs(...): ...
async def test_resolve_gate_routes_to_host(...): ...
async def test_cancel_run_terminal_sticky(...): ...
async def test_sink_failure_swallowed_state_folds(...): ...
def test_legacy_construction_no_redis(...): ...
```

---

## Agent Instructions

1. Read spec §2 Overview + §3 M3 + §7. Verify TASK-1849 completed.
2. RE-VERIFY runner.py line anchors (file is active — FEAT-270 era churn).
3. Check `FlowResult.status` values in `parrot/bots/flows/core/result.py`.
4. Implement; run full dev_loop tests; move to completed; update index.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-22
**Notes**: `DevLoopRunner` now owns `_hosts: Dict[run_id, SessionHost]` +
`_registry: RunRegistryState`, with `get_host`/`registry_state`/
`resolve_gate`/`cancel_run` per the contract. `run()`/`run_revision()`
create+register a host before `run_flow`, apply `RunCreated`+`RunAdded`,
seed `shared["session_host"]`; on completion (`_close_host`) apply
`RunClosed` (outcome mapped from `FlowResult.status`: `completed`→
`succeeded`, `partial`/`failed`→`failed`), persist the terminal
`Snapshot` under `conf.OUTPUT_DIR/dev_loop_runs/{run_id}.snapshot.json`,
schedule actions-stream retention, fold `RunSummaryChanged`, then discard
the host + fold `RunRemoved` — the host is NOT kept until retention (the
`view="state"` multiplexer, TASK-1854, falls back to replaying
`flow:{run_id}:actions` for a finished run). Envelope sink is a sync
`on_envelope` callback that schedules a best-effort background XADD task
(`flow:{run_id}:actions`, MAXLEN~100k) — never blocks `apply()`, every
failure swallowed+logged at DEBUG; no-op when `redis_url` is None. Gate
expiry + actions-stream retention share one periodic sweep
(`_sweep_loop`/`_sweep_once`, ~30s cadence, started on first host,
cancelled when none remain) rather than one asyncio task per run (avoids
leaking un-awaited multi-day sleeps). Added the 5 conf keys +
`gate_ttl_for(kind)` helper (in `runner.py`, keeps conf out of
`session_state.py`). Exported `SessionHost`, `ActionEnvelope`, `Snapshot`,
`ApprovalGate`, `DevLoopAction`, `DevLoopSessionState`, `RunRegistryState`,
`RunSummary`, `RootAction`, `ActionOrigin`, `GateNotFoundError`,
`GateAlreadyResolvedError`, `gate_ttl_for` from `parrot.flows.dev_loop`.
16 new tests in `test_runner_host.py`; all 7 pre-existing `test_runner.py`
tests still pass unchanged (legacy `DevLoopRunner(flow)` construction
verified). Full dev_loop suite: 460 passed (4 pre-existing unrelated
failures in `test_server_repo_wiring.py`/`test_webhook.py`, same as
before this task — verified in TASK-1850's note).

**Deviations from spec**:
1. **`packages/ai-parrot/tests/flows/dev_loop/conftest.py` modified**
   (not in this task's file list). The terminal-snapshot persistence
   this task adds writes real files under `conf.OUTPUT_DIR/dev_loop_runs/`
   on every completed run — without a fix, EVERY pre-existing test in this
   suite that drives a real run (not just the new host tests) would litter
   the actual repo's `outputs/` directory (confirmed: an initial run of
   `test_runner.py` created `outputs/dev_loop_runs/run-happy.snapshot.json`
   etc. in the real repo before this fix; cleaned up via `git clean -fd`).
   Added one autouse fixture (`_isolate_dev_loop_run_artifacts`) that
   monkeypatches `parrot.flows.dev_loop.runner.conf.OUTPUT_DIR` to
   `tmp_path` for every test in the module — a minimal, necessary fix for
   a regression this task's own change would otherwise cause.
2. **Snapshot artifact location** (`conf.OUTPUT_DIR/dev_loop_runs/`) was
   an implementer's choice per the task's own Implementation Notes
   ("where run artifacts live is implementer's choice"); reused the
   existing `conf.OUTPUT_DIR` convention rather than inventing a new conf
   key or directory.
3. **Actions-stream retention** implemented as entries in a
   `_pending_retention: Dict[run_id, delete_at]` dict checked by the same
   periodic sweep as gate expiry, rather than a long-lived per-run
   `asyncio.Task` sleeping for `DEV_LOOP_ACTIONS_RETENTION_DAYS` (7 days
   default) — a multi-day-sleeping task would not survive a process
   restart and would need explicit cancellation bookkeeping; the sweep
   approach is simpler, testable in isolation (`_sweep_once`), and
   equally correct for a v1 best-effort mechanism (spec §7 accepts
   Redis-side duplication/staleness during migration).
