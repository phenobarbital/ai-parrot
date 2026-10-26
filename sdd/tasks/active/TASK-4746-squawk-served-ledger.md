# TASK-4746: M9a — `ServedLedger` (fail-closed, signed) and the Postgres sink

**Feature**: FEAT-746 — Squawk: typed binary inter-agent protocol
**Spec**: `sdd/specs/inter-agent-protocol.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4737, TASK-4740
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (first slice; S8, AC06): the served ledger signs every `ServedLedgerEntry` with a core `AbstractKMSSigner` and, when a durable sink is configured, commits it **before** the caller gets a result — a sink failure with `required=True` raises `LedgerUnavailable`, which the dispatcher (M8, gated) maps to `UPSTREAM_FAILED(audit_unavailable)`. This is deliberately the opposite of `AuditLedger.append`, which stores in memory first and swallows storage failures. The Postgres sink mirrors FEAT-704 M8's asyncpg sink shape.

---

## Scope

- `parrot/squawk/server/{__init__,ledger}.py`: `LedgerUnavailable`, `ServedLedger(signer, sink, *, max_entries)` with `append(entry, *, required=True)`, `verify`, `durable`, `recent(limit)`; `postgres_ledger_sink(dsn_or_pool, *, table="squawk_served_ledger")`.
- `parrot/squawk/sql/squawk_served_ledger.sql` (DDL: entry_id PK, created_at, caller jsonb, cap_id, category, contract_hash, args_digest, status, result_digest, cost jsonb, backing, trace_id, correlation_id, signature, raw jsonb).
- Tests: `tests/server/{__init__,test_served_ledger}.py` (LocalHMACSigner round trip; sink-raises ⇒ `LedgerUnavailable` and the entry is NOT in `recent()`; `required=False` keeps the entry and logs).

**NOT in scope**: renderer/promotion (TASK-4747), dispatcher wiring (M8), a live Postgres test (the sink is tested with a fake pool).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-squawk/src/parrot/squawk/server/__init__.py` | CREATE | exports |
| `packages/ai-parrot-squawk/src/parrot/squawk/server/ledger.py` | CREATE | `ServedLedger`, sink |
| `packages/ai-parrot-squawk/src/parrot/squawk/sql/squawk_served_ledger.sql` | CREATE | DDL |
| `packages/ai-parrot-squawk/tests/server/__init__.py` | CREATE | tests package |
| `packages/ai-parrot-squawk/tests/server/test_served_ledger.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.security.audit_ledger import AbstractKMSSigner, LocalHMACSigner   # verified: packages/ai-parrot/src/parrot/security/audit_ledger.py:135, :166
from parrot.interagent import ServedLedgerEntry   # TASK-4740 (canonical_bytes excludes `signature`)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/security/audit_ledger.py
class AbstractKMSSigner(ABC):                                  # line 135
    async def sign(self, data: bytes) -> str                   # line 143 — hex signature
    async def verify(self, data: bytes, signature: str) -> bool   # line 154
class LocalHMACSigner(AbstractKMSSigner): def __init__(self, secret: Optional[bytes] = None)   # lines 166, 180
class AuditLedger: def __init__(...)  # :327 — storage: Callable[[str], Awaitable[None]] shape (reuse the callable contract, NOT the swallow-failure behaviour of append :338-405)
```

### Does NOT Exist
- ~~`parrot.security.ServedLedger`~~ — satellite-only.
- ~~`asyncdb` for the sink~~ — use `asyncpg` directly (same decision as FEAT-704 M8); `asyncpg` is a core dependency (verify with `python -c "import asyncpg"`).
- ~~`AuditLedger` subclassing~~ — mechanism-only reuse (signers), never the class.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-squawk/src/parrot/squawk/server/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/src/parrot/squawk/server/ledger.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/src/parrot/squawk/sql/squawk_served_ledger.sql", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/tests/server/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/tests/server/test_served_ledger.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/security/audit_ledger.py#AbstractKMSSigner",
    "sym:packages/ai-parrot/src/parrot/security/audit_ledger.py#LocalHMACSigner"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Ordering in `append`: `signature = await signer.sign(entry.canonical_bytes())` → `signed = entry.model_copy(update={"signature": signature})` → `await sink(signed.model_dump_json())` (if sink) → only then append to the deque and return. On sink exception: `required=True` ⇒ raise `LedgerUnavailable` from it (entry not retained); `required=False` ⇒ `self.logger.error(...)`, retain, return.
- `durable` ⇒ `sink is not None`.
- `postgres_ledger_sink`: accepts a DSN (creates a pool lazily on first call) or an existing pool; `INSERT` with `ON CONFLICT (entry_id) DO NOTHING`; connection errors propagate.

### References in Codebase
- `sdd/specs/semantic-layer.spec.md` M8 — `SemanticAuditLedger.append(required=...)` / `postgres_audit_storage` shape being generalized.

---

## Implementation Blueprint

### Steps (in order)
1. DDL — *why*: the sink's INSERT targets it.
2. `ledger.py` — *why*: the ordering is the whole point (S8).
3. Tests with a raising sink.

### `packages/ai-parrot-squawk/src/parrot/squawk/sql/squawk_served_ledger.sql` (CREATE)
```sql
-- FEAT-746 M9a — served ledger durable sink (one row per signed ServedLedgerEntry)
CREATE TABLE IF NOT EXISTS squawk_served_ledger (
    entry_id        TEXT PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL,
    caller          JSONB NOT NULL,
    cap_id          TEXT NOT NULL,
    category        TEXT NOT NULL,
    contract_hash   TEXT NOT NULL,
    args_digest     TEXT NOT NULL,
    status          TEXT NOT NULL,
    result_kind     TEXT NOT NULL,
    result_digest   TEXT,
    cost            JSONB NOT NULL,
    backing         TEXT NOT NULL,
    trace_id        TEXT NOT NULL,
    correlation_id  TEXT,
    signature       TEXT NOT NULL,
    raw             JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS squawk_served_ledger_cap_idx ON squawk_served_ledger (cap_id, created_at DESC);
CREATE INDEX IF NOT EXISTS squawk_served_ledger_trace_idx ON squawk_served_ledger (trace_id);
```

### `packages/ai-parrot-squawk/src/parrot/squawk/server/ledger.py` (CREATE)
```python
"""Served ledger: sign → durable commit → acknowledge (FEAT-746 M9a, S8). Never swallows a required sink failure."""
from __future__ import annotations

import json
import logging
from collections import deque
from typing import Any, Awaitable, Callable

from parrot.interagent import ServedLedgerEntry
from parrot.security.audit_ledger import AbstractKMSSigner  # verified: packages/ai-parrot/src/parrot/security/audit_ledger.py:135

Sink = Callable[[str], Awaitable[None]]


class LedgerUnavailable(Exception):
    """Required durable commit failed; the dispatcher maps this to UPSTREAM_FAILED('audit_unavailable')."""


class ServedLedger:
    def __init__(self, signer: AbstractKMSSigner, sink: Sink | None = None, *, max_entries: int = 10_000) -> None:
        self._signer = signer
        self._sink = sink
        self._recent: deque[ServedLedgerEntry] = deque(maxlen=max_entries)
        self.logger = logging.getLogger(__name__)

    @property
    def durable(self) -> bool:
        return self._sink is not None

    async def append(self, entry: ServedLedgerEntry, *, required: bool = True) -> ServedLedgerEntry:
        """Sign, then commit to the sink BEFORE returning; failure + required ⇒ LedgerUnavailable (entry not retained)."""
        signature = await self._signer.sign(entry.canonical_bytes())
        signed = entry.model_copy(update={"signature": signature})
        if self._sink is not None:
            try:
                await self._sink(signed.model_dump_json())
            except Exception as exc:  # noqa: BLE001
                if required:
                    raise LedgerUnavailable(str(exc)) from exc
                self.logger.error("ServedLedger: sink failed (not required): %s", exc)
        self._recent.append(signed)
        return signed

    async def verify(self, entry: ServedLedgerEntry) -> bool:
        return await self._signer.verify(entry.canonical_bytes(), entry.signature)

    def recent(self, *, limit: int = 100) -> list[ServedLedgerEntry]:
        return list(self._recent)[-limit:]


def postgres_ledger_sink(dsn_or_pool: str | Any, *, table: str = "squawk_served_ledger") -> Sink:
    """asyncpg INSERT ... ON CONFLICT DO NOTHING; connection errors propagate to append()."""
    import asyncpg  # core dependency; local import keeps the module importable without a DB

    state: dict[str, Any] = {"pool": None if isinstance(dsn_or_pool, str) else dsn_or_pool}

    async def sink(payload: str) -> None:
        if state["pool"] is None:
            state["pool"] = await asyncpg.create_pool(dsn_or_pool)
        row = json.loads(payload)
        # FILL IN: INSERT the columns of squawk_served_ledger.sql from `row` (jsonb columns via json.dumps) with ON CONFLICT (entry_id) DO NOTHING — bounded by the DDL
        raise NotImplementedError

    return sink
```
**Why this shape**: the three-step ordering is AC06; `recent()` is for the renderer/promotion (TASK-4747), bounded so memory never grows unbounded.

### FILL IN checklist
- [ ] `ledger.py::postgres_ledger_sink.sink` INSERT; bounded by the DDL columns
- [ ] tests: fake pool object with `acquire()`/`execute()` to exercise the INSERT without a DB

---

## Acceptance Criteria

- [ ] Signed entry verifies with `LocalHMACSigner`; tampering a field breaks `verify`
- [ ] Sink raising + `required=True` ⇒ `LedgerUnavailable`, entry absent from `recent()`; `required=False` ⇒ retained + error logged
- [ ] `durable` reflects sink presence; `recent(limit)` bounded
- [ ] Tests pass; ruff clean

---

## Validation Commands

- `pytest packages/ai-parrot-squawk/tests/server/test_served_ledger.py -q`

---

## Test Specification

Build a `ServedLedgerEntry` fixture (status "OK", backing deterministic); sinks: `ok_sink` (records payloads), `bad_sink` (raises RuntimeError).

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug inter-agent-protocol --feature-id FEAT-746`)
2. **Read the spec** §3 M9, §9 S8, AC06
3. **Check dependencies** — TASK-4737, TASK-4740 `"done"`
4. **Verify the Codebase Contract**
5. **Update status** → `"in-progress"`, commit only the index
6. **Implement**
7. **Verify** — Validation Commands
8. **Commit** — only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-4746 inter-agent-protocol verified`
10. **Completion Note**

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
