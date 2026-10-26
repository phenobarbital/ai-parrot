# TASK-4739: M1a — `parrot.interagent`: error codes, handles, descriptors, provenance, HandleStore

**Feature**: FEAT-746 — Squawk: typed binary inter-agent protocol
**Spec**: `sdd/specs/inter-agent-protocol.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (U1, S5, §8 Q1/Q3): the neutral, transport-free protocol contract lives in core `parrot/interagent/`. This first slice creates the package with the typed error codes, the `ArtifactHandle` family (`MediaType`, `HandleOwner`, `HandleDescriptor`, `HandleProvenance`, `ArtifactHandle`), `handle_key`, the `HandleStore` protocol with the owner-bound claim semantics lifted from FEAT-704's spec (`semantic-layer.spec.md:634-671`: every mismatch raises the same code, metadata alone is never authorization) and an `InMemoryHandleStore`. Later M1 slices (TASK-4740/4741/4742) add ledger, contract, messages, compiler and bus codec to the same package.

---

## Scope

- Create `parrot/interagent/{__init__,errors,handles,descriptors,provenance}.py` with the §2 Data Models exactly (frozen Pydantic v2 models).
- `HandleStore` Protocol + `InMemoryHandleStore` (bounded, `put`/`claim`/`grant`), `HandleClaimError` with the single code `handle_unavailable`.
- Tests in `packages/ai-parrot/tests/interagent/test_handles.py` (+ `__init__.py`).
- Package imports nothing from `parrot.squawk`, `parrot.semantic`, `pycapnp`, `biscuit`.

**NOT in scope**: `ServedLedgerEntry`/contract models (TASK-4740), messages/bus codec (TASK-4741), compiler (TASK-4742), blob store (M5).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interagent/__init__.py` | CREATE | exports (this slice only) |
| `packages/ai-parrot/src/parrot/interagent/errors.py` | CREATE | `SquawkErrorCode`, `SquawkError` |
| `packages/ai-parrot/src/parrot/interagent/descriptors.py` | CREATE | `MediaType`, `HandleDescriptor` |
| `packages/ai-parrot/src/parrot/interagent/provenance.py` | CREATE | `HandleProvenance` |
| `packages/ai-parrot/src/parrot/interagent/handles.py` | CREATE | `HandleOwner`, `ArtifactHandle`, `HandleStore`, `InMemoryHandleStore`, `HandleClaimError`, `handle_key` |
| `packages/ai-parrot/tests/interagent/__init__.py` | CREATE | tests package |
| `packages/ai-parrot/tests/interagent/test_handles.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field   # pydantic v2 (project standard; used e.g. in packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py:185 BlobRef with ConfigDict(extra="forbid", frozen=True))
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py:185 — the frozen-model idiom to copy
class BlobRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
# sdd/specs/semantic-layer.spec.md:634-671 — ResultHandle / ResultHandleStore.claim semantics being lifted (spec text, not code):
#   owner tuple (agent_id, user_id, tenant_id, session_id); claim re-verifies owner + expiry; "every mismatch raises the SAME code — never reveal whether a handle exists for someone else"
```

### Does NOT Exist
- ~~`parrot.interagent`~~ — created here.
- ~~`parrot.semantic.results.ResultHandle`~~ — FEAT-704 is unimplemented (TASK-4476 pending); never import `parrot.semantic`.
- ~~`parrot.interfaces.artifact_store.ArtifactHandle`~~ — the only `ArtifactStore`/`ArtifactDescriptor` there are task-memory types; do not subclass them.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interagent/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/interagent/errors.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/interagent/descriptors.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/interagent/provenance.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/interagent/handles.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/interagent/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/interagent/test_handles.py", "action": "CREATE"}
  ],
  "contract_symbols": ["sym:packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py#BlobRef"]
}
```

---

## Implementation Notes

### Key Constraints
- All models `frozen=True, extra="forbid"`; Google docstrings; strict hints.
- `handle_key(data) -> "sha256:<hex>"`; `ArtifactHandle.key` validated by regex `^sha256:[0-9a-f]{64}$`.
- `HandleClaimError` message is constant (`"handle_unavailable"`) — tests assert identical `str(exc)` for non-owner, expired and unknown.
- `InMemoryHandleStore` is asyncio-safe enough for tests (a dict + `asyncio.Lock`); bounded by `max_entries` (evict oldest).

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py:185-218` — frozen reference model idiom.
- `packages/ai-parrot/src/parrot/security/audit_ledger.py:109` — `canonical_bytes` idiom (used by TASK-4740; mention only).

---

## Implementation Blueprint

### Steps (in order)
1. `errors.py` — *why*: every other module raises `SquawkError`.
2. `descriptors.py`, `provenance.py` — *why*: `ArtifactHandle` composes them.
3. `handles.py` with the store — *why*: the claim semantics are the security core of D3/D4.
4. `__init__.py` exports; tests — *why*: later slices append to the same `__init__`.

### `packages/ai-parrot/src/parrot/interagent/errors.py` (CREATE)
```python
"""Typed protocol errors shared by Squawk (FEAT-746) and Roost (FEAT-747)."""
from __future__ import annotations

from enum import Enum
from typing import Any


class SquawkErrorCode(str, Enum):
    """Wire-level error codes; `detail` is a short audit string, never the primary signal."""

    STALE_CONTRACT = "STALE_CONTRACT"
    POLICY_DENIED = "POLICY_DENIED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    UNAUTHORIZED = "UNAUTHORIZED"
    UNKNOWN_CAPABILITY = "UNKNOWN_CAPABILITY"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    UPSTREAM_FAILED = "UPSTREAM_FAILED"


class SquawkError(Exception):
    """Typed protocol error.

    Args:
        code: The wire code.
        detail: Short, sanitized audit string (no policy internals, no payload).
        payload: Structured extra; ``STALE_CONTRACT`` carries the current category here.
    """

    def __init__(self, code: SquawkErrorCode, detail: str = "", payload: dict[str, Any] | None = None) -> None:
        super().__init__(f"{code.value}: {detail}" if detail else code.value)
        self.code = code
        self.detail = detail
        self.payload = payload or {}
```

### `packages/ai-parrot/src/parrot/interagent/descriptors.py` (CREATE)
```python
"""Media types and the bounded descriptor the LLM sees instead of the payload (D3, D7)."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MediaType(str, Enum):
    """Registered artifact media types (unknown types travel as GENERIC with no affordances)."""

    ARROW = "arrow"; PARQUET = "parquet"; MERMAID = "mermaid"; STRUCTURIZR = "structurizr"
    SVG = "svg"; PNG = "png"; PDF = "pdf"; GENERIC = "generic"


class HandleDescriptor(BaseModel):
    """What the LLM reads: ~100–200 tokens, never bytes. Caps are frozen by gate G1."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    media_type: MediaType
    byte_size: int = Field(ge=0)
    summary: dict[str, Any] = Field(default_factory=dict)
    # FILL IN: a model_validator bounding json.dumps(summary) length — bounded by the G1 amendment (default 1500 chars until amended)
```

### `packages/ai-parrot/src/parrot/interagent/provenance.py` (CREATE)
```python
"""Provenance carried by every artifact handle (audit, citation, promotion loop)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HandleProvenance(BaseModel):
    """Who produced the bytes, under which contract and policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    serving_agent: str
    cap_id: str
    contract_hash: str
    args_digest: str
    policy_applied: tuple[str, ...] = ()
    data_classes: tuple[str, ...] = ()
    backing: Literal["deterministic", "llm_backed"]
    produced_at: datetime
    trace_id: str
    derived_from: tuple[str, ...] = Field(default_factory=tuple)
```

### `packages/ai-parrot/src/parrot/interagent/handles.py` (CREATE)
```python
"""Owner-bound artifact handles: a key is never a bearer (FEAT-746 D4; semantics lifted from FEAT-704 M9b)."""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from parrot.interagent.descriptors import HandleDescriptor, MediaType
from parrot.interagent.provenance import HandleProvenance

HANDLE_UNAVAILABLE = "handle_unavailable"


class HandleClaimError(Exception):
    """Raised for EVERY failed claim (non-owner, expired, unknown) with the same message."""

    def __init__(self) -> None:
        super().__init__(HANDLE_UNAVAILABLE)


def handle_key(data: bytes) -> str:
    """Content key: ``'sha256:' + hexdigest``."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


class HandleOwner(BaseModel):
    """Owner tuple (mirrors FEAT-704 ResultHandle's owner)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    agent_id: str; user_id: str; tenant_id: str; session_id: str


class ArtifactHandle(BaseModel):
    """Handle + descriptor + provenance; bytes live only in a blob store."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    media_type: MediaType
    byte_size: int = Field(ge=0)
    ttl_s: int = Field(ge=1)
    expires_at: datetime
    owner: HandleOwner
    grants: tuple[str, ...] = ()
    descriptor: HandleDescriptor
    provenance: HandleProvenance
    affordances: tuple[str, ...] = ()


class HandleStore(Protocol):
    """Claim semantics: owner match or explicit grant, unexpired — else HandleClaimError."""

    async def put(self, handle: ArtifactHandle) -> str: ...
    async def claim(self, key: str, *, owner: HandleOwner, grantee: str | None = None) -> ArtifactHandle: ...
    async def grant(self, key: str, *, owner: HandleOwner, grantee: str) -> ArtifactHandle: ...


class InMemoryHandleStore:
    """Bounded dict-backed HandleStore for tests and single-process deployments."""

    def __init__(self, *, max_entries: int = 4096) -> None:
        self._items: dict[str, ArtifactHandle] = {}
        self._max = max_entries
        self._lock = asyncio.Lock()

    async def put(self, handle: ArtifactHandle) -> str:
        async with self._lock:
            # FILL IN: evict oldest (insertion order) when len >= self._max — bounded by max_entries
            self._items[handle.key] = handle
            return handle.key

    async def claim(self, key: str, *, owner: HandleOwner, grantee: str | None = None) -> ArtifactHandle:
        async with self._lock:
            h = self._items.get(key)
            # FILL IN: unknown OR expired (expires_at <= now UTC) OR (owner != h.owner and grantee not in h.grants) ⇒ raise HandleClaimError() — same exception, no branch-specific message
            return h

    async def grant(self, key: str, *, owner: HandleOwner, grantee: str) -> ArtifactHandle:
        async with self._lock:
            # FILL IN: owner-only; return h.model_copy(update={"grants": (*h.grants, grantee)}) and store it — bounded by: non-owner ⇒ HandleClaimError
            raise NotImplementedError
```

### `packages/ai-parrot/src/parrot/interagent/__init__.py` (CREATE)
```python
"""Transport-free inter-agent protocol contract shared by Squawk (FEAT-746) and Roost (FEAT-747).

Never imports parrot.squawk, parrot.semantic, pycapnp or biscuit.
"""
from parrot.interagent.descriptors import HandleDescriptor, MediaType
from parrot.interagent.errors import SquawkError, SquawkErrorCode
from parrot.interagent.handles import ArtifactHandle, HandleClaimError, HandleOwner, HandleStore, InMemoryHandleStore, handle_key
from parrot.interagent.provenance import HandleProvenance

__all__ = [
    "ArtifactHandle", "HandleClaimError", "HandleDescriptor", "HandleOwner", "HandleProvenance", "HandleStore",
    "InMemoryHandleStore", "MediaType", "SquawkError", "SquawkErrorCode", "handle_key",
]
```
**Why this shape**: §2 Data Models verbatim; the single-message `HandleClaimError` is the TASK-4476 rule the spec lifts (Q1). Later slices append to `__all__`.

### FILL IN checklist
- [ ] `descriptors.py::HandleDescriptor` summary-size validator; bounded by G1 amendment (1500 chars default)
- [ ] `handles.py::InMemoryHandleStore.put/claim/grant` — eviction, the three refusal conditions, owner-only grant; bounded by AC07

---

## Acceptance Criteria

- [ ] `from parrot.interagent import ArtifactHandle, HandleStore, SquawkError` works
- [ ] Non-owner, expired and unknown claims raise `HandleClaimError` with identical `str()` (AC07)
- [ ] Grantee in `grants` can claim; owner-only `grant`
- [ ] `pytest packages/ai-parrot/tests/interagent/test_handles.py -q` passes; `ruff check packages/ai-parrot/src/parrot/interagent` clean
- [ ] No import of `parrot.squawk`, `parrot.semantic`, `capnp`, `biscuit_auth` (AC22)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/interagent/test_handles.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/interagent/test_handles.py
import pytest
from datetime import datetime, timedelta, timezone
from parrot.interagent import ArtifactHandle, HandleClaimError, HandleDescriptor, HandleOwner, HandleProvenance, InMemoryHandleStore, MediaType, handle_key

def _handle(owner, *, ttl=60, grants=()):
    now = datetime.now(timezone.utc)
    return ArtifactHandle(key=handle_key(b"x"), media_type=MediaType.ARROW, byte_size=1, ttl_s=ttl, expires_at=now + timedelta(seconds=ttl),
                          owner=owner, grants=grants, descriptor=HandleDescriptor(media_type=MediaType.ARROW, byte_size=1, summary={}),
                          provenance=HandleProvenance(serving_agent="hr", cap_id="hr.reports.x", contract_hash="sha256:" + "0"*64, args_digest="d",
                                                      backing="deterministic", produced_at=now, trace_id="t"))

async def test_claim_same_code_for_every_mismatch():
    owner = HandleOwner(agent_id="a", user_id="u", tenant_id="t", session_id="s")
    other = owner.model_copy(update={"agent_id": "b"})
    store = InMemoryHandleStore()
    await store.put(_handle(owner))
    msgs = set()
    for key, who in ((handle_key(b"x"), other), ("sha256:" + "f"*64, owner)):
        with pytest.raises(HandleClaimError) as ei:
            await store.claim(key, owner=who)
        msgs.add(str(ei.value))
    assert msgs == {"handle_unavailable"}
    # FILL IN: expired variant (ttl=1, expires_at in the past) and grantee success path
```

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug inter-agent-protocol --feature-id FEAT-746`)
2. **Read the spec** §2 Data Models, §3 M1, §8 Q1/Q3
3. **Check dependencies** — none
4. **Verify the Codebase Contract**
5. **Update status** → `"in-progress"`, commit only the index
6. **Implement** from the blueprint
7. **Verify** — Validation Commands (`PYTHONPATH=packages/ai-parrot/src` in the worktree)
8. **Commit** — only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-4739 inter-agent-protocol verified`
10. **Completion Note**

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
