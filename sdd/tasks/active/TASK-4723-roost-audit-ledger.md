# TASK-4723: Roost audit ledger — one signed entry per performative, joined by trace_id (M10)

**Feature**: FEAT-747 — Roost — local inter-agent sub-protocol over Squawk
**Spec**: `sdd/specs/local-inter-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4711
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 10**. Every performative is a line in the serving agent's ledger and in the caller's
received ledger, joined by the shared `trace_id` (spec G9, AC-27). `AuditLedger.append()` cannot be reused because
it requires `credential_material`; this is a **sibling** ledger that shares the KMS signer abstraction.

---

## Scope

- Create `parrot/roost/audit.py` with `RoostAuditEntry` and `RoostAuditLedger`.
- Write `tests/roost/test_audit.py`.

**NOT in scope**: changing `AuditLedger` or its entries; durable storage backends (duck-typed `storage` only)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/audit.py` | CREATE | Sibling signed ledger |
| `packages/ai-parrot/tests/roost/test_audit.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `6cbd94131` (2026-10-26). Use these exact imports and
> signatures. Do NOT invent any import, attribute or method not listed here — verify first.

### Verified Imports
```python
from parrot.security.audit_ledger import AbstractKMSSigner, LocalHMACSigner   # verified: security/audit_ledger.py:135,166
from parrot.roost.messages import RoostMessage                               # TASK-4711
from parrot.roost.performatives import InteractionProtocol, Performative     # TASK-4711
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/security/audit_ledger.py
class AbstractKMSSigner:                                    # line 135
    async def sign(self, data: bytes) -> str                # line 143 — hex signature
    async def verify(self, data: bytes, signature: str) -> bool   # line 154
class LocalHMACSigner(AbstractKMSSigner)                    # line 166 — random secret when none given
class AuditLedger:                                          # line 296
    def __init__(self, signer=None, storage=None)           # line 327 — pattern to copy (in-memory dict + optional storage)
    async def append(self, *, user_id, channel, tool, provider, credential_material) -> AuditLedgerEntry  # line 338 — DO NOT call
```

### Does NOT Exist
- ~~`AuditLedger.append` without `credential_material` — required kw; never call it from Roost~~
- ~~a performative entry kind on `AuditLedgerEntry` — not added; Roost has its own entry model~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/roost/audit.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/roost/test_audit.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/security/audit_ledger.py#AbstractKMSSigner",
    "sym:packages/ai-parrot/src/parrot/security/audit_ledger.py#LocalHMACSigner",
    "sym:packages/ai-parrot/src/parrot/security/audit_ledger.py#AuditLedger"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Canonical bytes: `json.dumps(entry.model_dump(mode='json', exclude={'signature'}), sort_keys=True, separators=(',', ':')).encode()`.
- `result_digest`: sha256 hex of canonical JSON of `content` when it is a Pydantic model (`model_dump`) or a JSON value; of the string when content is a handle id (`str`); `None` otherwise (frames by reference).
- `storage` is duck-typed: if it has an async `store(entry)` call it; a storage error is logged and re-raised (fail-closed audit).
- Async-first; Pydantic v2 models; `self.logger` / module `logger`, never `print`; Google docstrings; type hints everywhere; 120-column lines.

### References in Codebase
- `packages/ai-parrot/src/parrot/security/audit_ledger.py:296-405` — ledger pattern

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Never change a signature, class name or file
> path the blueprint fixes (they come from the spec's §3 Interface Skeletons).

### Steps (in order)
1. Write `audit.py`.
2. Tests: sign/verify, tamper detection, entries filtered by conversation/trace.

### `packages/ai-parrot/src/parrot/roost/audit.py` (CREATE)
```python
"""Roost audit ledger — one signed line per performative (FEAT-747 M10)."""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from parrot.security.audit_ledger import AbstractKMSSigner, LocalHMACSigner  # verified: audit_ledger.py:135,166

from .messages import RoostMessage
from .performatives import InteractionProtocol, Performative


class RoostAuditEntry(BaseModel):
    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    direction: Literal["served", "received"]
    sender: str
    receiver: str
    performative: Performative
    protocol: InteractionProtocol
    conversation_id: str
    message_id: str
    trace_id: Optional[str] = None
    result_digest: Optional[str] = None
    body: Optional[str] = None
    signature: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def canonical_bytes(self) -> bytes:
        return json.dumps(self.model_dump(mode="json", exclude={"signature"}), sort_keys=True,
                          separators=(",", ":")).encode("utf-8")


class RoostAuditLedger:
    def __init__(self, signer: Optional[AbstractKMSSigner] = None, storage: Optional[Any] = None) -> None:
        self.logger = logging.getLogger(__name__)
        self._signer = signer or LocalHMACSigner()
        self._storage = storage
        self._entries: dict[str, RoostAuditEntry] = {}

    async def record(self, msg: RoostMessage, *, direction: Literal["served", "received"],
                     self_name: str) -> RoostAuditEntry:
        """Build, sign and persist the entry for *msg* (receiver = self_name when served, else first receiver/filter)."""
        raise NotImplementedError  # FILL IN — Key Constraints 2-3

    async def verify(self, entry: RoostAuditEntry) -> bool:
        return await self._signer.verify(entry.canonical_bytes(), entry.signature)

    def entries(self, *, conversation_id: Optional[str] = None, trace_id: Optional[str] = None) -> list[RoostAuditEntry]:
        return [e for e in self._entries.values()
                if (conversation_id is None or e.conversation_id == conversation_id)
                and (trace_id is None or e.trace_id == trace_id)]
```
**Why**: Model and ledger signatures are spec M10 verbatim; signer reuse is the whole point (no new crypto).

### FILL IN checklist
- [ ] `record` — result_digest rule, sign, store
- [ ] tests

---

## Acceptance Criteria

- [ ] Recorded entry verifies; a mutated entry does not
- [ ] `entries(trace_id=...)` joins both directions
- [ ] `AuditLedger.append` is never called
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/roost/audit.py packages/ai-parrot/tests/roost/test_audit.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree prefix with
> `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`.

- `pytest packages/ai-parrot/tests/roost/test_audit.py -q`

---

## Test Specification

```python
from parrot.roost.audit import RoostAuditLedger
from parrot.roost.messages import AgentAddress, RoostMessage
from parrot.roost.performatives import InteractionProtocol as IP, Performative as P


async def test_sign_verify_join(envelope):
    led = RoostAuditLedger()
    m = RoostMessage(performative=P.INFORM, protocol=IP.INFORM, conversation_id="c", envelope=envelope,
                     sender=AgentAddress(name="a"), receivers=[AgentAddress(name="b")], content={"salary": 1})
    s = await led.record(m, direction="received", self_name="a")
    r = await led.record(m, direction="served", self_name="b")
    assert await led.verify(s) and len(led.entries(trace_id=m.trace_id())) == 2
    s.body = "tampered"
    assert not await led.verify(s)
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug local-inter-agent --feature-id FEAT-747 --spec sdd/specs/local-inter-agent.spec.md --index sdd/tasks/index/local-inter-agent.json`)
2. **Read the spec** at `sdd/specs/local-inter-agent.spec.md` (§2 Data Models and the §3 module this task implements)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/local-inter-agent.json`
4. **Verify the Codebase Contract** — re-run `grep -c` on every MODIFY anchor before editing; a count that
   differs means the anchor moved, `0` means stop and report
5. **Update status** in the index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:`, never rename
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4723 local-inter-agent verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

