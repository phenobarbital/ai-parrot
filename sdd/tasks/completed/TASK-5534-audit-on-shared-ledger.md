# TASK-5534: Accounting audit on the shared semantic ledger

**Feature**: FEAT-713 — Accounting Metrics Layer
**Spec**: `sdd/specs/accounting-metrics-layer.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5531
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 and AC11. Per owner decision U1, accounting entries go to the shipped `SemanticAuditLedger`
instead of a separate ledger. The ledger is typed to `SemanticAuditEntry`; this task widens its annotations to a
`SignableAuditEntry` protocol (no behaviour change), defines `AccountingAuditEntry`, and adds replay:
`rebuild_lineage` recompiles from the discriminated `request_canonical` and verifies model, plan and SQL hashes.

---

## Scope

- `parrot/semantic/audit.py`: add `SignableAuditEntry` (runtime-checkable Protocol) and a `TypeVar` bound to it;
  widen `entries`, `append`, `verify` annotations. `SemanticAuditEntry` untouched.
- `accounting/audit.py`: `AuditMode`, `audit_mode_from_env`, `subject_digest`, `AccountingAuditEntry`,
  `build_entry`, `append_entry`, `rebuild_lineage`.
- `lineage_ref = f"{model_hash}:{plan_hash}:{sql_hash}"`.
- `tests/accounting/test_audit.py`: `test_ledger_accepts_both_entry_types`, `test_audit_entry_signed_and_verifiable`,
  `test_audit_required_fails_closed`, `test_audit_entry_fits_postgres_sink_keys`, `test_assertion_audit_replay`,
  `test_replay_rejects_tampered_plan_hash`.

**NOT in scope**: when the toolkit appends entries (TASK-5537); the Postgres sink itself (unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/audit.py` | MODIFY | protocol + widened annotations |
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/audit.py` | CREATE | accounting entry, append, replay |
| `packages/ai-parrot-semantic/tests/accounting/test_audit.py` | CREATE | audit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.semantic.audit import SemanticAuditEntry, SemanticAuditLedger, postgres_audit_storage   # SL/audit.py:23, :70, :158
from parrot.semantic.errors import SemanticExecutionError          # SL/errors.py:35
from parrot.security import LocalHMACSigner                        # imported at SL/audit.py:14
from parrot.auth.permission import PermissionContext               # CORE/auth/permission.py:81
from parrot.semantic.accounting.compiler import compile_assertion, compile_metric, canonical_request  # TASK-5530/5531
from parrot.semantic.accounting.models import AccountingRequest, Lineage                            # TASK-5526
from parrot.semantic.accounting.errors import AccountingAuditError, AccountingError                 # TASK-5524
```

### Existing Signatures to Use
```python
# SL/audit.py
class SemanticAuditEntry(BaseModel):                       # :23 — NOT modified
    def canonical_bytes(self) -> bytes                     # :60 — model_dump(mode="json", exclude={"signature"}), sort_keys, compact
class SemanticAuditLedger:                                 # :70
    def __init__(self, signer=None, storage=None, max_entries: int = 10_000) -> None   # :79
    self.entries: deque[SemanticAuditEntry] = deque(maxlen=max_entries)                # :87
    async def append(self, entry: SemanticAuditEntry, *, required: bool = False) -> SemanticAuditEntry   # :95
        # sets entry.signature; storage(entry.model_dump_json()) (:117); required + missing/failing sink ⇒
        # SemanticExecutionError("audit_unavailable", details={"audit_id": entry.entry_id})
    async def verify(self, entry: SemanticAuditEntry) -> bool                          # :126
def postgres_audit_storage(...)                            # :158 — reads payload keys entry_id, created_at, user_id,
                                                           #   tenant_id, model, outcome, signature (:179-190)
# CORE/auth/permission.py: PermissionContext.user_id (:132), .tenant_id (:137)
```
Edit-site anchors (each verified `grep -cxF` = 1 at `a45855936e`):
`class SemanticAuditLedger:` (:70), `        self.entries: deque[SemanticAuditEntry] = deque(maxlen=max_entries)` (:87),
`    async def append(self, entry: SemanticAuditEntry, *, required: bool = False) -> SemanticAuditEntry:` (:95),
`    async def verify(self, entry: SemanticAuditEntry) -> bool:` (:126).

### Does NOT Exist
- ~~`SemanticAuditLedger.get()` / `.list()`~~ — only `append`, `verify`, `durable`.
- ~~a subject-digest helper in `SL/audit.py`~~ — this task defines `subject_digest` in `accounting/audit.py`.
- ~~`AuditLedgerEntry` changes~~ — `parrot.security.audit_ledger.AuditLedgerEntry` is not touched.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/audit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/accounting/audit.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/test_audit.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/audit.py#SemanticAuditLedger",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/audit.py#SemanticAuditEntry",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/audit.py#postgres_audit_storage"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The ledger change is annotations only; `packages/ai-parrot-semantic/tests/test_audit.py` must pass unchanged.
- `AccountingAuditEntry` is not frozen (the ledger assigns `signature`).
- `canonical_bytes` identical in shape to `SemanticAuditEntry.canonical_bytes`.
- `subject_digest(None)` = sha256 of `"anonymous"`; otherwise sha256 of `f"{user_id}\x1f{tenant_id}"`. Without a
  context, `user_id = "anonymous"` and `tenant_id = tenant` in the entry.
- `append_entry` maps `mode` to `required=(mode == "required")` and converts
  `SemanticExecutionError("audit_unavailable")` into `AccountingAuditError`.
- `rebuild_lineage`: parse `request_canonical` with `TypeAdapter(AccountingRequest)`; dispatch on `kind`; recompile
  with `entry.dialect`; compare `model_hash`, `plan_hash`, `sql_hash` and `lineage_ref`; any mismatch ⇒
  `AccountingError`.

---

## Implementation Blueprint

### Steps (in order)
1. Widen the ledger annotations; run the existing `tests/test_audit.py` — *why*: proves "behaviour unchanged".
2. Write `accounting/audit.py`.
3. Tests.

### `packages/ai-parrot-semantic/src/parrot/semantic/audit.py` (MODIFY)
```python
# BEFORE `class SemanticAuditLedger:` (verified: SL/audit.py:70) — occurrences: 1
# Add to typing imports: Protocol, TypeVar, runtime_checkable
@runtime_checkable
class SignableAuditEntry(Protocol):
    """What the ledger needs from an entry: an id, a signature slot and a canonical byte form."""

    entry_id: str
    signature: str

    def canonical_bytes(self) -> bytes: ...

    def model_dump_json(self) -> str: ...


_E = TypeVar("_E", bound=SignableAuditEntry)

# REPLACE the line at :87 (occurrences: 1)
        self.entries: deque[SignableAuditEntry] = deque(maxlen=max_entries)
# REPLACE the signature at :95 (occurrences: 1)
    async def append(self, entry: _E, *, required: bool = False) -> _E:
# REPLACE the signature at :126 (occurrences: 1)
    async def verify(self, entry: SignableAuditEntry) -> bool:
```

### `packages/ai-parrot-semantic/src/parrot/semantic/accounting/audit.py` (CREATE)
```python
"""Accounting audit entries on the shared SemanticAuditLedger (FEAT-713 M7)."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal, Mapping

from pydantic import BaseModel, TypeAdapter

from parrot.semantic.audit import SemanticAuditLedger
from parrot.semantic.errors import SemanticExecutionError

from .compiler import canonical_request, compile_assertion, compile_metric
from .errors import AccountingAuditError, AccountingError
from .models import AccountingModel, AccountingRequest, CompiledMetricQuery, Lineage

if TYPE_CHECKING:
    from parrot.auth.permission import PermissionContext

AuditMode = Literal["required", "best_effort"]
_REQUEST = TypeAdapter(AccountingRequest)


class AccountingAuditEntry(BaseModel):
    """Signed by the shared ledger; satisfies SignableAuditEntry."""

    schema_version: Literal[1] = 1
    entry_id: str
    created_at: datetime
    user_id: str
    tenant_id: str
    subject_digest: str
    model: str
    version: str
    model_hash: str
    snapshot_hash: str
    sql_hash: str
    plan_hash: str
    dialect: str
    target: Literal["database", "duckdb"]
    tool: str
    request_canonical: str
    lineage_ref: str
    assertion_status: Literal["passed", "failed", "skipped", "none"]
    outcome: Literal["ok", "denied", "validation_error", "execution_error"]
    row_count: int | None
    duration_ms: int | None
    signature: str = ""

    def canonical_bytes(self) -> bytes:
        """Sorted-key compact JSON without ``signature``."""
        data = self.model_dump(mode="json", exclude={"signature"})
        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def audit_mode_from_env(env: Mapping[str, str] | None = None) -> AuditMode:
    """FINANCE_AUDIT_MODE, default 'required'; unknown values ⇒ ValueError."""
    # FILL IN
    raise NotImplementedError


def subject_digest(context: "PermissionContext | None") -> str:
    """sha256 of (user_id, tenant_id), or of 'anonymous' when there is no context."""
    # FILL IN: see Key Constraints.
    raise NotImplementedError


def build_entry(*, context, tenant: str, model: AccountingModel, compiled: CompiledMetricQuery,
                target: Literal["database", "duckdb"], tool: str, outcome: str, assertion_status: str,
                row_count: int | None, duration_ms: int | None) -> AccountingAuditEntry:
    """Assemble an unsigned entry; lineage_ref = model_hash:plan_hash:sql_hash."""
    # FILL IN: entry_id uuid4 str; created_at now(timezone.utc); request_canonical=canonical_request(compiled.request).
    raise NotImplementedError


async def append_entry(ledger: SemanticAuditLedger, entry: AccountingAuditEntry, *, mode: AuditMode) -> AccountingAuditEntry:
    """ledger.append(entry, required=(mode == 'required')); AccountingAuditError when the sink is missing or fails."""
    try:
        return await ledger.append(entry, required=(mode == "required"))
    except SemanticExecutionError as exc:
        raise AccountingAuditError(str(exc)) from exc


def rebuild_lineage(entry: AccountingAuditEntry, model: AccountingModel) -> Lineage:
    """Recompile from request_canonical; verify model_hash, plan_hash, sql_hash and lineage_ref before returning."""
    # FILL IN: see Key Constraints.
    raise NotImplementedError
```

### `packages/ai-parrot-semantic/tests/accounting/test_audit.py` (CREATE)
```python
"""FEAT-713 M7 — accounting audit on the shared ledger."""

from __future__ import annotations


async def test_ledger_accepts_both_entry_types(recording_storage) -> None:
    # FILL IN: one SemanticAuditLedger signs + verifies a SemanticAuditEntry and an AccountingAuditEntry.


async def test_audit_entry_signed_and_verifiable(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: LocalHMACSigner; verify True; tamper a field ⇒ False.


async def test_audit_required_fails_closed(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: failing sink + required ⇒ AccountingAuditError; best_effort ⇒ entry returned; no sink + required ⇒ error.


def test_audit_entry_fits_postgres_sink_keys(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: json.loads(entry.model_dump_json()) has entry_id, created_at, user_id, tenant_id, model, outcome, signature.


def test_assertion_audit_replay(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: entry from compile_assertion(index 0); rebuild_lineage returns identical Lineage; wrong model or
    #   index ⇒ AccountingError.


def test_replay_rejects_tampered_plan_hash(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: entry with altered plan_hash ⇒ AccountingError.
```

### FILL IN checklist
- [ ] `audit_mode_from_env`, `subject_digest`, `build_entry`, `rebuild_lineage` — AC11.
- [ ] Six tests.

---

## Acceptance Criteria

- [ ] One ledger instance signs and verifies both entry types (AC11).
- [ ] `required` mode fails closed on a missing or failing sink (AC11).
- [ ] Replay verifies model/plan/SQL hashes and `lineage_ref` for metric and assertion requests (AC11, AC17).
- [ ] `packages/ai-parrot-semantic/tests/test_audit.py` passes unchanged.
- [ ] `ruff check` passes on every touched file.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/accounting/test_audit.py -q`
- `pytest packages/ai-parrot-semantic/tests/test_audit.py -q`

---

## Test Specification

See blueprint.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug accounting-metrics-layer --feature-id FEAT-713`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/accounting-metrics-layer.json`
4. **Verify the Codebase Contract** before writing any code; update it first if anything moved
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** — run the Validation Commands with absolute `PYTHONPATH` for both `packages/ai-parrot-semantic/src` and `packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5534 accounting-metrics-layer verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker / native sonnet coder (attempt 0a1334e3160745a2b065e96340a9ca5a), commit 97c37fc9e6
**Date**: 2026-11-12
**Notes**: Added `SignableAuditEntry` protocol + widened annotations in `semantic/audit.py`; created `accounting/audit.py` (AuditMode, audit_mode_from_env, subject_digest, AccountingAuditEntry, build_entry, append_entry, rebuild_lineage). New and existing audit tests pass (10 passed), ruff clean.

**Deviations from spec**: none
