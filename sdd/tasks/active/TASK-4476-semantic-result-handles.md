# TASK-4476: Owner-bound result handle store (M9b)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4464
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (results) + AC10: opaque, bounded, expiring handles bound to (agent, user, tenant, session, model/policy versions, subject digest); `claim()` re-verifies everything — metadata alone is never authorization.

---

## Scope

- Implement `packages/ai-parrot-semantic/src/parrot/semantic/results.py`: `ResultHandle`, `ResultHandleStore` (`put`, `claim`).
- Write `test_results.py`.

**NOT in scope**: the `sl_save_result_as_dataset` tool (TASK-4479).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/results.py` | CREATE | handle store |
| `packages/ai-parrot-semantic/tests/test_results.py` | CREATE | ownership tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified on `dev` @ 754878f67, 2026-10-19). Use these exact imports, class names and
> method signatures. **DO NOT** invent, guess or assume anything not listed here — verify first.
> `grep` in this repo is aliased to `ugrep` by RTK: use `grep -F` for anchors with `(`, `[`, `{`.

### Verified Imports
```python
import secrets
from datetime import datetime, timedelta, timezone
from parrot.auth import PermissionContext                     # verified: auth/__init__.py lazy map
from parrot.semantic.errors import SemanticResultError        # TASK-4464
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/permission.py
class UserSession:        # line 21 — user_id, tenant_id, roles, metadata (46-49); metadata NOT in the hash (49)
class PermissionContext:  # line 81 — session; request_id; channel; trace_context; extra (122-126)
```

### Does NOT Exist
- ~~`PermissionContext.session_id`~~ — not a field; read the session id from `ctx.extra.get("session_id")` and record that choice (the HTTP handler sets it).
- ~~Sequential/guessable result ids~~ — `secrets.token_urlsafe(24)` only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/results.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_results.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#PermissionContext"
  ]
}
```

---

## Implementation Notes

- Every mismatch raises the SAME code (`result_unavailable`) — never reveal whether a handle exists for someone else.
- Eviction: drop expired entries on every put/claim, then oldest beyond `max_entries`.

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
1. Write `ResultHandle` verbatim from spec §3 M9.
2. Write the store with constant error codes — *why*: AC10.
3. Write tests.

### `packages/ai-parrot-semantic/src/parrot/semantic/results.py` (CREATE)
```python
"""Opaque, bounded, expiring, owner-bound result handles (spec §3 Module 9, AC10)."""
from __future__ import annotations

import secrets
import threading
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from parrot.auth import PermissionContext

from .errors import SemanticResultError


class ResultHandle(BaseModel):
    result_id: str = ""
    agent_id: str | None
    user_id: str
    tenant_id: str
    session_id: str | None
    subject_digest: str
    model: str
    model_digest: str
    policy_digest: str
    expires_at: datetime
    columns: list[str]
    rows: list[dict]
    audit_id: str
    governed_sql: str


class ResultHandleStore:
    def __init__(self, *, ttl_s: int = 900, max_entries: int = 256) -> None:
        self.ttl = timedelta(seconds=ttl_s)
        self.max_entries = max_entries
        self._data: OrderedDict[str, ResultHandle] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, handle: ResultHandle) -> str:
        """Store with a fresh opaque id (secrets.token_urlsafe) and expires_at = now + ttl."""
        # FILL IN: purge expired; assign id + expires_at via model_copy; evict oldest beyond max_entries
        raise NotImplementedError

    def claim(self, result_id: str, *, ctx: PermissionContext, subject_digest: str,
              model_digest: str, policy_digest: str) -> ResultHandle:
        """Owner, session, subject digest and versions must match and the handle be unexpired."""
        # FILL IN: any mismatch/unknown/expired -> SemanticResultError("result_unavailable") (same code always)
        raise NotImplementedError
```

### FILL IN checklist
- [ ] `put` / `claim` — bounded by AC10.

---

## Acceptance Criteria

- [ ] `test_result_handle_ownership` passes: foreign user, other session, changed subject digest, changed policy digest, expired, unknown → same `result_unavailable` error (AC10).

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` in a worktree.

- `pytest packages/ai-parrot-semantic/tests/test_results.py -q`

---

## Test Specification

```python
# packages/ai-parrot-semantic/tests/test_results.py
import pytest
from parrot.semantic.results import ResultHandleStore, ResultHandle
from parrot.semantic.errors import SemanticResultError


def test_result_handle_ownership(pctx_factory):
    # FILL IN: put a handle for user-a; claim as user-b / other session / changed digests / after expiry
    #          (ttl_s=0) -> SemanticResultError with code "result_unavailable"; owner claim succeeds
    ...
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
7. **Commit** only the listed files: `feat(semantic-layer): TASK-4476 — Owner-bound result handle store (M9b)`.
8. **Close** with `scripts/sdd/close_task.sh TASK-4476 semantic-layer verified` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
