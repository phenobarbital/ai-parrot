# TASK-3593: Checkpoint-derived run resolver (`runs.py`) and typed ArtifactRef registration

**Feature**: FEAT-585 — Plan-then-Execute Hardening
**Spec**: `sdd/specs/plan-then-execute-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3590
**Assigned-to**: unassigned

---

## Context

Implements the resolver half of spec §3 **Module 3** and goals D3–D5 / AC4 / AC5 / §8 D3.

The checkpoint is the **sole** persisted execution state. `ContextSnapshot.results`
(`checkpoint/model.py:65`) can carry `ArtifactRef`s only if the type is registered with
`register_checkpoint_type` (`serializer.py:43`); otherwise they degrade to a lossy repr
(finding R1). This task registers the type, reads the `plan_run` envelope from
`shared_data`, projects a `PlanRun` (typed refs, synthesized error refs, pending-vs-blocked,
recomputed counters, lineage), and resolves every agent-facing operation through one
`PlanRunResolver` that classifies misses **by configured tier capability** (`unknown_run`
when a durable tier is configured and `latest()` is `None`; `missing_or_expired` for
ephemeral-only) — no receipts, tombstones or side index.

This task also creates the shared recovery test fakes used by every later test file.

---

## Scope

- Create `packages/ai-parrot/src/parrot/tools/execution_plan/runs.py`:
  `register_plan_checkpoint_types()`, `plan_fingerprint(plan)`, `read_run_metadata(checkpoint)`,
  `project_run(checkpoint, *, metadata)`, `select_latest(store, durable_store, flow_id)`,
  `classify_miss(store, durable_store)`, `PlanRunResolver`.
- Create `packages/ai-parrot/tests/tools/execution_plan/_recovery_fakes.py`:
  `SerializingFakeCheckpointStore` (stores **real `FlowStateSerializer` bytes**), scripted
  planner client, counted fake tool manager, plan builders.
- Write `packages/ai-parrot/tests/tools/execution_plan/test_run_resolution.py`
  (spec §4 `test_artifact_ref_checkpoint_roundtrip`, `test_manifest_projection`,
  `test_resolver_refreshes_lineage`, and the M3 part of `test_scope_and_policy_rejection`).

**NOT in scope**:
- Writing checkpoints (TASK-3594) or acquiring leases (TASK-3595).
- Toolkit wiring of the resolver (TASK-3598).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/execution_plan/runs.py` | CREATE | Registration, projection, tier-aware resolver |
| `packages/ai-parrot/tests/tools/execution_plan/_recovery_fakes.py` | CREATE | Shared fakes (byte-serializing store, scripted planner, counted tools) |
| `packages/ai-parrot/tests/tools/execution_plan/test_run_resolution.py` | CREATE | Round-trip, projection, lineage, tier classification |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `3028213ee` on 2026-09-21.

### Verified Imports
```python
from parrot.bots.flows.core.checkpoint import (            # verified: checkpoint/__init__.py:8-30
    CheckpointStore, FlowCheckpoint, ContextSnapshot, FlowStateSerializer, register_checkpoint_type,
)
from parrot.bots.flows.plan import ArtifactRef, ExecutionManifest, ExecutionPlan, build_manifest  # verified: plan/__init__.py
from parrot.tools.execution_plan.models import (           # created by TASK-3590
    PLAN_RUN_SHARED_KEY, PlanRun, PlanRunError, PlanRunMetadata, PlanRunManifest, PlanRecoveryEnvelope, ResumeLevel,
)
from parrot.tools.working_memory.task_memory.models import TaskScope   # verified: models.py:571
# tests only:
from parrot.bots.flows.core.context import FlowContext          # verified: context.py:56
from parrot.bots.flows.flow.definition import FlowDefinition    # verified: used at tests/flows/checkpoint/test_required_persistence.py:31
from parrot.clients.base import AbstractClient                  # verified: tests/tools/execution_plan/test_planner.py:19
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/serializer.py
def register_checkpoint_type(model_cls: type[BaseModel], tag: str | None = None) -> str   # :43 — idempotent for same class; default tag = qualified name
class FlowStateSerializer:                                     # :90
    def to_safe_with_meta(self, obj) -> tuple[Any, bool]       # :269 — (safe, lossy)
    def from_safe(self, safe: Any) -> Any                      # :292 — returns registered model instance, or dict/lossy wrapper
    def encode(self, obj) -> bytes (:306); def decode(self, data: bytes) -> Any (:345)
_LOSSY_TAG = "lossy"                                           # :25 — unregistered models become {"__type__": "lossy", "__repr__": ...}

# packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/model.py
class ContextSnapshot(BaseModel):   # :56 — results: dict[str, Any] (:65); completed_tasks: list[str] (:73);
                                    #        completion_order: list[str] (:77); shared_data: dict[str, Any] (:81); errors: dict[str, dict[str,str]] (:85)
class FlowCheckpoint(BaseModel):    # :113 — flow_id (:121), flow_name, checkpoint_id: int (:123), parent_checkpoint_id, created_at,
                                    #        status: Literal["running","suspended","completed","failed"] (:129), definition (:132), context: ContextSnapshot (:133)

# packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/base.py:17
class CheckpointStore(ABC): put(:29) latest(flow_id)(:37) get(flow_id, checkpoint_id)(:48) history(:60) list_flows(:72)
                            delete_flow(:85) acquire_lease(flow_id, holder, ttl=60)->bool(:93) renew_lease(:107) release_lease(:122) close(:134)
# store/redis.py:93 put refreshes TTL (FLOW_CHECKPOINT_REDIS_TTL, conf.py:309 = 86400); store/durable.py:12 "No TTL/expiry"
# packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/__init__.py:12-15
CheckpointStore, DurableCheckpointStore, get_checkpoint_store, RedisCheckpointStore

# packages/ai-parrot/src/parrot/bots/flows/plan/node.py:1124
def build_manifest(plan, refs: Sequence[ArtifactRef], *, session_id=None, duration_seconds=0.0) -> ExecutionManifest
#   counts partial as failed; artifacts in `refs` order

# packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py:318-345 — the CURRENT ref synthesis to move into project_run:
#   result is ArtifactRef → keep; ctx.errors[node] → ArtifactRef(status="error", errors=[str(error)[:300]]);
#   neither → "node never dispatched: blocked by a failed dependency" (ONLY valid when the run is terminal)
```

### Does NOT Exist
- ~~`CheckpointStore.exists()` / `.was_created()` / tombstones~~ — must not be added (§8 D3).
- ~~`ArtifactRef` auto-registration in `bots/flows/plan`~~ — nothing registers it; you do, idempotently, in `register_plan_checkpoint_types()`.
- ~~`bots/flows/core/checkpoint/models.py`~~ — the file is `checkpoint/model.py` (singular).
- ~~`CheckpointInputMetadata(workflow="execution-plan")`~~ — `workflow` is `Literal["dev-loop","dev-flow"]` (`model.py:104`); store the fingerprint inside `PlanRunMetadata.plan_fingerprint` instead.
- ~~an in-memory `CheckpointStore` in production code~~ — only `redis.py`/`durable.py`; tests use the fake you create (the existing `FakeCheckpointStore` at `tests/flows/checkpoint/test_suspend_resume.py:20` stores objects, NOT bytes — spec §4 requires real serializer bytes).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/execution_plan/runs.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/_recovery_fakes.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_run_resolution.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/serializer.py#register_checkpoint_type",
    "sym:packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/serializer.py#FlowStateSerializer",
    "sym:packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/model.py#FlowCheckpoint",
    "sym:packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/model.py#ContextSnapshot",
    "sym:packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/base.py#CheckpointStore",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/node.py#build_manifest"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Fail closed**: a `results` value that decodes to anything other than an `ArtifactRef`
  (dict, lossy wrapper) ⇒ `PlanRunError("checkpoint_invalid")`. Never recover from `__repr__`.
- Missing/malformed `shared_data["plan_run"]`, `schema_version != 1`, root/child cycle,
  missing ancestor ⇒ `checkpoint_invalid`.
- **Pending vs blocked**: a node with neither result nor error is `pending` while
  `checkpoint.status == "running"` and is only synthesized as a blocked error ref when the
  run is terminal (`completed`/`failed`/`suspended` handled as non-terminal for resume).
- Counters are **recomputed** by `build_manifest` from the projected refs; never add parent
  and child totals. For a root with `active_child_run_id`, the resolver follows the chain
  (bounded by `len(repair_children)`) and projects the **latest consolidated** run: child refs
  override the parent's for the replaced ids; every other ref comes from the parent.
- `select_latest`: read both tiers, pick the greatest `checkpoint_id`; equal ids with
  different `created_at`/`status`/`context` ⇒ `checkpoint_invalid` (corruption).
- Scope: `metadata.scope_key != scope.cache_key()` ⇒ `PlanRunError("scope_mismatch")`.
- `resume_level`: `"none"` if `not checkpoint_enabled`; `"process"` if `artifact_mode == "memory"`;
  `"cross_restart"` otherwise. `resumable` additionally requires status in (`running`,
  `suspended`, `failed`, `partial`) with undispatched/pending nodes, and — for memory mode —
  `metadata.process_id == current process id`; else set `recovery_reason` to the §2 code
  (`checkpoint_unavailable` / `artifacts_unavailable` / `run_not_resumable`).
- The resolver's `cache: dict[str, PlanRun]` is consulted only for `checkpoint_enabled=False`
  runs (no store) or to add explicitly-marked uncheckpointed progress; a cached entry whose
  `checkpoint_id` is behind the store's latest is refreshed.

### References in Codebase
- `toolkit.py:318-345` — ref synthesis to lift.
- `flow.py:1631-1664` — how resume decodes `results` with `serializer.from_safe` and seeds `completion_order`.
- `tests/flows/checkpoint/test_serializer.py` — round-trip test idioms.

---

## Implementation Blueprint

### Steps (in order)
1. Write `_recovery_fakes.py` first — *why*: `test_run_resolution.py` and five later test files import it; the byte-serializing store is the only thing that can catch a missing type registration.
2. `register_plan_checkpoint_types` + `plan_fingerprint` + `read_run_metadata` — *why*: everything else decodes through them.
3. `project_run` — *why*: the deterministic core; test it with hand-built `FlowCheckpoint`s.
4. `select_latest`, `classify_miss`, `PlanRunResolver.resolve` — *why*: tier-aware I/O around the pure projection.

### `packages/ai-parrot/tests/tools/execution_plan/_recovery_fakes.py` (CREATE)
```python
"""Shared fakes for FEAT-585 recovery tests. Stores hold REAL FlowStateSerializer bytes."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from parrot.bots.flows.core.checkpoint import CheckpointStore, FlowCheckpoint, FlowStateSerializer
from parrot.clients.base import AbstractClient


class SerializingFakeCheckpointStore(CheckpointStore):
    """In-memory store that encodes/decodes every checkpoint through the real serializer.

    ``failures`` lets a test inject ``ConnectionError`` on the Nth ``put``.
    ``ttl_expired`` simulates Redis key expiry (``latest`` returns None) without deleting history.
    """

    def __init__(self, *, durable: bool = False) -> None:
        self._bytes: Dict[str, Dict[int, bytes]] = {}
        self._leases: Dict[str, str] = {}
        self._serializer = FlowStateSerializer()
        self.durable = durable
        self.put_calls = 0
        self.failures: List[int] = []
        self.ttl_expired: set[str] = set()

    async def put(self, checkpoint: FlowCheckpoint) -> None:
        self.put_calls += 1
        if self.put_calls in self.failures:
            raise ConnectionError("checkpoint store unavailable")
        self._bytes.setdefault(checkpoint.flow_id, {})[checkpoint.checkpoint_id] = self._serializer.encode(
            checkpoint.model_dump(mode="python")
        )

    async def latest(self, flow_id: str) -> FlowCheckpoint | None:
        if flow_id in self.ttl_expired or flow_id not in self._bytes:
            return None
        return await self.get(flow_id, max(self._bytes[flow_id]))

    async def get(self, flow_id: str, checkpoint_id: int) -> FlowCheckpoint | None:
        raw = self._bytes.get(flow_id, {}).get(checkpoint_id)
        return None if raw is None else FlowCheckpoint.model_validate(self._serializer.decode(raw))

    # FILL IN: history / list_flows / delete_flow / acquire_lease / renew_lease / release_lease / close —
    # copy the semantics of tests/flows/checkpoint/test_suspend_resume.py:20-75 (lease = dict flow_id→holder).


class ScriptedPlannerClient(AbstractClient):
    """AbstractClient double returning scripted ask() texts; counts calls (AC2/AC8 evidence)."""

    # FILL IN: copy tests/tools/execution_plan/test_planner.py:37-60 (_FakeClient) verbatim, add `self.calls: List[str]`.


class CountingToolManager:
    """ToolManagerLike fake counting dispatches per tool (proves completed nodes are not re-run)."""

    # FILL IN: copy tests/tools/execution_plan/test_toolkit_core.py:23-49 (_FakeToolManager); add
    # `self.dispatch_counts: Dict[str, int]` and optional per-tool asyncio.Event gates for interruption tests.
```
**Why**: `model_dump(mode="python")` keeps `ArtifactRef` instances inside `results`, so the
serializer must know the type — exactly the failure R1 describes. A plain object-holding fake
cannot detect it.

### `packages/ai-parrot/src/parrot/tools/execution_plan/runs.py` (CREATE — registration + projection)
```python
"""Checkpoint-derived run resolution for ExecutionPlanToolkit (FEAT-585 M3)."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
from typing import Any, Dict, List, Optional

from parrot.bots.flows.core.checkpoint import CheckpointStore, FlowCheckpoint, FlowStateSerializer, register_checkpoint_type
from parrot.bots.flows.plan import ArtifactRef, ExecutionPlan, build_manifest
from parrot.tools.working_memory.task_memory.models import TaskScope

from .models import PLAN_RUN_SHARED_KEY, PlanRecoveryEnvelope, PlanRun, PlanRunError, PlanRunManifest, PlanRunMetadata

__all__ = ("PlanRunResolver", "classify_miss", "plan_fingerprint", "process_identity",
           "project_run", "read_run_metadata", "register_plan_checkpoint_types", "select_latest")
_logger = logging.getLogger(__name__)
_TERMINAL = frozenset({"completed", "failed"})


def register_plan_checkpoint_types() -> None:
    """Idempotently register ArtifactRef before any checkpoint encode or decode (R1)."""
    register_checkpoint_type(ArtifactRef)


def process_identity() -> str:
    """``host:pid`` — identity of memory-mode artifacts (§2)."""
    return f"{socket.gethostname()}:{os.getpid()}"


def plan_fingerprint(plan: ExecutionPlan) -> str:
    """sha256 over canonical JSON of the effective plan."""
    return hashlib.sha256(json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_run_metadata(checkpoint: FlowCheckpoint) -> PlanRunMetadata:
    """Parse the ``plan_run`` envelope; anything malformed is ``checkpoint_invalid``."""
    raw = checkpoint.context.shared_data.get(PLAN_RUN_SHARED_KEY)
    if not isinstance(raw, dict):
        raise PlanRunError("checkpoint_invalid", f"checkpoint {checkpoint.flow_id}@{checkpoint.checkpoint_id} has no plan_run envelope")
    try:
        return PlanRunMetadata.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - converted to a bounded structured error
        raise PlanRunError("checkpoint_invalid", f"plan_run envelope rejected: {str(exc)[:300]}") from exc


def project_run(checkpoint: FlowCheckpoint, *, metadata: PlanRunMetadata) -> PlanRun:
    """Derive typed refs, progress and status; reject lossy or inconsistent state."""
    register_plan_checkpoint_types()
    serializer = FlowStateSerializer()
    terminal = checkpoint.status in _TERMINAL
    refs: List[ArtifactRef] = []
    dispatched: List[str] = []
    for node in metadata.plan.nodes:
        if node.id in checkpoint.context.results:
            value = serializer.from_safe(checkpoint.context.results[node.id])
            if not isinstance(value, ArtifactRef):
                raise PlanRunError("checkpoint_invalid", f"node {node.id!r} result is not a typed ArtifactRef")
            refs.append(value)
            dispatched.append(node.id)
        elif node.id in checkpoint.context.errors:
            refs.append(ArtifactRef(node_id=node.id, status="error", errors=[str(checkpoint.context.errors[node.id].get("message", ""))[:300]]))
            dispatched.append(node.id)
        elif terminal:
            refs.append(ArtifactRef(node_id=node.id, status="error", errors=["node never dispatched: blocked by a failed dependency"]))
        # else: pending — running run, no ref yet
    # FILL IN: status = "running" if not terminal else derive from build_manifest counters exactly as
    # toolkit.py:352-359 does; resume_level/resumable/recovery_reason per Implementation Notes;
    # return PlanRun(metadata=..., checkpoint_id=checkpoint.checkpoint_id, ...) — bounded by AC4/AC5.
    raise NotImplementedError
```
**Why this shape**: the loop is `toolkit.py:318-345` made pure and terminal-aware. Decoding
with `from_safe` and type-checking is the "reject lossy" rule; `register_plan_checkpoint_types()`
is called defensively before every decode because registration is process-wide and idempotent.

### `packages/ai-parrot/src/parrot/tools/execution_plan/runs.py` (CREATE — tiers + resolver)
```python
# continue the same file
async def select_latest(store: Optional[CheckpointStore], durable_store: Optional[CheckpointStore], flow_id: str) -> Optional[FlowCheckpoint]:
    """Greatest checkpoint_id across configured tiers; equal ids with different state are corruption."""
    candidates = [cp for cp in [await s.latest(flow_id) for s in (store, durable_store) if s is not None] if cp is not None]
    if not candidates:
        return None
    best = max(candidates, key=lambda cp: cp.checkpoint_id)
    for cp in candidates:
        if cp.checkpoint_id == best.checkpoint_id and cp.model_dump(mode="json") != best.model_dump(mode="json"):
            raise PlanRunError("checkpoint_invalid", f"tiers disagree on {flow_id}@{best.checkpoint_id}")
    return best


def classify_miss(store: Optional[CheckpointStore], durable_store: Optional[CheckpointStore]) -> str:
    """§8 D3: durable tier configured → unknown_run; ephemeral-only → missing_or_expired; none → checkpoint_unavailable."""
    if durable_store is not None:
        return "unknown_run"
    return "missing_or_expired" if store is not None else "checkpoint_unavailable"


class PlanRunResolver:
    """Resolve every agent-facing run operation from the same authority (the checkpoint)."""

    def __init__(self, *, store: Optional[CheckpointStore], durable_store: Optional[CheckpointStore],
                 scope: Optional[TaskScope], cache: Dict[str, PlanRun]) -> None:
        """Bind trusted scope and store handles, never serialized clients."""
        self._store, self._durable, self._scope, self._cache = store, durable_store, scope, cache
        self.logger = logging.getLogger(f"{__name__}.PlanRunResolver")

    async def resolve(self, run_id: str) -> PlanRun:
        """Resolve latest authorized lineage; classify misses by configured tier capability."""
        checkpoint = await select_latest(self._store, self._durable, run_id)
        if checkpoint is None:
            cached = self._cache.get(run_id)
            if cached is not None and not cached.checkpoint_enabled:
                return cached
            raise PlanRunError(classify_miss(self._store, self._durable), f"run {run_id!r} has no checkpoint in the configured tiers")
        metadata = read_run_metadata(checkpoint)
        if self._scope is not None and metadata.scope_key not in (None, self._scope.cache_key()):
            raise PlanRunError("scope_mismatch", f"run {run_id!r} belongs to another scope")
        run = project_run(checkpoint, metadata=metadata)
        # FILL IN: follow metadata.active_child_run_id (bounded by len(metadata.repair_children)+1 hops, cycle →
        # checkpoint_invalid, missing child → checkpoint_invalid) and consolidate child refs over parent refs;
        # merge cache[run_id].uncheckpointed progress only when cache entry checkpoint_id == checkpoint.checkpoint_id.
        return run

    def envelope(self, run: PlanRun) -> PlanRecoveryEnvelope:
        """Build the response envelope from a resolved run."""
        m = run.metadata
        return PlanRecoveryEnvelope(run_id=m.run_id, root_run_id=m.root_run_id, parent_run_id=m.parent_run_id,
                                    checkpoint_enabled=run.checkpoint_enabled, artifact_mode=m.artifact_mode,
                                    resume_level=run.resume_level, resumable=run.resumable, recovery_reason=run.recovery_reason,
                                    repair_attempts_used=m.repair_attempts_used, max_repair_rounds=m.max_repair_rounds,
                                    active_child_run_id=m.active_child_run_id)
```
**Why**: `classify_miss` is the whole of §8 D3 in six lines — decided by configuration, not by a
retained record. `select_latest` implements "read both tiers, pick the greatest id".

### FILL IN checklist
- [ ] `_recovery_fakes.py` — remaining `CheckpointStore` methods; `ScriptedPlannerClient`; `CountingToolManager`
- [ ] `runs.py::project_run` — status/resume_level/resumable derivation; AC4/AC5
- [ ] `runs.py::PlanRunResolver.resolve` — lineage walk + consolidation + cache merge; §2 "Root lookup follows this bounded chain"
- [ ] `test_run_resolution.py` — bodies

---

## Acceptance Criteria

- [ ] AC-1 — A checkpoint whose `results` hold `ArtifactRef`s survives `SerializingFakeCheckpointStore` put/latest with typed refs; with a **fresh** serializer registry and no registration the same bytes are rejected as `checkpoint_invalid`, not silently repr-degraded (AC3, R1).
- [ ] AC-2 — `project_run` yields ok/skipped/partial/error/hard-failure refs in **original node order**; a pending node on a `running` checkpoint is absent from refs, and present as a blocked error on a `failed` one; counters equal `build_manifest`'s.
- [ ] AC-3 — Resolver follows `active_child_run_id`, consolidates without double counting, and raises `checkpoint_invalid` on a cycle, a missing ancestor and `schema_version != 1`.
- [ ] AC-4 — Durable tier configured + `latest()` None ⇒ `unknown_run`; ephemeral-only ⇒ `missing_or_expired`; both carry the tier in the error (AC16).
- [ ] AC-5 — Another scope's `scope_key` ⇒ `scope_mismatch`.
- [ ] `ruff check` clean.
- [ ] Dependency suites still pass (files created by upstream tasks, so not listed under Validation Commands): `pytest packages/ai-parrot/tests/tools/execution_plan/test_run_models.py -q`

## Validation Commands
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_run_resolution.py -q`
- `pytest packages/ai-parrot/tests/flows/checkpoint/test_serializer.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/execution_plan/test_run_resolution.py
import pytest
from parrot.tools.execution_plan.runs import PlanRunResolver, classify_miss, project_run, register_plan_checkpoint_types, select_latest
from ._recovery_fakes import SerializingFakeCheckpointStore

pytestmark = pytest.mark.asyncio

def _checkpoint(*, status, results, errors, metadata, checkpoint_id=1, flow_id="run-1"): ...   # builds FlowCheckpoint with shared_data={"plan_run": metadata.model_dump(mode="json")}

async def test_artifact_ref_checkpoint_roundtrip(): ...             # AC-1
async def test_unregistered_type_fails_closed(monkeypatch): ...     # AC-1 (fresh FlowStateSerializer registry via monkeypatch)
def test_manifest_projection_orders_and_counts(): ...               # AC-2
def test_pending_vs_blocked(): ...                                  # AC-2
async def test_resolver_follows_active_child_and_consolidates(): ...# AC-3
async def test_resolver_rejects_cycle_missing_ancestor_schema(): ...# AC-3
async def test_tier_classification(): ...                           # AC-4
async def test_scope_mismatch(): ...                                # AC-5
async def test_select_latest_prefers_greatest_id_and_detects_corruption(): ...
```

---

## Agent Instructions

1. Read spec §2 "Checkpoint contract and recovery", "Recovery capabilities", §8 D3, §3 Module 3.
2. Verify anchors; write the fakes first, then `runs.py`, then tests.
3. Run the Validation Commands.
4. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

**Completed by**: native / sonnet (sdd-coder subagent), attempt_uid `dc8368af811c4668b55324d87d6bd06e`
**Date**: 2026-09-22
**Notes**:
- Delivered exactly the 3 scoped files: `runs.py` (`register_plan_checkpoint_types`,
  `plan_fingerprint`, `read_run_metadata`, `project_run`, `select_latest`, `classify_miss`,
  `PlanRunResolver`), `_recovery_fakes.py` (`SerializingFakeCheckpointStore`,
  `ScriptedPlannerClient`, `CountingToolManager`), `test_run_resolution.py` (9 tests,
  AC-1..AC-5). No out-of-scope files; `sdd/` untouched.
- 9 new tests pass; regression checks against `test_serializer.py` (12 passed) and
  `test_run_models.py` (11 passed, unmodified) confirm no drift in dependencies. ruff clean.
- Self-checked all 3 prior coder-feedback patterns (hasattr-duck-typing-ordering,
  unisolated-real-$HOME-in-tests, unscoped-removal-reuse) against this delivery; none
  applicable (no hasattr branching — uses explicit `isinstance(value, ArtifactRef)`;
  no filesystem paths touched; no wider-scoped helper reused for a narrower operation).
- **Ledger-worthy finding reported by the coder** (test-fake-only workaround, in this task's
  own file scope, not a defect in this delivery): `SerializingFakeCheckpointStore.put()`'s
  blueprint-given body (`self._serializer.encode(checkpoint.model_dump(mode="python"))`)
  cannot round-trip a registered Pydantic type nested inside `ContextSnapshot.results`
  (a `dict[str, Any]` field) — Pydantic v2.12.5's `model_dump()` flattens the nested
  `BaseModel` to a plain dict before `FlowStateSerializer` can tag it, and pre-encoding via
  `to_safe_with_meta()` first triggers the serializer's own `__type__`-key collision-escape
  guard on the second pass, corrupting the envelope. Fixed locally in `_recovery_fakes.py` by
  restoring the raw (live-object) `results` onto the `model_dump()`'d payload before the
  single `encode()` call. The coder flagged this as a likely latent defect in the shared
  FEAT-399 `FlowStateSerializer`/`FlowCheckpointer` double-encode interaction that would
  affect any OTHER registered type once exercised against a real byte-based store (Redis/
  Durable) rather than an object-holding fake — worth a ledger issue at feature completion
  review; every existing checkpoint-store test fake in the repo stores live objects directly
  and never exercised this path. **Filed at feature-completion code review, not here** (per
  the SDD-worker protocol: deferred findings are filed once, at the adversarial review step).
- Design decisions documented as code comments where the Implementation Notes were
  underspecified: resumable/recovery_reason precedence order; lineage consolidation keeps the
  deepest child's `PlanRunMetadata` on the returned `PlanRun`; a child's synthesized `blocked`
  refs never override a parent's real ref (only the child's own `dispatched_node_ids` do).
- Merge-tier `coder_run_validation` for the TASK-3592/TASK-3593 chunk hit the same
  established pre-existing timeout pattern as earlier tasks in this feature (see TASK-3592's
  Completion Note) — no failure relates to `runs.py` or `_recovery_fakes.py`.

**Deviations from spec**: none.
