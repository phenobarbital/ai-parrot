# TASK-3591: PlanWorkingMemoryCatalog — exact-version restoration without new versions

**Feature**: FEAT-585 — Plan-then-Execute Hardening
**Spec**: `sdd/specs/plan-then-execute-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements the catalog half of spec §3 **Module 2** ("Plan memory binding and recovery
reads") and AC3 / AC13.

`WorkingMemoryCatalog.aget()` (`tools/working_memory/internals.py:1204`) only reads the
local `_store` dict, even when a durable artifact backend is attached. After a process
restart the catalog is empty, so a resumed plan node that reads `{artifacts.<id>}` would
fail even though the exact `artifact_id@version` is still in the backend (research
finding R2). This task adds a toolkit-local subclass that can **restore** an exact
`EvidenceRef` from the backend into the local catalog: authorized against the host
scope, loaded through the backend's byte-bound API, metadata reconstructed from the
returned descriptor, and **never** by writing a new version or moving the persistent
alias.

---

## Scope

- Create `packages/ai-parrot/src/parrot/tools/execution_plan/memory.py` with
  `PlanWorkingMemoryCatalog(WorkingMemoryCatalog)`:
  `restore_version(key, ref, *, max_bytes)`, `aget(key)` override, and a private
  `_bind_version(key, ref)` pin map used by `aget` to refuse alias/version conflicts.
- Define the module-level `RestoreError(Exception)` with a `code` attribute using the
  §2 stable codes `missing_or_expired`, `artifact_alias_conflict`,
  `restore_budget_exceeded`, `scope_mismatch`.
- Write `packages/ai-parrot/tests/tools/execution_plan/test_plan_memory_restore.py`.

**NOT in scope**:
- `PlanMemoryBinding` and `WorkingMemoryToolkit._enable_plan_memory` (TASK-3592, which
  appends to this same `memory.py`).
- Any change to `WorkingMemoryCatalog` itself or to the raw-read policy in `tool.py`.
- Restoring interrupted fan-out item aliases (TASK-3592 `restore()` handles the whole-node case; item-level ownership is reported as a limitation, spec §2).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/execution_plan/memory.py` | CREATE | `RestoreError`, `PlanWorkingMemoryCatalog` |
| `packages/ai-parrot/tests/tools/execution_plan/test_plan_memory_restore.py` | CREATE | Restore tests over `InMemoryArtifactStore` |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `3028213ee` on 2026-09-21.

### Verified Imports
```python
from parrot.tools.working_memory.internals import (          # verified: packages/ai-parrot/src/parrot/tools/working_memory/internals.py
    WorkingMemoryCatalog,   # class at :778, __init__ at :794
    CatalogEntry,           # :442
    GenericEntry,           # :307
    VersionMetadata,        # :96, from_descriptor classmethod at :163
)
from parrot.tools.working_memory.task_memory.models import TaskScope, EvidenceRef  # verified: models.py:571, :619
from parrot.interfaces.artifact_store import ArtifactStore, PayloadResult           # verified: artifact_store.py:152, :90
from parrot.tools.working_memory.task_memory.artifacts import InMemoryArtifactStore # verified: artifacts.py:290 (tests only)
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig         # verified: config.py:57 (tests only)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/working_memory/internals.py:794
class WorkingMemoryCatalog:
    def __init__(self, session_id: Optional[str] = None, *, backend: Optional["ArtifactStore"] = None,
                 scope: Optional["TaskScope"] = None, task_id: Optional[str] = None) -> None
        self.session_id; self._store: dict[str, CatalogEntry | GenericEntry] (:824); self._backend (:830);
        self._scope (:831); self.task_id (:832); self._lock = asyncio.Lock() (:834)
    @property is_enabled -> bool                                   # :839
    def _require_enabled(self, method: str) -> tuple[ArtifactStore, TaskScope]   # :871
    def put_generic(...)                                           # :922 (sync; ERROR when enabled)
    def get(self, key: str) -> CatalogEntry | GenericEntry         # :968 (sync local read)
    async def aput_generic(...)                                    # :1074 — the ONLY way a new version is allocated
    async def aget(self, key: str) -> CatalogEntry | GenericEntry  # :1204 — local-only, raises KeyError

# packages/ai-parrot/src/parrot/tools/working_memory/internals.py:163
@classmethod
def from_descriptor(cls, descriptor: "ArtifactDescriptor") -> "VersionMetadata"
#   captures artifact_id/version/scope/kind/availability/created_at/task_id/producer_call_id/
#   fingerprint/evidence_verifiable/invalidated/binding_invalid/byte_size/captured_shape/schema_summary/storage_ref

# packages/ai-parrot/src/parrot/interfaces/artifact_store.py
async def get_version(self, scope: TaskScope, ref: EvidenceRef, *, task_id: Optional[str] = None) -> Optional[ArtifactDescriptor]  # :242
async def load_payload(self, scope: TaskScope, ref: EvidenceRef, *, max_bytes: int,
                       offset: Optional[int] = None, limit: Optional[int] = None) -> PayloadResult                       # :266
class PayloadResult: ref, kind, payload (Any|None), refusal (PayloadRefusal|None), byte_size, returned_bytes, truncated  # :90

# packages/ai-parrot/src/parrot/tools/working_memory/task_memory/models.py:619
class EvidenceRef(_TaskModel): artifact_id: str; version: int (ge=1); __str__ -> "id@version"; @classmethod parse(value)
# :571
class TaskScope(_TaskModel): chatbot_id, user_id, session_id; cache_key(); matches(other) -> bool
```

### How entries are built today (pattern to mirror, NOT to call)
`aput_generic` (`internals.py:1074-1145`) writes through the backend, then constructs
the local entry with `version_metadata=VersionMetadata.from_descriptor(descriptor)`
(`:1140`). `restore_version` must build the same entry shape from a descriptor returned
by `get_version`, **without** calling `put`/`aput_generic`. Read `GenericEntry`
(`internals.py:307-441`) and `CatalogEntry` (`:442-...`) constructors before writing
`_entry_from_payload` — their required fields are the contract.

### Does NOT Exist
- ~~`WorkingMemoryCatalog.attach_backend` / `.enable` / `.set_backend`~~ — backend is constructor-only.
- ~~a read-through `aget` in the base class~~ — `:1204` reads `_store` only; that is the gap you fill.
- ~~`ArtifactStore.restore` / `.hydrate` / `.get_payload`~~ — only `get_version` + `load_payload`.
- ~~`ArtifactStore.exists()`~~ — a `None` from `get_version` IS the miss signal.
- ~~`EvidenceRef` inside `ArtifactRef`~~ — `ArtifactRef.versions` is `List[str]` ("id@version"); parse with `EvidenceRef.parse`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/execution_plan/memory.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_plan_memory_restore.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/working_memory/internals.py#WorkingMemoryCatalog",
    "sym:packages/ai-parrot/src/parrot/tools/working_memory/internals.py#WorkingMemoryCatalog.aget",
    "sym:packages/ai-parrot/src/parrot/tools/working_memory/internals.py#VersionMetadata.from_descriptor",
    "sym:packages/ai-parrot/src/parrot/interfaces/artifact_store.py#ArtifactStore"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Never allocate a version, never move an alias**: no `put`, `aput_generic`, `drop_alias`
  or `invalidate` calls anywhere in this file (AC13 "never mutates evidence versions").
- Authorize with the **host** scope (`self._scope`), never a scope carried by the caller.
  A `get_version` returning `None` → `RestoreError("missing_or_expired")`;
  `descriptor.invalidated` or `availability` not loadable → `missing_or_expired`;
  `PayloadResult.refusal` set → `restore_budget_exceeded`.
- Pin exact versions: `_bind_version(key, ref)` records `key → ref`; a second pin for the
  same key with a **different** ref raises `artifact_alias_conflict`; `aget` on a key that
  is bound but not yet local restores it lazily using the pinned ref, never the backend's
  current alias.
- Hold `self._lock` (`internals.py:834`) around the local publish, like `aput_generic`.
- Validate key/version cardinality: one key ↔ one ref per call.

### References in Codebase
- `internals.py:1074-1145` `aput_generic` — the lock + `from_descriptor` + local publish shape.
- `bots/flows/plan/node.py:594-621` `_read_key` — the consumer (`await catalog.aget(key)`; reads `.data`/`.df`).
- `tests/tools/working_memory/task_memory/test_plan_task_receipts.py:55` — `SCOPE = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")` fixture idiom.

---

## Implementation Blueprint

### Steps (in order)
1. Create `memory.py` with `RestoreError` and the class skeleton — *why*: TASK-3592 appends `PlanMemoryBinding` to this file and imports `RestoreError`.
2. Implement `restore_version` as authorize → load → build entry → publish under lock — *why*: the order is the security property (scope check before any bytes move).
3. Implement `_bind_version` and the `aget` override — *why*: pinning is what makes a resumed run read the version it proved, not whatever the alias points to now.
4. Tests over a real `InMemoryArtifactStore` — *why*: a dict fake cannot prove that no new version was allocated; the store's version counter can.

### `packages/ai-parrot/src/parrot/tools/execution_plan/memory.py` (CREATE)
```python
"""Plan-scoped working-memory binding and exact-version recovery (FEAT-585 M2)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from parrot.interfaces.artifact_store import ArtifactStore, PayloadResult
from parrot.tools.working_memory.internals import CatalogEntry, GenericEntry, VersionMetadata, WorkingMemoryCatalog
from parrot.tools.working_memory.task_memory.models import EvidenceRef, TaskScope

__all__ = ("PlanWorkingMemoryCatalog", "RestoreError")


class RestoreError(Exception):
    """A restoration was refused; ``code`` is one of the spec §2 stable codes."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PlanWorkingMemoryCatalog(WorkingMemoryCatalog):
    """Catalog that can restore an exact ``artifact_id@version`` into the local store.

    Restoration reads through the backend's byte-bound API and publishes a local
    entry. It never writes a version and never moves the backend alias (AC13).
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Bind like the base catalog and start with no pinned versions."""
        super().__init__(*args, **kwargs)
        self._pinned: Dict[str, EvidenceRef] = {}
        self.logger = logging.getLogger(f"{__name__}.PlanWorkingMemoryCatalog")

    def _bind_version(self, key: str, ref: EvidenceRef) -> None:
        """Pin ``key`` to ``ref`` for this continuation; conflicting pins are refused."""
        current = self._pinned.get(key)
        if current is not None and (current.artifact_id, current.version) != (ref.artifact_id, ref.version):
            raise RestoreError("artifact_alias_conflict", f"{key!r} is pinned to {current}, not {ref}")
        self._pinned[key] = ref

    async def restore_version(self, key: str, ref: EvidenceRef, *, max_bytes: int) -> None:
        """Authorize, load and publish ``ref`` under alias ``key`` without allocating a version.

        Raises:
            RestoreError: ``scope_mismatch`` (catalog has no trusted scope), ``missing_or_expired``
                (unknown/invalidated/unavailable version), ``restore_budget_exceeded``
                (backend refused under ``max_bytes``), ``artifact_alias_conflict``.
        """
        backend, scope = self._require_enabled("restore_version")
        self._bind_version(key, ref)
        descriptor = await backend.get_version(scope, ref, task_id=self.task_id)
        if descriptor is None or getattr(descriptor, "invalidated", False):
            raise RestoreError("missing_or_expired", f"{ref} is not available in this scope")
        result: PayloadResult = await backend.load_payload(scope, ref, max_bytes=max_bytes)
        if result.refusal is not None or result.payload is None:
            raise RestoreError("restore_budget_exceeded", f"{ref} refused under max_bytes={max_bytes}: {result.refusal}")
        entry = self._entry_from_payload(key, result.payload, descriptor)
        async with self._lock:
            self._store[key] = entry
        self.logger.debug("restored %s as %r (%d bytes)", ref, key, result.returned_bytes or 0)

    def _entry_from_payload(self, key: str, payload: Any, descriptor: Any) -> "CatalogEntry | GenericEntry":
        """Rebuild the local entry the way ``aput_generic`` would have, from a read descriptor."""
        metadata = VersionMetadata.from_descriptor(descriptor)
        # FILL IN: construct GenericEntry (or CatalogEntry when payload is a DataFrame) with the SAME
        # required fields aput_generic passes at internals.py:1120-1145, using `metadata` as
        # version_metadata — bounded by "reconstruct entry metadata without writing a new version".
        raise NotImplementedError

    async def aget(self, key: str) -> "CatalogEntry | GenericEntry":
        """Local read; a pinned-but-missing key is restored from its pinned version first."""
        async with self._lock:
            if key in self._store:
                return self._store[key]
        pinned = self._pinned.get(key)
        if pinned is None:
            return await super().aget(key)
        # FILL IN: restore with the continuation's budget (set by TASK-3592 via a `_restore_budget`
        # attribute; default to a conservative 2_000_000 here) — bounded by AC13 "restoration is bounded".
        raise NotImplementedError
```
**Why this shape**: the constructor keeps the base contract (`backend=` requires `scope=`,
`internals.py:826`), so `_require_enabled` gives the trusted scope; `get_version` is the
authorization, `load_payload(max_bytes=)` is the byte bound; the `_pinned` map is what
"pin exact versions for completed nodes during an active continuation" (§2) means in code.

### `packages/ai-parrot/tests/tools/execution_plan/test_plan_memory_restore.py` (CREATE)
```python
"""FEAT-585 M2 — exact-version restoration (test_restore_exact_version)."""
from __future__ import annotations

import pytest

from parrot.tools.execution_plan.memory import PlanWorkingMemoryCatalog, RestoreError
from parrot.tools.working_memory.task_memory.artifacts import InMemoryArtifactStore
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig
from parrot.tools.working_memory.task_memory.models import EvidenceRef, TaskScope

pytestmark = pytest.mark.asyncio
SCOPE = TaskScope(chatbot_id="execution-plan", user_id="proc-1", session_id="sess-1")
OTHER = TaskScope(chatbot_id="execution-plan", user_id="proc-2", session_id="sess-1")


@pytest.fixture
def backend() -> InMemoryArtifactStore:
    return InMemoryArtifactStore(TaskMemoryConfig(enabled=True))


async def _seed(backend, key: str, value) -> EvidenceRef:
    """Write one version through a producer catalog and return its EvidenceRef."""
    producer = PlanWorkingMemoryCatalog(backend=backend, scope=SCOPE)
    await producer.aput_generic(key, value)   # FILL IN: exact kwargs per internals.py:1074 signature
    entry = await producer.aget(key)
    meta = entry.version_metadata
    return EvidenceRef(artifact_id=meta.artifact_id, version=meta.version)


async def test_restore_publishes_locally_without_new_version(backend): ...   # version count unchanged; aget works
async def test_restore_unknown_version_is_missing_or_expired(backend): ...
async def test_restore_other_scope_is_missing(backend): ...                   # seeded under SCOPE, catalog bound to OTHER
async def test_restore_over_budget_is_refused(backend): ...                   # max_bytes=1 → restore_budget_exceeded
async def test_conflicting_pin_is_alias_conflict(backend): ...
async def test_alias_moved_later_still_reads_pinned_version(backend): ...     # producer writes v2; pinned v1 wins
```
**Why**: spec §4 `test_restore_exact_version`: "No new versions, no alias movement, bounded
loads, eviction/refusal and scope mismatch". Assert "no new version" by seeding, restoring,
then writing again from the producer and checking the new version number is exactly old+1.

### FILL IN checklist
- [ ] `memory.py::PlanWorkingMemoryCatalog._entry_from_payload` — mirror `aput_generic`'s entry construction; AC13
- [ ] `memory.py::PlanWorkingMemoryCatalog.aget` — lazy restore of a pinned key under a budget; AC13
- [ ] `test_plan_memory_restore.py` — `_seed` kwargs and the six test bodies

---

## Acceptance Criteria

- [ ] AC-1 — `restore_version` makes a restored key readable via `aget` and the backend's version counter for that artifact is unchanged (AC13).
- [ ] AC-2 — Unknown/other-scope/invalidated versions raise `RestoreError` with `code == "missing_or_expired"`; no local entry is created.
- [ ] AC-3 — `load_payload` refusal raises `code == "restore_budget_exceeded"`; a conflicting pin raises `artifact_alias_conflict`.
- [ ] AC-4 — After the producer writes a newer version under the same alias, a catalog pinned to the older ref still reads the older payload (AC3 "exact durable versions").
- [ ] AC-5 — The module contains no call to `put`, `aput_generic`, `drop_alias` or `invalidate` (grep-verified).
- [ ] `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_plan_memory_restore.py -q`
- `pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_catalog_async.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Read spec §2 "Plan memory binding and recovery reads" and §3 Module 2.
2. Read `internals.py:1074-1145` and `:307-520` before writing `_entry_from_payload`.
3. Verify anchors, implement, run Validation Commands.
4. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
