# TASK-4474: Signed audit ledger and optional Postgres sink (M8)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4464
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Owner-approved contract clarification (2026-10-25): `SemanticAuditLedger.verify` is async, matching the updated spec and `AbstractKMSSigner.verify`; callers and tests await it.

Spec rev 0.4, §3 M8; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Implement SemanticAuditEntry and bounded SemanticAuditLedger using async AbstractKMSSigner sign/verify, canonical sorted JSON without signature and independent async storage.
- Keep engine fixed native as provenance only. Every allowed/denied/validation/execution outcome is representable; SQL belongs in audit not exception messages.
- Implement postgres_audit_storage(dsn_or_pool, table=...) and satellite SQL DDL. Validate/quote table identifiers and bind payload parameters. Injected pools are not closed; owned connections always close.
- required=True withholds result on sink failure; optional mode logs failure. Test signatures, tampering, configured durability and fake asyncpg insert; do not run shared DDL.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/audit.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/src/parrot/semantic/sql/semantic_audit_events.sql` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_audit.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from .errors import SemanticExecutionError
from __future__ import annotations
from collections import deque
from datetime import datetime
from parrot.security import AbstractKMSSigner, LocalHMACSigner
from pathlib import Path
from pydantic import BaseModel
from typing import Any, Awaitable, Callable, Literal
import json
import logging
import pytest
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/security/audit_ledger.py:135
class AbstractKMSSigner(ABC):
    # line 143
    async def sign(self, data: bytes) -> str:
    # line 154
    async def verify(self, data: bytes, signature: str) -> bool:
```

```python
# packages/ai-parrot/src/parrot/security/audit_ledger.py:166
class LocalHMACSigner(AbstractKMSSigner):
    # line 180
    def __init__(self, secret: Optional[bytes]=None) -> None:
    # line 183
    async def sign(self, data: bytes) -> str:
    # line 187
    async def verify(self, data: bytes, signature: str) -> bool:
```

### Dependency Contracts and Parallelism Evidence

- TASK-4464: consumes packages/ai-parrot-semantic/src/parrot/semantic/errors.py, packages/ai-parrot-semantic/src/parrot/semantic/models.py (Query/result contracts and trusted identity model (M2))

- Consumer-specific evidence: SemanticExecutionError for required-audit failures

### Does NOT Exist

- `parrot.semantic` on dev — the package and symbols are created by this graph, never imported from the salvage branch environment.
- A semantic engine selector, sidemantic adapter or sidemantic parity oracle — native SQL generation is the only path.
- `PermissionContext.session_id` or `.agent_id` — the satellite identity contract carries trusted scope; request_id is not a session id.
- Automatic semantic authorization in `DatasetManager.add_dataframe()` — retained snapshots require the guarded host-sink contract.

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

## Implementation Notes

- Keep the scope and signatures fixed by spec rev 0.4. Complete the bounded blueprint gaps, not a broad refactor. Preserve the clean-room rule: do not open sidemantic source/API glue.
- Use async I/O, Pydantic v2, strict types and Google-style docstrings. CPU SQL passes run off the event loop. Use logging, not print; black/ruff are the format/lint gates.
- Run in the feature worktree with the existing venv activated; never repair the shared environment. Write test logs to `artifacts/logs/`.
- The full-file snippets below are starting points. Recheck dependency-created MODIFY anchors after their tasks land; they cannot be falsely reported verified on dev today.

## Implementation Blueprint

### Steps (in order)

1. Verify existing anchors and dependency contracts — because stale signatures invalidate a mechanical implementation.
2. Implement the listed targets in their blueprint order — because each target has one explicit owner and the graph orders shared writers.
3. Complete all scope-specific validation branches and regression scenarios — because success-path-only tests cannot establish the required fail-closed behavior.
4. Run this task's validation commands and focused lint — because only evidence from its declared files closes this task.

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

from parrot.security import AbstractKMSSigner, LocalHMACSigner

from .errors import SemanticExecutionError

logger = logging.getLogger(__name__)


class SemanticAuditEntry(BaseModel):
    schema_version: int = 1
    entry_id: str
    created_at: datetime
    user_id: str
    tenant_id: str
    channel: str
    agent_id: str | None
    subject_digest: str
    roles: list[str]
    static_subject: bool
    model: str
    model_digest: str
    policy_digest: str
    engine: str = "native"
    tool: str
    structured_query: dict | None
    raw_sql: bool
    compiled_sql: str | None
    governed_sql: str | None
    dialect: str
    driver: str
    rls_applied: list[str]
    masked_columns: list[str]
    pbac: Literal["allow", "deny", "unavailable", "not_governed"]
    outcome: Literal["ok", "denied", "validation_error", "execution_error"]
    error_code: str | None
    row_count: int | None
    duration_ms: int | None
    signature: str = ""

    def canonical_bytes(self) -> bytes:
        """Sorted-key JSON without `signature` (same approach as AuditLedgerEntry.canonical_bytes)."""
        data = self.model_dump(mode="json", exclude={"signature"})
        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


```

```python
class SemanticAuditLedger:
    def __init__(self, signer: AbstractKMSSigner | None = None,
                 storage: Callable[[str], Awaitable[None]] | None = None, max_entries: int = 10_000) -> None:
        self.signer = signer or LocalHMACSigner()
        self.storage = storage
        self.entries: deque[SemanticAuditEntry] = deque(maxlen=max_entries)

    @property
    def durable(self) -> bool:
        """True when a storage callable is configured — drives audit_required=None resolution (§8 Q5)."""
        return self.storage is not None

    async def append(self, entry: SemanticAuditEntry, *, required: bool = False) -> SemanticAuditEntry:
        """Sign, keep in memory, forward JSON to storage; storage failure raises only when required."""
        # FILL IN: signature = await signer.sign(canonical_bytes) when signer (check sign()'s arg type at audit_ledger.py:143);
        #   append; try await storage(entry.model_dump_json()) except Exception: logger.error(...);
        #   if required: raise SemanticExecutionError("audit_unavailable", details={"audit_id": entry.entry_id})
        raise NotImplementedError

    async def verify(self, entry: SemanticAuditEntry) -> bool:
        """Await signature verification using the configured async KMS signer."""
        # FILL IN: return await self.signer.verify(entry.canonical_bytes(), entry.signature)
        raise NotImplementedError


def postgres_audit_storage(dsn_or_pool: str | Any, *, table: str = "semantic_audit_events") -> Callable[[str], Awaitable[None]]:
    """Async storage(json_str) that INSERTs into `table` (DDL: parrot/semantic/sql/semantic_audit_events.sql)."""
    # FILL IN: validate `table` is a bare identifier; lazy asyncpg.create_pool(dsn) when given a str;
    #   INSERT entry_id, created_at, user_id, tenant_id, model, outcome, payload(::jsonb), signature with $n params
    raise NotImplementedError
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

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

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_audit.py` (CREATE)

```python
"""Regression contract: Signed audit ledger and optional Postgres sink (M8)."""
from pathlib import Path
import pytest


def test_signed_roundtrip_and_tampering(tmp_path: Path) -> None:
    """Verify signed roundtrip and tampering."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_durable_required_and_optional_failures(tmp_path: Path) -> None:
    """Verify durable required and optional failures."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_postgres_storage_bound_values_and_cleanup(tmp_path: Path) -> None:
    """Verify postgres storage bound values and cleanup."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/audit.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/sql/semantic_audit_events.sql` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_audit.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Implement SemanticAuditEntry and bounded SemanticAuditLedger using async AbstractKMSSigner sign/verify, canonical sorted JSON without signature and independent async storage.
- [ ] Keep engine fixed native as provenance only. Every allowed/denied/validation/execution outcome is representable; SQL belongs in audit not exception messages.
- [ ] Implement postgres_audit_storage(dsn_or_pool, table=...) and satellite SQL DDL. Validate/quote table identifiers and bind payload parameters. Injected pools are not closed; owned connections always close.
- [ ] required=True withholds result on sink failure; optional mode logs failure. Test signatures, tampering, configured durability and fake asyncpg insert; do not run shared DDL.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

- [ ] `await ledger.verify(entry)` accepts intact entries and rejects tampered entries; a yielding signer is awaited without blocking the event loop.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_audit.py -q`

## Test Specification

- `test_signed_roundtrip_and_tampering`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_durable_required_and_optional_failures`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_postgres_storage_bound_values_and_cleanup`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4474` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Seat: opus (native), 1 attempt.
Engine fidelity gate clean; merge-tier validation green; orchestrator review approved.
