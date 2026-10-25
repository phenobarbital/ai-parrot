# TASK-4683: Tenant and bearer resolution (M2)

**Feature**: FEAT-734 — Serve FormDesigner forms from a Teams agent
**Spec**: `sdd/specs/formdesigner-serve-forms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 2**: pure resolution of *which FormDesigner tenant* and *whose
bearer* a Teams turn uses. No Bot Framework, no HTTP — plain data in, plain data
out — so the precedence rules are unit-testable in isolation. It also defines
the three Protocols later tasks consume: `UserSessionLike`,
`TeamsSessionStoreLike` (FEAT-729's session/store, consumed structurally) and
`LocalFormAuthorizer` (the NEW host membership adapter for local mode).

Leaf task, wave 1.

---

## Scope

- Create `formdesigner_identity.py` with `TenantUnresolved`, `TenantResolution`,
  `UserSessionLike`, `TeamsSessionStoreLike`, `LocalFormAuthorizer`,
  `resolve_form_tenant()` and `resolve_bearer()`.
- Precedence is EXACTLY: mapped activity AAD GUID → mapped session AAD GUID →
  config slug. Both GUID tiers go through `tenant_map`; an unmapped GUID is never
  returned. No tier → raise `TenantUnresolved`.
- Write `tests/msteams/test_formdesigner_identity.py` with the seven M2 tests of spec §4.

**NOT in scope**: reading the session store (the mixin does it, TASK-4691), any
import of `auth.py` (forbidden here — see Does NOT Exist), FEAT-733's
`resolve_submit_tenant` (not merged; this module is independent of it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_identity.py` | CREATE | Protocols, TenantResolution, resolve_form_tenant, resolve_bearer |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_identity.py` | CREATE | M2 unit tests |


---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from typing import TYPE_CHECKING, Literal, Protocol
from pydantic import BaseModel
# TYPE_CHECKING only:
from botbuilder.core import TurnContext       # used the same way across msteams/ (e.g. handler.py)
```

### Existing Signatures to Use (consumed STRUCTURALLY — never imported here)
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py  (FEAT-729, landed)
@dataclass
class MSTeamsUserSession:                                  # line 45
    tenant_id: Optional[str] = None                        # line 51 — AAD GUID, NOT a FormDesigner slug
    nav_user_id: Optional[str] = None                      # line 53
    nav_session_token: Optional[str] = None                # line 54 — the bearer
    authenticated: bool = False                            # line 56

class MSTeamsSessionStore:                                 # line 102
    def is_expired(self, session: MSTeamsUserSession) -> bool: ...                    # line 130
    async def get_or_create(self, turn_context: TurnContext) -> MSTeamsUserSession: ...  # line 134
    #   read-only; never exchanges; fills tenant_id from channel_data["tenant"]["id"] (lines 159-164)

class MSTeamsAuthStrategy:                                 # line 256
    async def ensure_authenticated(self, turn_context) -> MSTeamsUserSession: ...      # line 301 — may SEND a sign-in card
```

### Does NOT Exist
- ~~`UserSessionLike`~~, ~~`TeamsSessionStoreLike`~~, ~~`LocalFormAuthorizer`~~, ~~`TenantUnresolved`~~ — this task defines them (0 hits today).
- ~~`TeamsIdentityProvider`~~, ~~`current_session()`~~ — an earlier draft's invention; never reintroduce.
- ~~A FormDesigner tenant slug on the session~~ — `MSTeamsUserSession.tenant_id` is an AAD GUID; `metadata` holds no slug.
- ~~`resolve_submit_tenant()`~~, ~~`MSTeamsAgentConfig.formdesigner_tenant_map`~~ — FEAT-733, not merged on `dev`; this module takes the map as a plain `dict` argument.
- Do NOT `import` anything from `.auth` in this module (spec §6: only wiring and tests may name the concrete classes).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_identity.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/msteams/test_formdesigner_identity.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py#MSTeamsUserSession",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py#MSTeamsSessionStore",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py#MSTeamsAuthStrategy"
  ]
}
```

---

## Implementation Notes

- `TeamsSessionStoreLike` must list ONLY `get_or_create` and `is_expired` — the
  docstring records that `ensure_authenticated()` is forbidden (side effect: it
  may send a sign-in card, pre-empting the login card).
- Log nothing sensitive; this module has no logger beyond `logging.getLogger(__name__)` debug of the winning `source`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the Protocols and models — *why*: TASK-4690/4691 import them by name.
2. Write `resolve_form_tenant` as a straight three-tier ladder — *why*: the precedence is an AC; a ladder makes each tier testable.
3. Write `resolve_bearer` taking `expired` as a bool — *why*: keeps M2 free of any store dependency (spec M2 docstring).
4. Write the seven tests.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_identity.py` (CREATE)
```python
"""Tenant + bearer resolution for FormDesigner serving (FEAT-734 M2). Pure functions, no I/O."""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    from botbuilder.core import TurnContext


class TenantUnresolved(Exception):
    """No tier yielded a FormDesigner tenant slug — never guess one."""


class TenantResolution(BaseModel):
    """Which tenant won, and why — logged on every fetch."""

    tenant: str
    source: Literal["aad_map", "session_aad_map", "config"]


class UserSessionLike(Protocol):
    """The subset of FEAT-729's MSTeamsUserSession (auth.py:45) this feature consumes."""

    authenticated: bool
    nav_session_token: str | None
    nav_user_id: str | None
    tenant_id: str | None  # AAD GUID — NEVER a FormDesigner slug


class TeamsSessionStoreLike(Protocol):
    """The subset of MSTeamsSessionStore (auth.py:102) this feature may call.

    `get_or_create` is read-only and never exchanges (the `_effective_user_id`
    precedent, wrapper.py:345). NEVER call MSTeamsAuthStrategy.ensure_authenticated()
    (auth.py:301): it may send a sign-in card as a side effect.
    """

    async def get_or_create(self, turn_context: "TurnContext") -> UserSessionLike: ...

    def is_expired(self, session: UserSessionLike) -> bool: ...


class LocalFormAuthorizer(Protocol):
    """Host adapter to the embedded app's authoritative membership policy (NEW contract).

    Missing adapter, rejection or lookup failure all deny. Neither the AAD map nor
    client-supplied tenant metadata proves membership.
    """

    async def require_membership(self, *, tenant: str, bearer_token: str, user_id: str) -> None:
        """Return only for an authorized principal; otherwise raise PermissionError."""
        ...


def resolve_form_tenant(
    *,
    asserted_tenant_id: str | None,
    session_tenant_id: str | None,
    tenant_map: dict[str, str] | None,
    config_tenant: str | None,
) -> TenantResolution:
    """Precedence: mapped activity GUID > mapped session GUID > bot config slug.

    Raises:
        TenantUnresolved: when no tier yields a slug.
    """
    mapping = tenant_map or {}
    # FILL IN: tier 1 — asserted_tenant_id in mapping -> TenantResolution(tenant=mapping[...], source="aad_map")
    # FILL IN: tier 2 — session_tenant_id in mapping -> source="session_aad_map"
    #   (bounded by AC "unmapped AAD GUID never used as a slug": a GUID absent from the map is skipped, never returned)
    # FILL IN: tier 3 — non-empty config_tenant -> source="config"; else raise TenantUnresolved
    raise NotImplementedError


def resolve_bearer(session: UserSessionLike | None, *, expired: bool = False) -> str | None:
    """session.nav_session_token when authenticated and not expired, else None (-> login card)."""
    if session is None or expired or not getattr(session, "authenticated", False):
        return None
    token = getattr(session, "nav_session_token", None)
    return token or None
```
**Why this shape**: signatures are spec §3 M2's skeleton verbatim. Should tier 2 apply when tier 1's GUID was present but unmapped? Yes — fall through tier by tier; the session tier only adds coverage, never overrides a mapped activity GUID.

### `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_identity.py` (CREATE)
```python
"""FEAT-734 M2 — tenant precedence and bearer resolution."""
from types import SimpleNamespace

import pytest

from parrot.integrations.msteams.formdesigner_identity import (
    TenantUnresolved, resolve_bearer, resolve_form_tenant,
)

GUID_A = "11111111-2222-3333-4444-555555555555"
GUID_B = "99999999-8888-7777-6666-555555555555"


def _session(**kw):
    base = dict(authenticated=True, nav_session_token="nav-tok", nav_user_id="u1", tenant_id=GUID_A)
    return SimpleNamespace(**{**base, **kw})


def test_tenant_precedence_aad_map_wins(): ...           # FILL IN: activity GUID_A->"acme" beats session GUID_B->"other"
def test_tenant_precedence_session_guid_when_activity_absent(): ...  # FILL IN: source == "session_aad_map"
def test_tenant_precedence_unmapped_guid_never_leaks(): ...          # FILL IN: result.tenant == config, not a GUID
def test_tenant_precedence_config_last(): ...            # FILL IN: source == "config"
def test_tenant_unresolved_raises():
    with pytest.raises(TenantUnresolved):
        resolve_form_tenant(asserted_tenant_id=GUID_A, session_tenant_id=None, tenant_map={}, config_tenant=None)
def test_resolve_bearer_requires_authenticated():
    assert resolve_bearer(_session(authenticated=False)) is None
def test_resolve_bearer_rejects_expired():
    assert resolve_bearer(_session(), expired=True) is None
```

### FILL IN checklist
- [ ] `resolve_form_tenant` three tiers; bounded by spec §5 AC "Tenant precedence is exactly …"
- [ ] four precedence test bodies

---

## Acceptance Criteria

- [ ] Precedence exactly `aad_map > session_aad_map > config`; unmapped GUIDs never returned.
- [ ] No tier → `TenantUnresolved`.
- [ ] `resolve_bearer` returns `None` for unauthenticated, expired, or token-less sessions.
- [ ] The module imports nothing from `parrot.integrations.msteams.auth`.
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_identity.py -q`


---

## Test Specification

Seven tests in the blueprint, named after spec §4 M2 rows.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug formdesigner-serve-forms --feature-id FEAT-734`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/formdesigner-serve-forms.json`
4. **Verify the Codebase Contract** — confirm every import/signature before writing code; never use anything under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker, never change a fixed signature or path
7. **Verify** — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot-integrations/src:packages/ai-parrot/src:packages/parrot-formdesigner/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4683 formdesigner-serve-forms verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any


### Completion Note
Implemented by the sdd-coder pool; merged to the feature branch, file-fidelity gate green, merge-tier validation green, review recorded (0 corrections).
