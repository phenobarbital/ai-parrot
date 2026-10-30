# TASK-4937: Principal model and PrincipalResolver Protocol

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Principal" and §3 Module 1. Every connection, cache key and durable row becomes keyed by the
Navigator principal (`auth.users.user_id`, U1) instead of `(channel, user_id)`. This task creates the core
`Principal` model plus a `PrincipalResolver` Protocol with a module-level registration point, mirroring
`set_vault_credential_store` (vault_utils.py:46): core defines the seam, the server registers
`IdentityPrincipalResolver` at startup (TASK-4952 / TASK-4957). Resolution failure means **no principal** and
the caller fails closed — never a channel-keyed fallback.

---

## Scope

- Create `parrot/auth/principal.py` with `Principal` (Pydantic v2), `PrincipalResolver` (Protocol),
  `WebPrincipalResolver` (default: `channel == "web"` → the id IS the Navigator id; every other channel → `None`),
  `set_principal_resolver`, `get_principal_resolver` (defaults to `WebPrincipalResolver`), `resolve_principal`.
- Export `Principal`, `PrincipalResolver`, `set_principal_resolver`, `resolve_principal` through the lazy
  `_LAZY_ATTRS` map and `__all__` of `parrot/auth/__init__.py`.
- Unit tests `test_principal_resolver_default_web_only`, `test_resolve_principal_fail_closed`.

**NOT in scope**: the server resolver over `auth.user_identities` (TASK-4952); any use of the principal in managers (TASK-4940).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/principal.py` | CREATE | Principal, PrincipalResolver, default resolver, registration |
| `packages/ai-parrot/src/parrot/auth/__init__.py` | MODIFY | lazy exports |
| `packages/ai-parrot/tests/unit/auth/test_principal.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from pydantic import BaseModel, Field                 # pydantic v2 (core dep)
from typing import Optional, Protocol, runtime_checkable
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/security/vault_utils.py:46 — the pattern to mirror
_PG_VAULT_STORE: Any = None
def set_vault_credential_store(store: Any) -> None:
    global _PG_VAULT_STORE
    _PG_VAULT_STORE = store

# packages/ai-parrot/src/parrot/auth/__init__.py:30 — lazy map (dict[str, str] name -> module)
_LAZY_ATTRS: dict[str, str] = {
    ...
    "CredentialResolver": "parrot.auth.credentials",      # line 52 (anchor)
    ...
}
__all__ = [ ... ]                                         # follows the map

# packages/ai-parrot-server/src/parrot/handlers/integrations.py:43 — web user id today
#   IntegrationsHandler._get_user_id(): the web session user_id IS the Navigator id
```

### Does NOT Exist
- ~~`parrot.auth.principal`~~ — created by this task.
- ~~`PermissionContext.principal_id` / `PermissionContext.nav_user_id`~~ — only `user_id` (permission.py:81-126).
- ~~`CanonicalIdentityMapper` → Navigator id~~ — it returns OID/e-mail only (identity.py:75).
- ~~`parrot.connections`~~, ~~`ConnectionManager`~~ — brainstorm names, never implemented.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/principal.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/auth/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/auth/test_principal.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- `user_id` is the Navigator bigint serialized as `str`. Keep `channel_user_id` required: notifier adapters
  and legacy-key migration need the raw channel id.
- The resolver registry is a module global (like `_PG_VAULT_STORE`) — tests must restore it; provide a fixture.
- Valid `channel` values include `cli` and `a2a` (S-4 seam); do not validate against a closed list.

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Write `principal.py` from the block below — *why*: fixes the §2 data model every later task imports.
2. Add the four lazy exports after the anchor in `auth/__init__.py` and to `__all__` — *why*: `from parrot.auth import Principal` must work without eager imports (the package is lazy by design).
3. Write the tests — *why*: AC for fail-closed resolution (spec §4 M1 rows).

### `packages/ai-parrot/src/parrot/auth/principal.py` (CREATE)
```python
"""Platform principal for delegated connections (FEAT-773, spec §2).

A connection belongs to the Navigator user (``auth.users.user_id``), never to a
``(channel, channel_user_id)`` pair. Core defines the resolver seam; the server
registers an implementation over ``auth.user_identities`` at startup.
"""
from __future__ import annotations

import logging
from typing import Optional, Protocol, runtime_checkable

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class Principal(BaseModel):
    """The platform identity a connection belongs to (U1).

    Attributes:
        user_id: Navigator ``auth.users.user_id`` serialized as ``str``.
        canonical_identity: Entra OID or lower-cased e-mail, when known.
        tenant_id: Optional tenant.
        channel: Originating channel (web, telegram, slack, msteams, a2a, cli).
        channel_user_id: Raw id on that channel.
    """

    user_id: str
    canonical_identity: Optional[str] = None
    tenant_id: Optional[str] = None
    channel: str
    channel_user_id: str


@runtime_checkable
class PrincipalResolver(Protocol):
    """Maps ``(channel, channel_user_id)`` to a :class:`Principal`."""

    async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]:
        """Return the bound principal, or ``None`` (the caller fails closed)."""
        ...


class WebPrincipalResolver:
    """Default resolver: on ``web`` the id IS the Navigator id; other channels resolve to ``None``."""

    async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]:
        """Resolve web ids only."""
        # FILL IN: return Principal(user_id=channel_user_id, channel="web", channel_user_id=channel_user_id)
        #          for channel == "web" with a non-empty id; None otherwise — bounded by spec §3 M1 + test row 1
        raise NotImplementedError


_RESOLVER: Optional[PrincipalResolver] = None


def set_principal_resolver(resolver: Optional[PrincipalResolver]) -> None:
    """Register the process-wide resolver (server calls this at startup; ``None`` restores the default)."""
    global _RESOLVER  # pylint: disable=global-statement
    _RESOLVER = resolver


def get_principal_resolver() -> PrincipalResolver:
    """Return the registered resolver, or :class:`WebPrincipalResolver`."""
    return _RESOLVER if _RESOLVER is not None else WebPrincipalResolver()


async def resolve_principal(channel: str, channel_user_id: str) -> Optional[Principal]:
    """Resolve through the registered resolver; ``None`` means "no principal" — never fall back to channel keys."""
    # FILL IN: guard empty channel/channel_user_id (return None); call get_principal_resolver().resolve();
    #          log at debug when unresolved (never log tokens) — bounded by AC-2 (fail closed)
    raise NotImplementedError
```
**Why this shape**: matches the §2 data model and the §3 M1 skeleton verbatim. The setter takes `Optional`
so tests and shutdown can reset to the default; nothing else changes from the skeleton.

### `packages/ai-parrot/src/parrot/auth/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "CredentialResolver": "parrot.auth.credentials",' packages/ai-parrot/src/parrot/auth/__init__.py)
# AFTER — insert below `    "CredentialResolver": "parrot.auth.credentials",` (verified: auth/__init__.py:52)
    "Principal": "parrot.auth.principal",
    "PrincipalResolver": "parrot.auth.principal",
    "set_principal_resolver": "parrot.auth.principal",
    "resolve_principal": "parrot.auth.principal",
```
**Why**: the package resolves exports lazily through `_LAZY_ATTRS`; also append the same four names to `__all__`
(FILL IN: place them next to the existing credential exports).

### FILL IN checklist
- [ ] `principal.py::WebPrincipalResolver.resolve` — web passthrough only; bounded by spec §3 M1
- [ ] `principal.py::resolve_principal` — empty-input guard + delegation; bounded by AC-2 (fail closed)
- [ ] `auth/__init__.py::__all__` — add the four names
- [ ] `test_principal.py` — bodies for the tests below

---

## Acceptance Criteria

- [ ] `from parrot.auth import Principal, PrincipalResolver, set_principal_resolver, resolve_principal` works
- [ ] Default resolver binds `web` ids and returns `None` for telegram/slack/msteams/a2a/cli
- [ ] `resolve_principal` returns `None` (never raises, never falls back) when the registered resolver returns `None`
- [ ] `ruff check` clean on the touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/auth/test_principal.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/auth/test_principal.py
import pytest
from parrot.auth.principal import (Principal, WebPrincipalResolver, get_principal_resolver,
                                   resolve_principal, set_principal_resolver)


@pytest.fixture(autouse=True)
def _reset_resolver():
    set_principal_resolver(None)
    yield
    set_principal_resolver(None)


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["telegram", "slack", "msteams", "a2a", "cli"])
async def test_principal_resolver_default_web_only(channel):
    assert await WebPrincipalResolver().resolve(channel, "42") is None
    web = await WebPrincipalResolver().resolve("web", "1042")
    assert web == Principal(user_id="1042", channel="web", channel_user_id="1042")


@pytest.mark.asyncio
async def test_resolve_principal_fail_closed():
    class _Nope:
        async def resolve(self, channel, channel_user_id):
            return None
    set_principal_resolver(_Nope())
    assert await resolve_principal("web", "1042") is None   # registered resolver wins, no fallback
    assert await resolve_principal("", "") is None
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug delegated-auth-connections --feature-id FEAT-773`)
2. **Read the spec** (`sdd/specs/delegated-auth-connections.spec.md`) — at least §2, the module section named in Context, §5 and §7
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/delegated-auth-connections.json`
4. **Verify the Codebase Contract** before writing ANY code (re-grep each anchor; line numbers drift). If an entry is stale, fix the contract in this file first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH` set to every touched `packages/<dist>/src` (the shared `.venv` imports the main checkout otherwise)
8. **Commit the code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> delegated-auth-connections verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
