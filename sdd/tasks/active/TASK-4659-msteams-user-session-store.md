# TASK-4659: MSTeamsUserSession and the shared-store session store

**Feature**: FEAT-729 — MS Teams user authentication lane
**Spec**: `sdd/specs/msteams-user-auth-lane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **spec §3 Module 1**. The Teams lane is identity-blind today: the
wrapper passes `{"user_id": from_property.id}` to the agent and nothing else.
This task creates the per-user session object that the rest of the feature
populates, plus the store that keeps it.

**Spec Q3 (resolved 2026-10-23)** decides the storage shape, and its original
premise was wrong — read the resolution in the spec before starting. Telegram's
session is **not** Redis-backed: it is a plain dataclass in an in-process dict
(`telegram/wrapper.py:177`), and `telegram/auth.py:78` documents the three
isolation slots as *"Kept process-local (no Redis serialization)"* because
`tool_manager` and `user_agent` are live objects that cannot be serialized.

So the shape is a **hybrid**: the serializable auth fields round-trip through an
injected store (the same `set/get/delete(expire=)` protocol
`IntegrationStateManager` already uses), while the three isolation slots stay
process-local. TTL comes from `external_expires_at` — never hard-coded, which is
the defect the ledger already records against `AudioSessionStore`
(`issue:d92b765f8c4d`).

---

## Scope

- Implement `MSTeamsUserSession` in a new `msteams/auth.py`, mirroring
  `TelegramUserSession`'s field layout and its `repr=False, compare=False`
  treatment of the isolation slots.
- Implement `user_key(turn_context)` with the **same precedence as
  `_get_user_id`**: `aad_object_id` first, `from_property.id` as fallback.
- Implement `MSTeamsSessionStore` with `get_or_create`, `clear`, `is_expired`,
  and JSON payload round-tripping through an injected store.
- Write unit tests for key precedence, expiry, and the serialization round trip.

**NOT in scope**: acquiring tokens or calling Navigator (TASK-4661); the
`/login` command (TASK-4662); touching `wrapper.py` or `models.py`
(TASK-4663); any Redis client code — the store is **injected**, and the default
is `InMemoryStateStore`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py` | CREATE | `MSTeamsUserSession`, `user_key`, `MSTeamsSessionStore` |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_session_store.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from botbuilder.core import TurnContext                      # installed
from parrot.integrations.core.state import InMemoryStateStore  # verified: packages/ai-parrot-integrations/src/parrot/integrations/core/state.py:14
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/core/state.py:14 — the store protocol to accept (duck-typed, do NOT subclass)
class InMemoryStateStore:
    async def set(self, key: str, value: str, expire: int = 0) -> None:  # line 42
    async def get(self, key: str) -> Optional[str]:                      # line 49
    async def delete(self, key: str) -> None:                            # line 56

# packages/ai-parrot-integrations/src/parrot/integrations/core/state.py:61 — the precedent for key construction
class IntegrationStateManager:
    def __init__(self, store: Any = None):                   # line 75
    def _make_key(self, integration: str, chat_id: str, user_id: str) -> str:  # line 85

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/jira_commands.py:116 — the precedence to mirror EXACTLY
def _get_user_id(turn_context: "TurnContext") -> str:

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py:44 — the field layout and slot treatment to mirror
@dataclass
class TelegramUserSession:
    nav_user_id: Optional[str] = None          # line 52
    nav_session_token: Optional[str] = None    # line 53
    authenticated: bool = False                # line 56
    tool_manager: Optional["ToolManager"] = field(default=None, repr=False, compare=False)   # line 85
    user_agent: Optional["AbstractBot"] = field(default=None, repr=False, compare=False)     # line 88
    post_login_ran: bool = field(default=False, repr=False, compare=False)                   # line 91
    def set_authenticated(self, nav_user_id, session_token, display_name=None, email=None, **extra_meta) -> None:  # line 121

# botbuilder.schema.ChannelAccount attributes: id, name, aad_object_id, role, properties
```

### Does NOT Exist
- ~~`MSTeamsUserSession`~~ — nothing by that name exists anywhere in `packages/`.
- ~~a Redis-backed session store for any integration~~ — `telegram/auth.py` has
  **zero** Redis references. Do not import `redis` here.
- ~~`InMemoryStateStore.expire` / `.ttl` / `.exists`~~ — the protocol is exactly
  `set` / `get` / `delete`.
- ~~`IntegrationStateManager.get_or_create`~~ — it has `set_suspended_state`,
  `get_suspended_session`, `clear_suspended_state` only. Do not call it; mirror
  its key-building style and accept its `store` instead.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_session_store.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/core/state.py#InMemoryStateStore",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/core/state.py#IntegrationStateManager",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/jira_commands.py#_get_user_id",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py#TelegramUserSession"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `aiohttp` only; `ruff` TID251 fails the task on `requests`/`httpx`.
- Google-style docstrings, strict type hints, 120 columns, `self.logger` — never
  `print` (`.claude/rules/codebase-conventions.md`).
- **Never log a token**, not even truncated. Redact to `<redacted len=N>`.
- The three isolation slots must never reach the payload. A test asserts it.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py:44-137` — field layout, slots, `set_authenticated`.
- `packages/ai-parrot-integrations/src/parrot/integrations/core/state.py:61-88` — the injected-store pattern and key building.

---

## Implementation Blueprint

### Steps (in order)
1. Write the dataclass with the serializable fields first, then the three slots
   with `repr=False, compare=False` — *why*: the slots hold live agent objects, so
   a default `repr` would dump tool internals into logs.
2. Add `user_key()` as a module-level function — *why*: TASK-4661 and TASK-4663
   both need it without constructing a store.
3. Add `_to_payload`/`_from_payload` as explicit field lists, not
   `asdict()` — *why*: `asdict()` would walk into the isolation slots and raise.
4. Derive the TTL from `external_expires_at` on every write — *why*: a
   hard-coded TTL is the logged defect of `AudioSessionStore`.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py` (CREATE)
```python
"""MS Teams per-user session and its store."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, TYPE_CHECKING

from botbuilder.core import TurnContext

from parrot.integrations.core.state import InMemoryStateStore

if TYPE_CHECKING:  # pragma: no cover
    from parrot.bots.abstract import AbstractBot
    from parrot.tools import ToolManager

logger = logging.getLogger(__name__)

_KEY_PREFIX = "msteams:session"


def user_key(turn_context: TurnContext) -> str:
    """Return the Entra ``oid`` when present, else the Teams-scoped id.

    Same precedence as ``_get_user_id``  # verified: jira_commands.py:116
    """
    frm = turn_context.activity.from_property
    return getattr(frm, "aad_object_id", None) or frm.id


@dataclass
class MSTeamsUserSession:
    """Cached identity for one Teams user of one agent."""

    user_key: str
    teams_user_id: str
    aad_object_id: Optional[str] = None
    tenant_id: Optional[str] = None
    display_name: Optional[str] = None
    # Populated after the Navigator token exchange:
    nav_user_id: Optional[str] = None
    nav_session_token: Optional[str] = None
    nav_email: Optional[str] = None
    authenticated: bool = False
    authenticated_at: Optional[datetime] = None
    # Drives re-acquisition; the Navigator session is capped to the external
    # token's remaining life (PoC observed cap=89).
    external_expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Process-local, never serialized — see telegram/auth.py:78 for the rationale.
    tool_manager: Optional["ToolManager"] = field(default=None, repr=False, compare=False)
    user_agent: Optional["AbstractBot"] = field(default=None, repr=False, compare=False)
    post_login_ran: bool = field(default=False, repr=False, compare=False)

    @property
    def user_id(self) -> str:
        """Navigator id when authenticated, else a Teams-scoped fallback."""
        if self.authenticated and self.nav_user_id:
            return self.nav_user_id
        return f"msteams:{self.user_key}"

    def set_authenticated(self, nav_user_id: str, session_token: str,
                          display_name: Optional[str] = None,
                          email: Optional[str] = None,
                          external_expires_at: Optional[datetime] = None,
                          **extra_meta: Any) -> None:
        """Mark the session authenticated with Navigator credentials."""
        # FILL IN: assign the fields and stamp authenticated_at (UTC-aware) —
        # bounded by AC-1; mirror telegram/auth.py:121 exactly
        raise NotImplementedError
```
**Why this shape**: the field split is the whole point of Q3 — everything above
the comment is serializable, the three below are not. `user_key` is a free
function because two later tasks need it without a store. Do not rename
`external_expires_at`: `is_expired` and the TTL both read it.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py` — store (same file, CREATE)
```python
class MSTeamsSessionStore:
    """Sessions for one agent's Teams users, over an injected state store."""

    def __init__(self, agent_name: str, store: Any = None, logger_: Any = None) -> None:
        self.agent_name = agent_name
        self._store = store if store is not None else InMemoryStateStore()
        self._local: Dict[str, MSTeamsUserSession] = {}
        self.logger = logger_ or logger

    def _key(self, key: str) -> str:
        """Namespaced key; mirrors IntegrationStateManager._make_key:85."""
        return f"{_KEY_PREFIX}:{self.agent_name}:{key}"

    @staticmethod
    def _ttl_for(session: MSTeamsUserSession) -> int:
        """Seconds until the external token dies; 0 when unknown."""
        # FILL IN: compute max(0, external_expires_at - now) in whole seconds,
        # returning 0 when external_expires_at is None — bounded by AC-4.
        # 0 means "no expiry" to InMemoryStateStore.set, so never return a
        # negative number.
        raise NotImplementedError

    def is_expired(self, session: MSTeamsUserSession) -> bool:
        """True when external_expires_at has passed."""
        # FILL IN: compare against timezone-aware utcnow — bounded by AC-3
        raise NotImplementedError

    async def get_or_create(self, turn_context: TurnContext) -> MSTeamsUserSession:
        """Return the live session, rehydrating from the store if needed."""
        # FILL IN: local cache first; else store.get(self._key(k)) and
        # _from_payload; else build a fresh session from the activity.
        # An expired rehydrated session is returned with authenticated=False,
        # not dropped — bounded by AC-2, AC-3.
        raise NotImplementedError

    async def save(self, session: MSTeamsUserSession) -> None:
        """Persist the serializable fields with a token-derived TTL."""
        # FILL IN: store.set(self._key(...), json.dumps(self._to_payload(...)),
        # expire=self._ttl_for(session)) — bounded by AC-4
        raise NotImplementedError

    async def clear(self, key: str) -> None:
        """Drop the session (logout); never raises on a missing key."""
        # FILL IN: pop the local entry and delete the stored one, swallowing
        # a missing-key error from the store — bounded by AC-5
        raise NotImplementedError

    @staticmethod
    def _to_payload(session: MSTeamsUserSession) -> Dict[str, Any]:
        """Serializable fields only — never the isolation slots."""
        # FILL IN: build the dict from an EXPLICIT field list. Do not use
        # dataclasses.asdict: it walks into tool_manager/user_agent and raises.
        # Datetimes go out as ISO-8601 strings — bounded by AC-6.
        raise NotImplementedError

    @classmethod
    def _from_payload(cls, payload: Dict[str, Any]) -> MSTeamsUserSession:
        """Inverse of _to_payload; tolerates a payload written by an older build."""
        # FILL IN: parse ISO-8601 back to aware datetimes; unknown keys ignored,
        # missing keys fall back to the dataclass defaults — bounded by AC-6
        raise NotImplementedError
```
**Why**: the store is injected and duck-typed so Redis arrives as configuration,
not as an import here — that is what keeps this task S/M instead of pulling a
client in. `_to_payload` is an explicit list precisely because `asdict()` cannot
work on this dataclass.

### FILL IN checklist
- [ ] `MSTeamsUserSession.set_authenticated` — field assignment + UTC stamp; bounded by AC-1
- [ ] `MSTeamsSessionStore._ttl_for` — clamp at 0, None ⇒ 0; bounded by AC-4
- [ ] `MSTeamsSessionStore.is_expired` — aware-datetime comparison; bounded by AC-3
- [ ] `MSTeamsSessionStore.get_or_create` — cache → store → fresh; bounded by AC-2
- [ ] `MSTeamsSessionStore.save` — TTL-carrying write; bounded by AC-4
- [ ] `MSTeamsSessionStore.clear` — idempotent delete; bounded by AC-5
- [ ] `MSTeamsSessionStore._to_payload` / `_from_payload` — explicit fields; bounded by AC-6

---

## Acceptance Criteria

- [ ] AC-1 `set_authenticated` populates `nav_user_id`, `nav_session_token`,
      `nav_email`, sets `authenticated=True` and stamps an aware `authenticated_at`
- [ ] AC-2 `get_or_create` returns the same object twice for one user, and
      rehydrates from the injected store when the local cache is cold
- [ ] AC-3 `is_expired` follows `external_expires_at`, not session age; an
      expired rehydrated session comes back with `authenticated=False`
- [ ] AC-4 `save` passes a TTL derived from `external_expires_at`; no literal
      TTL constant appears in the module
- [ ] AC-5 `clear` on an unknown key does not raise
- [ ] AC-6 the payload round-trips and contains **none** of `tool_manager`,
      `user_agent`, `post_login_ran`
- [ ] `ruff check` clean; no `redis`, `requests` or `httpx` import
- [ ] `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_session_store.py -q` passes

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_session_store.py -q`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_session_store.py
import pytest
from datetime import datetime, timedelta, timezone

from parrot.integrations.msteams.auth import (
    MSTeamsSessionStore, MSTeamsUserSession, user_key,
)

TEAMS_OID = "7c8f1d2e-3b4a-5c6d-7e8f-9a0b1c2d3e4f"


class TestUserKey:
    def test_prefers_aad_object_id(self, teams_activity):
        """user_key returns the Entra oid when present."""
        # FILL IN: assert user_key(ctx) == TEAMS_OID

    def test_falls_back_to_from_id(self):
        """With aad_object_id None, the Teams-scoped id is used."""
        # FILL IN


class TestSessionStore:
    async def test_payload_excludes_isolation_slots(self):
        """The three live-object slots never serialize."""
        # FILL IN: assert set(payload) & {"tool_manager", "user_agent", "post_login_ran"} == set()

    async def test_expiry_follows_external_token(self):
        """is_expired reads external_expires_at, not session age."""
        # FILL IN

    async def test_clear_missing_key_is_quiet(self):
        """clear() on an unknown key does not raise."""
        # FILL IN
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug msteams-user-auth-lane --feature-id FEAT-729`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/msteams-user-auth-lane.json`
4. **Verify the Codebase Contract** before writing ANY code. Re-grep every
   anchor: this task was written on `dev @ 0eb59926a` and the spec's §6 was
   verified on `37dc1da44`, so two anchors had already drifted once (see
   Context where noted). If anything moved, fix the contract FIRST.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`)
   and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every
   `# FILL IN:` marker, never change a signature or path it fixes
7. **Verify** the Acceptance Criteria — run the Validation Commands with
   `PYTHONPATH` set per changed package (the shared `.venv` is editable-installed
   against the MAIN checkout, so a bare `pytest` in a worktree imports the wrong
   branch)
8. **Commit the code** — stage only the files this task lists (never `git add .`)
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4659 msteams-user-auth-lane verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

> Filled in by the implementing agent when the task is closed.

**Completed**:
**Deviations from scope**:
**Ambiguities found in the spec**:
**Follow-up needed**:
