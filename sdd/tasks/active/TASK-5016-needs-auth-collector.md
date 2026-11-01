# TASK-5016: Core needs-auth collector (`parrot/auth/pending.py`)

**Feature**: FEAT-776 — Connections on Telegram
**Spec**: `sdd/specs/connections-telegram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (shared with FEAT-775 M5). A request-scoped collector lets a channel wrapper learn,
after `agent.ask()` returns, which tools needed a connection during the turn. `ToolManager.execute_tool`
already converts `AuthorizationRequired` / `CredentialRequired` into a `ToolResult(status="authorization_required")`
carrying an `AuthRequiredPayload`; this task adds one call that also records that payload into a
ContextVar-bound list when a collector is active.

**Shared-file rule (spec §2 "Shared with FEAT-775")**: whichever feature merges first creates
`parrot/auth/pending.py`. Before writing code, run `git fetch origin && git show origin/dev:packages/ai-parrot/src/parrot/auth/pending.py`.
If it exists, do NOT create a second module: re-verify it matches the contract below and add only the
missing tests. AC-14: exactly one `def collect_auth_requirements` under `packages/`.

---

## Scope

- Create `parrot/auth/pending.py` with `collect_auth_requirements()` and `record_auth_requirement()`.
- In `ToolManager.execute_tool`'s needs-auth branch, call `record_auth_requirement(payload)` before returning.
- Write unit tests `test_collector_unbound_is_noop`, `test_collector_sees_appends_from_child_tasks`,
  `test_toolmanager_records_needs_auth`.

**NOT in scope**: Telegram rendering (TASK-5026), the LLM-facing message (TASK-5017), any change to how
the payload is built.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/pending.py` | CREATE | ContextVar collector |
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | record payload in needs-auth branch |
| `packages/ai-parrot/tests/unit/auth/test_pending_collector.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.credentials import AuthRequiredPayload, CredentialRequired   # verified: auth/credentials.py:114, :128
from parrot.auth.exceptions import AuthorizationRequired                      # verified: auth/exceptions.py:12
from parrot.tools.abstract import ToolResult                                  # verified: clients/base.py:55 imports it
from parrot.tools.manager import ToolManager                                  # verified: tools/manager.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/manager.py
from ..auth.credentials import CredentialRequired      # :19
from ..auth.exceptions import AuthorizationRequired    # :20
#   :2274  except (AuthorizationRequired, CredentialRequired) as auth_exc:
#   :2275-2279  payload = (auth_exc.to_payload(tool_name=tool_name) if isinstance(auth_exc, CredentialRequired) else auth_exc.to_payload())
#   :2285  return ToolResult(success=False, status="authorization_required", result=None, error=payload.message, metadata=payload.model_dump())

# packages/ai-parrot/src/parrot/auth/credentials.py:114
class AuthRequiredPayload(BaseModel):
    provider: str; auth_url: Optional[str]; scopes: List[str]; tool_name: Optional[str]; message: str
    auth_kind: Optional[AuthKind]; user_code: Optional[str]; verification_uri: Optional[str]; expires_in: Optional[int]
```

### Does NOT Exist
- ~~`parrot.auth.pending`~~ — created here (unless FEAT-775 merged it first; see Context).
- ~~`ToolManager.pending_auth`~~ / any per-instance list — state must live in the ContextVar only.
- ~~A second collector module (e.g. `parrot/tools/pending_auth.py`)~~ — never create one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/auth/pending.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/tools/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/auth/test_pending_collector.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.execute_tool",
    "sym:packages/ai-parrot/src/parrot/auth/credentials.py#AuthRequiredPayload"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The ContextVar holds a *list object*; `asyncio.wait_for` / `gather` copy the context, so children see the
  same list reference and their appends are visible to the parent. Never rebind the var inside `record_*`.
- `collect_auth_requirements()` must reset the token in `finally` (exceptions, cancellation).
- Unbound (`None`) → `record_auth_requirement` is a silent no-op: web/A2A paths keep today's behaviour.

---

## Implementation Blueprint

### Steps (in order)
1. Check `origin/dev` for an existing `pending.py` — *why*: FEAT-775 may have created it; two modules violate AC-14.
2. Create `pending.py` from the block below — *why*: verbatim spec contract shared by two features.
3. Insert the record call in `manager.py` — *why*: the only producer of needs-auth `ToolResult`s.
4. Write the three tests and run them.

### `packages/ai-parrot/src/parrot/auth/pending.py` (CREATE)
```python
"""Request-scoped collector of tool needs-auth payloads (FEAT-775 M5 / FEAT-776 M1)."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, List, Optional

from parrot.auth.credentials import AuthRequiredPayload

_PENDING_AUTH: ContextVar[Optional[List[AuthRequiredPayload]]] = ContextVar("parrot_pending_auth", default=None)


@contextmanager
def collect_auth_requirements() -> Iterator[List[AuthRequiredPayload]]:
    """Bind a fresh list for the current context; reset the ContextVar token on exit.

    Yields:
        The list that ``record_auth_requirement`` appends to while bound.
    """
    pending: List[AuthRequiredPayload] = []
    token = _PENDING_AUTH.set(pending)
    try:
        yield pending
    finally:
        _PENDING_AUTH.reset(token)


def record_auth_requirement(payload: AuthRequiredPayload) -> None:
    """Append ``payload`` when a collector is bound; otherwise do nothing."""
    pending = _PENDING_AUTH.get()
    if pending is not None:
        pending.append(payload)


__all__ = ["collect_auth_requirements", "record_auth_requirement"]
```
**Why this shape**: identical to the FEAT-775 M5 skeleton (spec §3 M1). Do not add dedup or filtering here — the
Telegram renderer (TASK-5026) groups by provider.

### `packages/ai-parrot/src/parrot/tools/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        except (AuthorizationRequired, CredentialRequired) as auth_exc:' packages/ai-parrot/src/parrot/tools/manager.py)
# AFTER — the `self.logger.info("Authorization required for tool %s: provider=%s", ...)` call that follows
# `        except (AuthorizationRequired, CredentialRequired) as auth_exc:` (verified: manager.py:2274-2284),
# and BEFORE `return ToolResult(` (:2285):
            record_auth_requirement(payload)

# imports — next to `from ..auth.exceptions import AuthorizationRequired` (:20):
from ..auth.pending import record_auth_requirement
```
**Why**: one call, no other change to the branch (spec Edit Sites row for manager.py).

### `packages/ai-parrot/tests/unit/auth/test_pending_collector.py` (CREATE)
```python
"""Tests for parrot.auth.pending (FEAT-776 M1)."""
import asyncio

import pytest

from parrot.auth.credentials import AuthRequiredPayload
from parrot.auth.pending import collect_auth_requirements, record_auth_requirement


def test_collector_unbound_is_noop() -> None:
    record_auth_requirement(AuthRequiredPayload(provider="jira"))  # must not raise
    # FILL IN: assert nothing leaked into a later bound collector


@pytest.mark.asyncio
async def test_collector_sees_appends_from_child_tasks() -> None:
    # FILL IN: bind, asyncio.gather two children that each record; assert both payloads present; assert reset after exit
    ...


@pytest.mark.asyncio
async def test_toolmanager_records_needs_auth() -> None:
    # FILL IN: ToolManager with a tool raising AuthorizationRequired and one raising CredentialRequired;
    # inside collect_auth_requirements() each execute_tool appends exactly one payload; result.status == "authorization_required"
    ...
```

### FILL IN checklist
- [ ] `test_pending_collector.py` — three test bodies; build the fake tools from existing tool fixtures in `packages/ai-parrot/tests/unit/test_auth_required.py`
- [ ] Verify the reset-on-exception path in `test_collector_sees_appends_from_child_tasks` (or a fourth test)

---

## Acceptance Criteria

- [ ] `grep -rn "def collect_auth_requirements" packages/` matches exactly one definition (AC-14)
- [ ] Both needs-auth exceptions record one payload while bound; unbound is a no-op
- [ ] `ruff check` clean on touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/auth/test_pending_collector.py -q`
- `pytest packages/ai-parrot/tests/unit/test_auth_required.py -q`

---

## Test Specification

See the blueprint test file; names are fixed by spec §4 (M1 rows).

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug connections-telegram --feature-id FEAT-776`)
2. **Read the spec** for full context; check every `Depends-on` is `done` in `sdd/tasks/index/connections-telegram.json`
3. **Verify the Codebase Contract** before writing code; fix stale entries first
4. **Implement** from the blueprint, complete every `# FILL IN:`
5. **Validate** with the commands above (prefix `PYTHONPATH=packages/ai-parrot/src`)
6. **Commit** only the listed files; close with `scripts/sdd/close_task.sh TASK-5016 connections-telegram verified`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
