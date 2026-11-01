# TASK-5066: `msteams/connections.py` — Teams principal source, permission context, connect state

**Feature**: FEAT-775 — Connections on MS Teams
**Spec**: `sdd/specs/connections-msteams.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5061
**Assigned-to**: unassigned

---

## Context

Spec §2 "Principal (M1)", §3 Module 1, Data Models, AC-1. Creates `connections.py`, the Teams module later
tasks extend (TASK-5067 notifier, TASK-5068 cards). An authenticated Teams turn (FEAT-729 session with
`nav_user_id` and AAD oid, unexpired) yields a FEAT-773 `Principal(user_id=nav_user_id,
canonical_identity=aad_oid, tenant_id, channel="msteams", channel_user_id=aad_oid)`; anything else yields
`None` — fail closed, never an AAD-keyed fallback. Session reads never trigger an exchange (same rule as
`MSTeamsAgentWrapper._effective_user_id`, wrapper.py:350-368).

---

## Scope

- `TeamsConnectState(BaseModel)`: `conversation_reference: Dict[str, Any]`, `bot_app_id: str`.
- `MSTeamsPrincipalSource(store)`: `session_for_turn(turn_context)` (validated session or `None`) and
  `principal_for_turn(turn_context)`.
- `build_msteams_permission_context(session) -> PermissionContext`: `session.user_id = nav_user_id`,
  `channel="msteams"`, `channel_user_id = aad_object_id`, tenant from the session, roles empty.
- Tests: `test_principal_for_turn_authenticated`, `test_principal_for_turn_unauthenticated_or_expired_is_none`,
  `test_build_msteams_permission_context`.

**NOT in scope**: wrapper call sites (TASK-5071), notifier (TASK-5067), cards (TASK-5068).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/connections.py` | CREATE | state model, principal source, context builder |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_principal_source.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from botbuilder.core import TurnContext                                           # verified: commands/jira_commands.py:33
from parrot.auth.permission import build_principal_context, PermissionContext     # verified: auth/permission.py:166, :81
from parrot.auth.principal import Principal                                       # verified: auth/principal.py:18
from parrot.integrations.msteams.auth import MSTeamsSessionStore, MSTeamsUserSession   # verified: msteams/auth.py:102, :45
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py
@dataclass class MSTeamsUserSession:                                              # :45
    user_key: str; teams_user_id: str; aad_object_id: Optional[str] = None; tenant_id: Optional[str] = None
    display_name: Optional[str] = None; nav_user_id: Optional[str] = None; ...; authenticated: bool = False
    external_expires_at: Optional[datetime] = None; metadata: Dict[str, Any]
class MSTeamsSessionStore:                                                        # :102
    def is_expired(self, session) -> bool                                         # :130
    async def get_or_create(self, turn_context) -> MSTeamsUserSession             # :134 (reads/rehydrates; no exchange)

# packages/ai-parrot/src/parrot/auth/permission.py
def build_principal_context(principal: str, *, channel: str, tenant_id=None, roles=None) -> PermissionContext  # :166
@dataclass class PermissionContext: ... channel_user_id: Optional[str] = None     # added by TASK-5061

# packages/ai-parrot/src/parrot/auth/principal.py:18
class Principal(BaseModel): user_id: str; canonical_identity: Optional[str]; tenant_id: Optional[str]; channel: str; channel_user_id: str
```

### Does NOT Exist
- ~~`msteams/connections.py`~~ — created here.
- ~~`MSTeamsAuthStrategy.ensure_authenticated` from this module~~ — never call it (it may run an exchange).
- ~~a principal for an unauthenticated Teams user~~ — `None`, never `from_property.id` / AAD-keyed.
- ~~`MSTeamsUserSession.roles` / `.groups`~~ — no such fields; the context gets empty roles.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/connections.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_principal_source.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py#MSTeamsSessionStore",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py#MSTeamsUserSession",
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#build_principal_context",
    "sym:packages/ai-parrot/src/parrot/auth/principal.py#Principal"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Create the module from the block. 2. Fill the validation rule. 3. Tests.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/connections.py` (CREATE)
```python
"""Teams connections (FEAT-775): principal source, permission context, notifier and cards.

TASK-5066 owns the principal/context part; TASK-5067 appends the notifier, TASK-5068 the card builders.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from pydantic import BaseModel

from parrot.auth.permission import PermissionContext, build_principal_context
from parrot.auth.principal import Principal

from .auth import MSTeamsSessionStore, MSTeamsUserSession

if TYPE_CHECKING:  # pragma: no cover
    from botbuilder.core import TurnContext

logger = logging.getLogger(__name__)

MSTEAMS_CHANNEL = "msteams"


class TeamsConnectState(BaseModel):
    """What the Teams channel puts in ``IntegrationsService.start_connect(extra_state=...)``."""

    conversation_reference: Dict[str, Any]
    bot_app_id: str


class MSTeamsPrincipalSource:
    """Principal for the speaking Teams user, from the cached FEAT-729 session; never runs an exchange."""

    def __init__(self, store: Optional[MSTeamsSessionStore]) -> None:
        self._store = store

    async def session_for_turn(self, turn_context: "TurnContext") -> Optional[MSTeamsUserSession]:
        """Return the live authenticated session, or ``None``.

        Requires ``authenticated``, ``nav_user_id``, ``aad_object_id`` and an unexpired credential.
        """
        if self._store is None:
            return None
        session = await self._store.get_or_create(turn_context)
        # FILL IN: return session only when authenticated, nav_user_id and aad_object_id are nonempty and
        # not self._store.is_expired(session); else None — bounded by AC-1 / wrapper.py:365-367 rule
        ...

    async def principal_for_turn(self, turn_context: "TurnContext") -> Optional[Principal]:
        """Return the FEAT-773 principal for an authenticated turn, else ``None``."""
        session = await self.session_for_turn(turn_context)
        if session is None:
            return None
        return Principal(
            user_id=str(session.nav_user_id),
            canonical_identity=session.aad_object_id,
            tenant_id=session.tenant_id,
            channel=MSTEAMS_CHANNEL,
            channel_user_id=str(session.aad_object_id),
        )


def build_msteams_permission_context(session: MSTeamsUserSession) -> PermissionContext:
    """Build the Navigator PBAC context for a validated Teams session.

    ``session.user_id`` is the Navigator id (PBAC subject); ``channel_user_id`` is the AAD oid used only for
    OAuth credential lookup. Roles stay empty: Teams sessions carry no verified role claims.
    """
    context = build_principal_context(
        str(session.nav_user_id),
        channel=MSTEAMS_CHANNEL,
        tenant_id=session.tenant_id,
        roles=frozenset(),
    )
    context.channel_user_id = session.aad_object_id
    return context
```
**Why this shape**: `session_for_turn` is shared by `principal_for_turn` and the wrapper's context building
(TASK-5071), so the validation rule exists once.

### `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_principal_source.py` (CREATE)
```python
"""FEAT-775 M1: Teams principal source."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.msteams.auth import MSTeamsUserSession
from parrot.integrations.msteams.connections import MSTeamsPrincipalSource, build_msteams_permission_context


@pytest.fixture
def teams_session():
    return MSTeamsUserSession(user_key="aad-1", teams_user_id="29:x", aad_object_id="aad-1",
                              tenant_id="t-1", nav_user_id="42", authenticated=True)


def _store(session, expired=False):
    store = MagicMock()
    store.get_or_create = AsyncMock(return_value=session)
    store.is_expired = MagicMock(return_value=expired)
    return store


@pytest.mark.asyncio
async def test_principal_for_turn_authenticated(teams_session):
    # FILL IN: Principal(user_id="42", canonical_identity="aad-1", channel="msteams", channel_user_id="aad-1", tenant_id="t-1")
    ...


@pytest.mark.asyncio
async def test_principal_for_turn_unauthenticated_or_expired_is_none(teams_session):
    # FILL IN: store None / authenticated False / expired / nav_user_id None / aad_object_id None → None — bounded by AC-1
    ...


def test_build_msteams_permission_context(teams_session):
    # FILL IN: user_id "42", channel "msteams", channel_user_id "aad-1", roles empty
    ...
```

### FILL IN checklist
- [ ] validation rule in `session_for_turn`
- [ ] three tests

---

## Acceptance Criteria

- [ ] Authenticated session → principal per spec G1; any other state → `None` (AC-1).
- [ ] Context has Navigator id as subject and AAD oid only in `channel_user_id`.
- [ ] No call to `ensure_authenticated`; `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_principal_source.py -q`

---

## Test Specification

Three tests listed in the test-file block.

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

Implemented by gpt-5.6-luna (codex), 1 attempt, merged via sdd-worker; engine fidelity gate passed; merge-tier validation green (chunk 1). 0 review corrections.

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

