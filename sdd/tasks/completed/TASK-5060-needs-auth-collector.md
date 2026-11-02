# TASK-5060: Core needs-auth collector (`parrot/auth/pending.py`) + ToolManager recording

**Feature**: FEAT-775 — Connections on MS Teams
**Spec**: `sdd/specs/connections-msteams.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Needs-auth collector", §3 Module 5, AC-9. A channel wrapper needs to know, after `agent.ask()`
returns, which tools needed a connection during the turn. `ToolManager.execute_tool` already turns
`AuthorizationRequired` / `CredentialRequired` into `ToolResult(status="authorization_required")` with an
`AuthRequiredPayload` (tools/manager.py:2274-2291), but that payload is lost before it reaches the wrapper
(clients/base.py:1668 — do NOT edit that file). This task adds a ContextVar-bound list and one recording call.

**Shared-file rule (spec §2 "Shared with FEAT-776")**: FEAT-776 TASK-5016 and FEAT-777 TASK-5050 plan the
identical module. Whichever merges first creates it. **Before writing code** run
`git fetch origin && git show origin/dev:packages/ai-parrot/src/parrot/auth/pending.py`. If the file exists,
do NOT create a second module and do NOT add a second `record_auth_requirement` call: verify it matches the
contract below, then add only the missing tests from this task. Exactly one `def collect_auth_requirements`
may exist under `packages/`.

---

## Scope

- Create `packages/ai-parrot/src/parrot/auth/pending.py` with `collect_auth_requirements()` and
  `record_auth_requirement()` (unless the shared-file rule above applies).
- In `ToolManager.execute_tool`'s unified needs-auth branch, call `record_auth_requirement(payload)` once,
  before building the `ToolResult`.
- Unit tests: `test_collector_unbound_is_noop`, `test_collector_sees_appends_from_child_tasks`,
  `test_toolmanager_records_needs_auth`.

**NOT in scope**: Teams rendering (TASK-5075), the LLM-facing message in `clients/base.py` (FEAT-776 M2),
any change to how the payload is built.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/pending.py` | CREATE | ContextVar collector (skip if already on origin/dev) |
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | one `record_auth_requirement(payload)` call |
| `packages/ai-parrot/tests/auth/test_pending_auth.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.credentials import AuthRequiredPayload, CredentialRequired   # verified: auth/credentials.py:114, :128
from parrot.auth.exceptions import AuthorizationRequired                     # verified: tools/manager.py:20
# tools/manager.py uses relative imports:
from ..auth.credentials import CredentialRequired                            # verified: tools/manager.py:19
from ..auth.exceptions import AuthorizationRequired                          # verified: tools/manager.py:20
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/credentials.py:114
class AuthRequiredPayload(BaseModel):
    provider: str; auth_url: Optional[str] = None; scopes: List[str]; tool_name: Optional[str] = None
    message: str = ""; auth_kind: Optional[AuthKind] = None; user_code: Optional[str] = None
    verification_uri: Optional[str] = None; expires_in: Optional[int] = None

# packages/ai-parrot/src/parrot/tools/manager.py:2274-2291 (inside ToolManager.execute_tool)
        except (AuthorizationRequired, CredentialRequired) as auth_exc:
            payload = (
                auth_exc.to_payload(tool_name=tool_name)
                if isinstance(auth_exc, CredentialRequired)
                else auth_exc.to_payload()
            )
            self.logger.info(                                                  # :2280
                "Authorization required for tool %s: provider=%s",           # :2281
                tool_name,
                payload.provider,
            )
            return ToolResult(success=False, status="authorization_required", result=None,
                              error=payload.message, metadata=payload.model_dump())
```

### Does NOT Exist
- ~~`parrot.auth.pending`~~ — created here (unless another feature merged it first; see Context).
- ~~`ToolResult.metadata` on `AIMessage.tool_calls[*].result`~~ — lost at clients/base.py:1668; do not "fix" it here.
- ~~`ToolManager.pending_auth`~~ / ~~an `on_auth_required` hook~~ — no such attribute or hook.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/auth/pending.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/tools/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/auth/test_pending_auth.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/credentials.py#AuthRequiredPayload",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.execute_tool"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The ContextVar holds a **list**; `asyncio.create_task` copies the context, so child tasks share the same
  list object — appends are visible, rebinding is not. Never rebind inside `record_auth_requirement`.
- Reset with the token returned by `ContextVar.set` in a `finally`, so nested collectors restore the outer one.
- `record_auth_requirement` is a no-op when unbound — non-Teams callers see no change (AC-9).
- Import `pending` lazily or at module top in `tools/manager.py`; `parrot/auth/pending.py` must import nothing
  from `parrot.tools` (no cycle).

---

## Implementation Blueprint

### Steps (in order)
1. Run the shared-file check in Context — *why*: three features plan this module; only one may create it.
2. Create `pending.py` from the block below — *why*: fixed spec §3 M5 skeleton.
3. Add the import and the one call in `tools/manager.py` — *why*: the unified branch already covers both exceptions.
4. Write the three tests; run Validation Commands.

### `packages/ai-parrot/src/parrot/auth/pending.py` (CREATE)
```python
"""Request-scoped collector for tool needs-auth signals (FEAT-775 M5 / FEAT-776 M1).

A channel wrapper binds a collector around one agent turn; ``ToolManager`` appends every
``AuthRequiredPayload`` it produces. Unbound, recording is a no-op.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, List, Optional

from parrot.auth.credentials import AuthRequiredPayload

_PENDING_AUTH: ContextVar[Optional[List[AuthRequiredPayload]]] = ContextVar("parrot_pending_auth", default=None)


@contextmanager
def collect_auth_requirements() -> Iterator[List[AuthRequiredPayload]]:
    """Bind a fresh list for the current context and yield it.

    Yields:
        The list that ``record_auth_requirement`` appends to while bound.
    """
    collected: List[AuthRequiredPayload] = []
    token = _PENDING_AUTH.set(collected)
    try:
        yield collected
    finally:
        _PENDING_AUTH.reset(token)


def record_auth_requirement(payload: AuthRequiredPayload) -> None:
    """Append ``payload`` to the bound collector; do nothing when none is bound.

    Args:
        payload: The needs-auth payload built by ``ToolManager``.
    """
    collected = _PENDING_AUTH.get()
    if collected is not None:
        collected.append(payload)
```
**Why this shape**: spec §3 M5 fixes the names, the ContextVar name and the no-op rule. A mutable list (not
an immutable tuple rebound per append) is what makes appends from `asyncio.gather` children visible.

### `packages/ai-parrot/src/parrot/tools/manager.py` (MODIFY)
```python
# AFTER — insert below `from ..auth.exceptions import AuthorizationRequired` (verified: tools/manager.py:20)
# occurrences: 1 (verified: grep -cxF 'from ..auth.exceptions import AuthorizationRequired' tools/manager.py)
from ..auth.pending import record_auth_requirement

# BEFORE — insert above `            self.logger.info(` that precedes
#   `                "Authorization required for tool %s: provider=%s",` (verified: tools/manager.py:2280-2281)
# occurrences: 1 (verified: grep -cxF '                "Authorization required for tool %s: provider=%s",' tools/manager.py)
            record_auth_requirement(payload)
```
**Why**: one call in the unified branch records both `AuthorizationRequired` and `CredentialRequired` exactly
once; it must run before the `return`.

### `packages/ai-parrot/tests/auth/test_pending_auth.py` (CREATE)
```python
"""FEAT-775 M5: needs-auth collector."""
import asyncio

import pytest

from parrot.auth.credentials import AuthRequiredPayload
from parrot.auth.pending import collect_auth_requirements, record_auth_requirement


def _payload(provider: str = "jira") -> AuthRequiredPayload:
    return AuthRequiredPayload(provider=provider, scopes=["read"])


def test_collector_unbound_is_noop():
    record_auth_requirement(_payload())  # must not raise
    # FILL IN: assert a later collector starts empty — bounded by AC-9


@pytest.mark.asyncio
async def test_collector_sees_appends_from_child_tasks():
    # FILL IN: bind, asyncio.gather two coroutines that each record one payload, assert len == 2 and
    # the collector is unbound after the with-block — bounded by spec §7 "Collector and concurrency"
    ...


@pytest.mark.asyncio
async def test_toolmanager_records_needs_auth():
    # FILL IN: register two fake tools on a real ToolManager — one raising AuthorizationRequired, one raising
    # CredentialRequired — execute each inside collect_auth_requirements(); assert exactly one payload per call
    # and the ToolResult status is still "authorization_required" — bounded by AC-9
    ...
```

### FILL IN checklist
- [ ] Shared-file check done and recorded in the Completion Note (created vs. verified-existing)
- [ ] `test_collector_unbound_is_noop` second assertion
- [ ] `test_collector_sees_appends_from_child_tasks` body
- [ ] `test_toolmanager_records_needs_auth` body (real ToolManager, fake tools)

---

## Acceptance Criteria

- [ ] `record_auth_requirement` is a no-op outside `collect_auth_requirements()` (AC-9).
- [ ] Appends from child tasks are visible to the binding caller; the ContextVar is reset on exit.
- [ ] `ToolManager.execute_tool` records both exception kinds exactly once; its return value is unchanged.
- [ ] Exactly one `def collect_auth_requirements` under `packages/`; `clients/base.py` untouched.
- [ ] `ruff check` clean on touched files.

## Validation Commands
- `pytest packages/ai-parrot/tests/auth/test_pending_auth.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_collector_unbound_is_noop` | no exception; no leakage into a later collector |
| `test_collector_sees_appends_from_child_tasks` | two gathered children → two payloads; unbound after exit |
| `test_toolmanager_records_needs_auth` | one payload per needs-auth tool call, both exception kinds |

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-msteams --feature-id FEAT-775`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/connections-msteams.json`
4. **Verify the Codebase Contract** — before writing ANY code confirm every import and signature still exists;
   if anything changed, update the contract FIRST; never reference anything listed under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH` pointing at the changed packages
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-<NNN> connections-msteams verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Implemented by gpt-5.6-terra (codex), 1 attempt, merged via sdd-worker; engine fidelity gate passed; merge-tier validation green (chunk 0). Review: diffstat in scope, 0 corrections (review recorded via coder_record_review).

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

