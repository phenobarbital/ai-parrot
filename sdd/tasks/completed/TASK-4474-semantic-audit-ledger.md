# TASK-4474: Signed semantic audit ledger + Postgres sink (M8)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4464
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 + §8 Q3/Q5 + AC9/AC21: a separate signed `SemanticAuditEntry` ledger reusing the core signers and the async `storage(json_str)` contract, plus the satellite-owned Postgres sink (`semantic_audit_events.sql` + `postgres_audit_storage`).

---

## Scope

- Implement `packages/ai-parrot-semantic/src/parrot/semantic/audit.py`: `SemanticAuditEntry` (+ `canonical_bytes`), `SemanticAuditLedger` (`append(required=)`, `verify`, `durable`), `postgres_audit_storage`.
- Create `packages/ai-parrot-semantic/src/parrot/semantic/sql/semantic_audit_events.sql` modelled on `packages/ai-parrot/src/parrot/security/security_events.sql`.
- Write `test_audit.py`.

**NOT in scope**: resolving `audit_required` (TASK-4477); `AuditLedger` itself (not used — credential-shaped).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/audit.py` | CREATE | entry + ledger + postgres sink |
| `packages/ai-parrot-semantic/src/parrot/semantic/sql/semantic_audit_events.sql` | CREATE | audit table DDL |
| `packages/ai-parrot-semantic/tests/test_audit.py` | CREATE | audit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified on `dev` @ 754878f67, 2026-10-19). Use these exact imports, class names and
> method signatures. **DO NOT** invent, guess or assume anything not listed here — verify first.
> `grep` in this repo is aliased to `ugrep` by RTK: use `grep -F` for anchors with `(`, `[`, `{`.

### Verified Imports
```python
from parrot.security import AbstractKMSSigner, LocalHMACSigner     # verified: security/__init__.py:50-55
from parrot.semantic.errors import SemanticExecutionError          # TASK-4464
import asyncpg                                                    # transitive via ai-parrot (venv 0.32.0)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/security/audit_ledger.py
class AuditLedgerEntry(BaseModel):       # line 80
    def canonical_bytes(self) -> bytes   # line 109 — sorted-key JSON without `signature` (pattern to copy)
class AbstractKMSSigner(ABC):            # line 135 — sign(data) -> str (143); verify(data, signature) -> bool (154)
class LocalHMACSigner(AbstractKMSSigner) # line 166
class AuditLedger:                       # line 296 — storage: async callable(json_str), awaited ~line 383 (pattern only)
# packages/ai-parrot/src/parrot/security/security_events.sql — CREATE TABLE IF NOT EXISTS + JSONB + per-column indexes
```

### Does NOT Exist
- ~~`AuditLedgerEntry.payload` / `.compiled_sql`~~ — credential-shaped only; do not reuse `AuditLedger`.
- ~~`asyncdb` in the satellite~~ — use `asyncpg` directly.
- ~~`LocalHMACSigner()` with no args reading an env key~~ — FILL IN: read its `__init__` (audit_ledger.py:166) before constructing it in tests.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/audit.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/sql/semantic_audit_events.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_audit.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/security/audit_ledger.py#AbstractKMSSigner",
    "sym:packages/ai-parrot/src/parrot/security/audit_ledger.py#LocalHMACSigner"
  ]
}
```

---

## Implementation Notes

- Table `semantic_audit_events(entry_id UUID PK, created_at TIMESTAMPTZ, user_id, tenant_id, model, outcome, payload JSONB, signature TEXT)` + indexes on user_id, tenant_id, model, outcome, created_at DESC.
- `postgres_audit_storage(dsn_or_pool)` accepts a DSN (creates a pool lazily on first call) or an existing pool with `.execute`.

### Key Constraints
- Async-first; sync CPU-only work (sqlglot, sidemantic compile) runs under `asyncio.to_thread` at the call site.
- Pydantic v2 models; `logging.getLogger(__name__)` / `self.logger`, never `print`.
- Google-style docstrings, strict type hints, 120-column lines; `ruff check` clean (TID251 bans apply).
- Fail closed wherever governance is involved (spec §7 "Patterns to Follow").
- Worktree testing: prefix pytest with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` (add `:packages/ai-parrot-server/src` for server tests); never `uv sync` inside a worktree.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim,
> then complete every `# FILL IN:` marker. Never change a signature, class name or path the
> blueprint fixes (they come from the spec §3 Interface Skeletons).

### Steps (in order)
1. Write `SemanticAuditEntry` fields verbatim from spec §3 M8 — *why*: AC9 field list.
2. Write the ledger (bounded deque, sign, storage, `required`) — *why*: §8 Q5.
3. Write DDL + `postgres_audit_storage` — *why*: §8 Q3.
4. Write tests.

### `packages/ai-parrot-semantic/src/parrot/semantic/audit.py` (CREATE)
```python
"""Signed semantic audit ledger (spec §3 Module 8, §8 Q3/Q5)."""
from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel

from parrot.security import AbstractKMSSigner

from .errors import SemanticExecutionError

logger = logging.getLogger(__name__)


class SemanticAuditEntry(BaseModel):
    schema_version: int = 1
    # FILL IN: every field verbatim from spec §3 Module 8 (entry_id ... signature: str = "")

    def canonical_bytes(self) -> bytes:
        """Sorted-key JSON without `signature` (same approach as AuditLedgerEntry.canonical_bytes)."""
        data = self.model_dump(mode="json", exclude={"signature"})
        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


class SemanticAuditLedger:
    def __init__(self, signer: AbstractKMSSigner | None = None,
                 storage: Callable[[str], Awaitable[None]] | None = None, max_entries: int = 10_000) -> None:
        self.signer = signer
        self.storage = storage
        self.entries: deque[SemanticAuditEntry] = deque(maxlen=max_entries)

    @property
    def durable(self) -> bool:
        """True when a storage callable is configured — drives audit_required=None resolution (§8 Q5)."""
        return self.storage is not None

    async def append(self, entry: SemanticAuditEntry, *, required: bool = False) -> SemanticAuditEntry:
        """Sign, keep in memory, forward JSON to storage; storage failure raises only when required."""
        # FILL IN: signature = signer.sign(canonical_bytes) when signer (check sign()'s arg type at audit_ledger.py:143);
        #   append; try await storage(entry.model_dump_json()) except Exception: logger.error(...);
        #   if required: raise SemanticExecutionError("audit_unavailable", details={"audit_id": entry.entry_id})
        raise NotImplementedError

    def verify(self, entry: SemanticAuditEntry) -> bool:
        # FILL IN: signer.verify(canonical_bytes, entry.signature); no signer -> False
        raise NotImplementedError


def postgres_audit_storage(dsn_or_pool: str | Any, *, table: str = "semantic_audit_events") -> Callable[[str], Awaitable[None]]:
    """Async storage(json_str) that INSERTs into `table` (DDL: parrot/semantic/sql/semantic_audit_events.sql)."""
    # FILL IN: validate `table` is a bare identifier; lazy asyncpg.create_pool(dsn) when given a str;
    #   INSERT entry_id, created_at, user_id, tenant_id, model, outcome, payload(::jsonb), signature with $n params
    raise NotImplementedError
```

### `packages/ai-parrot-semantic/src/parrot/semantic/sql/semantic_audit_events.sql` (CREATE)
```sql
-- FEAT-704 §8 Q3 — semantic-layer audit events (one row per SemanticAuditEntry)
CREATE TABLE IF NOT EXISTS semantic_audit_events (
    entry_id UUID PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    user_id VARCHAR(255) NOT NULL,
    tenant_id VARCHAR(255) NOT NULL,
    model VARCHAR(255) NOT NULL,
    outcome VARCHAR(32) NOT NULL,
    payload JSONB NOT NULL,
    signature TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_semantic_audit_user_id ON semantic_audit_events(user_id);
CREATE INDEX IF NOT EXISTS idx_semantic_audit_tenant_id ON semantic_audit_events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_semantic_audit_model ON semantic_audit_events(model);
CREATE INDEX IF NOT EXISTS idx_semantic_audit_outcome ON semantic_audit_events(outcome);
CREATE INDEX IF NOT EXISTS idx_semantic_audit_created_at ON semantic_audit_events(created_at DESC);
```

### FILL IN checklist
- [ ] `SemanticAuditEntry` fields verbatim from spec §3 M8.
- [ ] `append` / `verify`.
- [ ] `postgres_audit_storage` — bounded by §8 Q3.

---

## Acceptance Criteria

- [ ] `test_audit_entry_signature` and `test_postgres_audit_storage_insert` pass (AC9, AC21).
- [ ] `append(required=True)` with a failing sink raises `SemanticExecutionError('audit_unavailable')`; `required=False` only logs.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` in a worktree.

- `pytest packages/ai-parrot-semantic/tests/test_audit.py -q`

---

## Test Specification

```python
# packages/ai-parrot-semantic/tests/test_audit.py
import pytest
import sqlglot
from pathlib import Path
from parrot.semantic.audit import SemanticAuditLedger, postgres_audit_storage
from parrot.semantic.errors import SemanticExecutionError


async def test_audit_entry_signature():
    # FILL IN: LocalHMACSigner(...) ; append -> signature set; verify True; tampered entry -> False;
    #          storage callable receives JSON; failing storage + required=False logs, required=True raises
    ...


async def test_postgres_audit_storage_insert():
    ddl = (Path(__import__("parrot.semantic").semantic.__file__).parent / "sql/semantic_audit_events.sql").read_text()
    assert sqlglot.parse(ddl, read="postgres")
    # FILL IN: fake pool with AsyncMock execute; storage(json) -> execute called with INSERT INTO semantic_audit_events
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer --feature-id FEAT-704 --spec sdd/specs/semantic-layer.spec.md --index sdd/tasks/index/semantic-layer.json`).
2. **Read the spec** (`sdd/specs/semantic-layer.spec.md`), especially the sections named in Context.
3. **Check dependencies** — every `Depends-on` task is `done` in `sdd/tasks/index/semantic-layer.json`.
4. **Verify the Codebase Contract** before writing code; fix a stale entry in this file first.
5. **Implement** exactly the files above, following the blueprint; touch nothing else.
6. **Validate**: `ruff check --fix <files>`, then the Validation Commands.
7. **Commit** only the listed files: `feat(semantic-layer): TASK-4474 — Signed semantic audit ledger + Postgres sink (M8)`.
8. **Close** with `scripts/sdd/close_task.sh TASK-4474 semantic-layer verified` and fill in the Completion Note.

---

## Completion Note

- Task: TASK-4474
- Feature: semantic-layer
- Closed at (UTC): 2026-10-19
- Fix commits: none
- Seat: opus (native) · Attempts: 1 · Tokens: 56k
- Validation: merge-tier ad0839b5:wave3:merge completed exit 0 (12 passed).
- Review: coder-review:22fa92a2043aec3fce7e4d58 — no corrections.
- **Deviation**: SemanticAuditLedger.verify is `async def` (spec §3 skeleton shows sync `def verify(...) -> bool`). Forced: core AbstractKMSSigner.sign/verify are async (parrot/security/audit_ledger.py). Callers must `await ledger.verify(entry)`.
- Unspecified behaviour: append(required=True) with no storage configured raises SemanticExecutionError('audit_unavailable') (fail-closed).
