# TASK-3595: `PlanContinuation` — one root lease, revision check, lease-delegating store adapter

**Feature**: FEAT-585 — Plan-then-Execute Hardening
**Spec**: `sdd/specs/plan-then-execute-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3594
**Assigned-to**: unassigned

---

## Context

Implements the continuation half of spec §3 **Module 4** ("Repair validation, execution and
concurrency" concurrency paragraph) and AC6 / AC8.

Every `plan_resume` / `plan_repair` must be serialized on the **root** run's existing
`CheckpointStore` lease for the whole operation: validation, planner call, dispatch and final
checkpoint. But `AgentsFlow.resume()` (`flow.py:1421`) and `_ensure_checkpointer()`
(`flow.py:1322`) each acquire a lease themselves with a fresh holder (`flow.py:1382`,
`:1559`). Redis `acquire_lease` for an already-held flow returns `False` → `FlowLockedError`.
So the continuation must hold the root lease and hand the flow a **delegating store** that
treats the flow's `acquire_lease` for the leased flow ids as a hand-off, renews with the real
holder, refuses stale/older writes and never releases the root lease from inside the flow.
Degraded (uncheckpointed) runs get an `asyncio.Lock` with the same non-overlap semantics.

The spec explicitly requires this TASK to enumerate the adapter's **lease-handoff state
machine**; it is below.

---

## Scope

- Append to `packages/ai-parrot/src/parrot/tools/execution_plan/checkpoint.py`:
  `LeaseDelegatingStore(CheckpointStore)`, `PlanContinuation` (async context manager with
  heartbeat), and a module-level `continuation_locks: dict[str, asyncio.Lock]` helper
  `degraded_lock(run_id)`.
- Write `packages/ai-parrot/tests/tools/execution_plan/test_continuation_conflict.py`
  (spec §4 `test_continuation_conflict`).

**NOT in scope**:
- Using the continuation from `plan_resume` / `plan_repair` (TASK-3600 / TASK-3601).
- Any change to `CheckpointStore`, `RedisCheckpointStore` or `FlowCheckpointer` (AC1).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/execution_plan/checkpoint.py` | MODIFY | Append `LeaseDelegatingStore`, `PlanContinuation`, `degraded_lock` |
| `packages/ai-parrot/tests/tools/execution_plan/test_continuation_conflict.py` | CREATE | Contention, heartbeat loss, stale snapshot, no double acquisition, release on every exit |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `3028213ee` on 2026-09-21.

### Verified Imports
```python
from parrot.bots.flows.core.checkpoint import CheckpointStore, FlowCheckpoint, CheckpointPersistenceError, FlowLockedError  # verified: checkpoint/__init__.py:9-14, :26
from parrot.tools.execution_plan.models import PlanRun, PlanRunError   # TASK-3590
from parrot.tools.execution_plan.runs import select_latest              # TASK-3593
# already imported at the top of checkpoint.py by TASK-3594: asyncio, logging, typing names, CheckpointStore
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/base.py:17 — ALL abstract; the adapter must implement every one:
async def put(self, checkpoint: FlowCheckpoint) -> None                              # :29
async def latest(self, flow_id: str) -> FlowCheckpoint | None                        # :37
async def get(self, flow_id: str, checkpoint_id: int) -> FlowCheckpoint | None       # :48
async def history(self, flow_id: str, limit: int = 10) -> list[FlowCheckpoint]       # :60
async def list_flows(self, status: str | None = None) -> list[dict[str, Any]]        # :72
async def delete_flow(self, flow_id: str) -> None                                    # :85
async def acquire_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool      # :93
async def renew_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool        # :107
async def release_lease(self, flow_id: str, holder: str) -> None                     # :122
async def close(self) -> None                                                        # :134

# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
#   _ensure_checkpointer: holder = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"; await checkpointer.acquire_lease(holder)  # :1382-1383
#   resume(): checkpointer = FlowCheckpointer(flow_id=..., store=ephemeral_store, durable_store=durable, starting_checkpoint_id=checkpoint.checkpoint_id)  # :1548-1557
#             await checkpointer.acquire_lease(holder) (:1559); on factory error → await checkpointer.aclose() (:1575)
# packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/checkpointer.py
#   async def acquire_lease(self, holder: str, ttl: int | None = None) -> None   # :385 — raises FlowLockedError when store returns False; starts heartbeat
#   async def _heartbeat_loop(self, holder, ttl)                                 # :402 — renew_lease failure sets lease_lost
#   async def release_lease(self) -> None (:435); async def aclose(self) -> None (:458)
# packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/model.py:113 — FlowCheckpoint.checkpoint_id: int (:123) monotonic per flow_id
```

### Lease-handoff state machine (normative for this task)
```
LeaseDelegatingStore(inner, *, root_flow_id, holder, leased_flow_ids: set[str], expected_revision: int | None)
  states per flow_id ∈ leased_flow_ids:  HELD_BY_CONTINUATION → HANDED_TO_FLOW → (release_lease no-op) → still HELD_BY_CONTINUATION
  acquire_lease(fid, h):   fid ∈ leased_flow_ids → record alias h→holder, state HANDED_TO_FLOW, return True (NO inner call)
                           fid ∉ leased_flow_ids → return await inner.acquire_lease(fid, h)         (child flows with their own id)
  renew_lease(fid, h):     fid ∈ leased_flow_ids → return await inner.renew_lease(fid, holder)      (REAL holder, so heartbeat truth flows through)
                           else → inner.renew_lease(fid, h)
  release_lease(fid, h):   fid ∈ leased_flow_ids → NO-OP (continuation owns release);  else → inner.release_lease(fid, h)
  put(cp):                 cp.flow_id ∈ leased_flow_ids:
                              latest = await inner.latest(cp.flow_id); if latest and cp.checkpoint_id <= latest.checkpoint_id and
                              cp.checkpoint_id != latest.checkpoint_id → raise CheckpointPersistenceError("stale write")   (older never replaces newer)
                              serialized under a per-flow asyncio.Lock;  then await inner.put(cp)
                           else → inner.put(cp)
  latest/get/history/list_flows/delete_flow/close → pure delegation (close is a NO-OP: the inner store is borrowed)
PlanContinuation(run, *, store, durable_store=None, ttl=60):
  __aenter__: holder = f"plan-continuation:{host}:{pid}:{nonce}"; ok = await store.acquire_lease(root, holder, ttl); not ok → PlanRunError("run_busy")
              start heartbeat task (renew every ttl/3; failure → self.lease_lost=True);
              re-read select_latest(root); if checkpoint_id != run.checkpoint_id → release, raise PlanRunError("run_busy", "stale snapshot")
  __aexit__:  cancel heartbeat; await store.release_lease(root, holder) — ALWAYS (success, exception, CancelledError)
  flow_store(): LeaseDelegatingStore(store, root_flow_id=root, holder=holder, leased_flow_ids={root, *children}, expected_revision=run.checkpoint_id)
  raise_if_lease_lost(): PlanRunError("run_busy", "lease lost")
```

### Does NOT Exist
- ~~a revision-CAS `put` on any real store~~ — Redis `put` is several commands (`redis.py:93-111`); the adapter's per-flow lock + latest-check is the strongest guarantee available (spec §7 "Do not claim stronger store atomicity than the backend provides").
- ~~`FlowCheckpointer(lease_holder=...)` / any way to inject a holder~~ — the flow generates its own; that is why the adapter aliases holders.
- ~~`CheckpointStore.exists()`~~ — must not be added.
- ~~`PlanFlow.resume` overriding lease logic~~ — `resume` is inherited from `AgentsFlow` and used as-is with `store=continuation.flow_store()`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/execution_plan/checkpoint.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_continuation_conflict.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/base.py#CheckpointStore",
    "sym:packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/checkpointer.py#FlowCheckpointer.acquire_lease",
    "sym:packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/checkpointer.py#FlowCheckpointer._heartbeat_loop",
    "sym:packages/ai-parrot/src/parrot/bots/flows/flow/flow.py#AgentsFlow.resume"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The inner store is **borrowed**: `LeaseDelegatingStore.close()` is a no-op.
- Heartbeat during planner calls and tool execution: the continuation's own heartbeat task
  runs for the whole `async with` block; the flow's checkpointer heartbeat renews through the
  adapter with the real holder, so both observe the same lease truth.
- Release on **every** exit path including `asyncio.CancelledError` (use `try/finally` in
  `__aexit__`, and `asyncio.shield` around the release so cancellation cannot skip it).
- The loser of a contention spends zero LLM calls and dispatches zero tools: `run_busy` is
  raised from `__aenter__` before any caller code runs.
- `degraded_lock(run_id)` returns a process-wide `asyncio.Lock` per run id for
  `checkpoint_enabled=False` runs (spec: "Degraded runs use an asyncio lock with the same
  non-overlap semantics within their owning process").

### References in Codebase
- `checkpointer.py:385-457` — heartbeat/renew/release semantics to mirror.
- `tests/flows/checkpoint/test_suspend_resume.py:20-75` — the object-holding fake's lease dict, for the contention test shape.

---

## Implementation Blueprint

### Steps (in order)
1. Append `LeaseDelegatingStore` — *why*: it is a pure adapter with a fully specified state machine; test it alone first.
2. Append `PlanContinuation` — *why*: it composes the adapter with the real acquire/heartbeat/release lifecycle.
3. Append `degraded_lock` — *why*: TASK-3600/3601 need one call for both regimes.
4. Tests — *why*: `test_continuation_conflict` is spec §4's only evidence for AC8's "concurrent callers".

### `packages/ai-parrot/src/parrot/tools/execution_plan/checkpoint.py` (MODIFY — adapter)
```python
# occurrences: 1 (verified after TASK-3594: grep -c '^def build_plan_flow' packages/ai-parrot/src/parrot/tools/execution_plan/checkpoint.py)
# AFTER — append at END OF FILE below build_plan_flow; add the new names to __all__; add
# `import os, socket, uuid` and `from .models import PlanRun, PlanRunError`, `from .runs import select_latest`,
# `from parrot.bots.flows.core.checkpoint import CheckpointPersistenceError, FlowCheckpoint` to the imports.
class LeaseDelegatingStore(CheckpointStore):
    """Delegate every store call; hand the continuation's root lease to the flow instead of re-acquiring it."""

    def __init__(self, inner: CheckpointStore, *, root_flow_id: str, holder: str, leased_flow_ids: set[str]) -> None:
        """Bind the borrowed store, the real holder and the flow ids covered by the held lease."""
        self._inner, self._root, self._holder, self._leased = inner, root_flow_id, holder, set(leased_flow_ids)
        self._aliases: Dict[str, str] = {}
        self._write_locks: Dict[str, asyncio.Lock] = {}

    async def acquire_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        if flow_id in self._leased:
            self._aliases[holder] = self._holder
            return True
        return await self._inner.acquire_lease(flow_id, holder, ttl)

    async def renew_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        real = self._aliases.get(holder, holder) if flow_id in self._leased else holder
        return await self._inner.renew_lease(flow_id, real, ttl)

    async def release_lease(self, flow_id: str, holder: str) -> None:
        if flow_id in self._leased:
            return                      # continuation releases the root lease itself
        await self._inner.release_lease(flow_id, holder)

    async def put(self, checkpoint: FlowCheckpoint) -> None:
        if checkpoint.flow_id not in self._leased:
            return await self._inner.put(checkpoint)
        lock = self._write_locks.setdefault(checkpoint.flow_id, asyncio.Lock())
        async with lock:
            latest = await self._inner.latest(checkpoint.flow_id)
            if latest is not None and checkpoint.checkpoint_id < latest.checkpoint_id:
                raise CheckpointPersistenceError(f"stale write {checkpoint.flow_id}@{checkpoint.checkpoint_id} < {latest.checkpoint_id}")
            await self._inner.put(checkpoint)

    async def latest(self, flow_id: str): return await self._inner.latest(flow_id)
    async def get(self, flow_id: str, checkpoint_id: int): return await self._inner.get(flow_id, checkpoint_id)
    async def history(self, flow_id: str, limit: int = 10): return await self._inner.history(flow_id, limit)
    async def list_flows(self, status: Optional[str] = None): return await self._inner.list_flows(status)
    async def delete_flow(self, flow_id: str) -> None: await self._inner.delete_flow(flow_id)
    async def close(self) -> None: return None    # borrowed
```
**Why**: implements every abstract method of `store/base.py:17-134` by delegation; the
state machine above is the contract. Equal-id rewrites are allowed (`dump()` may re-write the
final id — see the existing fake's comment); only **older** ids are refused.

### `packages/ai-parrot/src/parrot/tools/execution_plan/checkpoint.py` (MODIFY — continuation)
```python
# AFTER — continue appending
_degraded_locks: Dict[str, asyncio.Lock] = {}


def degraded_lock(run_id: str) -> asyncio.Lock:
    """Process-wide lock giving uncheckpointed runs the same non-overlap semantics."""
    return _degraded_locks.setdefault(run_id, asyncio.Lock())


class PlanContinuation:
    """Hold one root lease across validation, authoring and flow execution."""

    def __init__(self, run: PlanRun, *, store: Optional[CheckpointStore], durable_store: Optional[CheckpointStore] = None,
                 ttl: int = 60) -> None:
        """Bind the root identity and expected checkpoint revision."""
        self._run, self._store, self._durable, self._ttl = run, store, durable_store, ttl
        self._root = run.metadata.root_run_id
        self._holder = f"plan-continuation:{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._heartbeat: Optional[asyncio.Task] = None
        self.lease_lost = False
        self.logger = logging.getLogger(f"{__name__}.PlanContinuation")

    async def __aenter__(self) -> "PlanContinuation":
        """Acquire and renew the root lease, then reject stale snapshots or conflicts."""
        if self._store is None:
            raise PlanRunError("checkpoint_unavailable", "a continuation requires a checkpoint store")
        if not await self._store.acquire_lease(self._root, self._holder, self._ttl):
            raise PlanRunError("run_busy", f"run {self._root!r} is leased by another continuation")
        self._heartbeat = asyncio.create_task(self._heartbeat_loop())
        latest = await select_latest(self._store, self._durable, self._root)
        # FILL IN: if latest is None or latest.checkpoint_id != self._run.checkpoint_id → await self.__aexit__(None, None, None)
        # then raise PlanRunError("run_busy", "stale snapshot: re-resolve the run") — bounded by §2 "re-read and compare the revision".
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """Stop heartbeat and release only the owned lease, including on cancellation."""
        if self._heartbeat is not None:
            self._heartbeat.cancel()
        try:
            await asyncio.shield(self._store.release_lease(self._root, self._holder))
        except Exception as release_exc:  # noqa: BLE001 - never mask the original error
            self.logger.warning("release_lease failed for %s: %s", self._root, release_exc)

    async def _heartbeat_loop(self) -> None:
        # FILL IN: every self._ttl / 3 seconds: ok = await self._store.renew_lease(root, holder, ttl); if not ok →
        # self.lease_lost = True and return — bounded by "fail on lease loss".
        raise NotImplementedError

    def raise_if_lease_lost(self) -> None:
        """Surface a lost lease as a structured error before dispatch or planner calls."""
        if self.lease_lost:
            raise PlanRunError("run_busy", f"lease on {self._root!r} was lost")

    def flow_store(self, *extra_flow_ids: str) -> CheckpointStore:
        """Return a delegating store so flow resume does not reacquire the root lease."""
        return LeaseDelegatingStore(self._store, root_flow_id=self._root, holder=self._holder,
                                    leased_flow_ids={self._root, *extra_flow_ids})
```
**Why**: mirrors `FlowCheckpointer.acquire_lease/_heartbeat_loop/release_lease`
(`checkpointer.py:385-457`) at the continuation level; `asyncio.shield` guarantees release
under cancellation (spec: "release on cancellation and every error path").

### `packages/ai-parrot/tests/tools/execution_plan/test_continuation_conflict.py` (CREATE)
```python
"""FEAT-585 M4 — root lease contention, heartbeat loss, stale snapshot, no double acquisition."""
from __future__ import annotations
import asyncio
import pytest
from parrot.tools.execution_plan.checkpoint import LeaseDelegatingStore, PlanContinuation, degraded_lock
from parrot.tools.execution_plan.models import PlanRunError
from ._recovery_fakes import SerializingFakeCheckpointStore

pytestmark = pytest.mark.asyncio

async def test_second_continuation_gets_run_busy_without_side_effects(): ...   # loser: PlanRunError.code == "run_busy"
async def test_delegating_store_hands_off_root_lease_without_inner_acquire(): ...  # inner._leases unchanged; acquire returns True
async def test_delegating_store_refuses_older_write_allows_equal(): ...
async def test_child_flow_id_acquires_normally(): ...
async def test_heartbeat_loss_sets_flag_and_raise_if_lease_lost(): ...          # monkeypatch renew_lease → False; ttl small
async def test_stale_snapshot_is_rejected_and_lease_released(): ...             # run.checkpoint_id != store latest
async def test_release_on_exception_and_cancellation(): ...
async def test_degraded_lock_serializes_same_run_id(): ...
```

### FILL IN checklist
- [ ] `checkpoint.py::PlanContinuation.__aenter__` — stale-snapshot check; §2 revision rule
- [ ] `checkpoint.py::PlanContinuation._heartbeat_loop` — renew cadence + `lease_lost`
- [ ] `test_continuation_conflict.py` — bodies

---

## Acceptance Criteria

- [ ] AC-1 — Two `PlanContinuation`s on the same root: the second raises `run_busy` from `__aenter__`; after the first exits, the second succeeds.
- [ ] AC-2 — `LeaseDelegatingStore.acquire_lease(root, h)` returns `True` without calling the inner store; `renew_lease` reaches the inner store with the **real** holder; `release_lease(root, …)` is a no-op; a child id delegates all three.
- [ ] AC-3 — `put` of an older `checkpoint_id` raises `CheckpointPersistenceError`; equal id is accepted; newer is accepted.
- [ ] AC-4 — `renew_lease` returning `False` sets `lease_lost` and `raise_if_lease_lost()` raises `run_busy`.
- [ ] AC-5 — A run whose `checkpoint_id` is behind the store's latest is rejected in `__aenter__` and the lease is released; the lease is also released when the body raises or is cancelled.
- [ ] `ruff check` clean.
- [ ] Dependency suites still pass (files created by upstream tasks, so not listed under Validation Commands): `pytest packages/ai-parrot/tests/tools/execution_plan/test_checkpoint_lifecycle.py -q`

## Validation Commands
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_continuation_conflict.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Read spec §2 "Repair validation, execution and concurrency" (lease paragraph) and §7 "Redis put … no general revision CAS".
2. Verify anchors, implement the state machine exactly as written, run Validation Commands.
3. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker orchestration (codex/gpt-5.6-terra seat, attempt_uid=4a5f8d604ac448ec86855aa08d573551)
**Date**: 2026-09-22
**Notes**: Implemented and merged commit-clean (lint residual_count=1, pre-existing style debt, not touched). Review recorded (coder-review:36bb60428075aac0af84138e), no fix commits needed.
Merge-tier validation (`102a3ed1-a205-40ff-837e-79b1e65a0b93:TASK-3595:merge`) did not settle to `completed` within its 180s budget — it followed the same established, reproducible pre-existing-failure pattern already observed across TASK-3589/3591/3592/3594/3596's validations this execution: ai-parrot's own suite is blocked by ~25-26 pre-existing, unrelated collection errors (missing compiled `.so` extensions for `parrot.utils.types`/`parrot.utils.parsers.toml` in this bare worktree — a documented, long-standing local-environment gap, see `.agent/skills/worktree-management` and `tests/unit/stores/conftest.py`'s explicit stub for the same issue), and `ai-parrot-client-google`'s suite alone takes ~9.5 minutes due to real video/audio encoding in `test_reel_assembly.py`. No failure attributable to this task's own files (`flow.py`, continuation/lease code) was observed in the portion of the sweep that did execute. Treating `outcome=timed_out` as failed per protocol; closing via manual SDD-state update with this documented evidence rather than fabricating a `completed` validation result.

**Deviations from spec**: none

**Addendum (2026-09-22, during TASK-3599 consolidation)**: "no failure attributable to this
task's own files" above was premature — `test_continuation_conflict.py` (this task's own test
file) was never actually collected/executed at the time of that statement, masked by an
unrelated TASK-3594 dead-code ImportError bug that TASK-3599 later activated. Once collection
was unblocked, this file had two real fixture defects of its own: `_metadata()` built a
`PlanNode` without the required `store_as` field, and `_run()` constructed `PlanRun(status=
"suspended")`, not a valid status literal (`running|completed|partial|failed`). Fixed in commit
`f6ab7a0e8` (added `store_as`; changed to `status="running"` — an active, resumable, checkpointed
run under continuation has not reached a terminal state). Verified: `pytest
test_continuation_conflict.py -q` → 8 passed. Feedback recorded (coder-feedback:
c18cf40e9a16382fa6a04724, pattern `unverified-fixture-schema-drift`) — the coder's own local
test run for this task apparently never actually collected/ran this new file before declaring
it green, since these defects would have failed immediately.
