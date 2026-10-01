# TASK-3956: [W0.1] Request scope seam (M1)

**Feature**: FEAT-605 — Agent Studio — Tenant Scope, Owner-Controlled Visibility & Host Mount
**Spec**: `sdd/specs/agentstudio-tenant-visibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Spec task label**: W0.1 (spec §3 "Task plan") — **early subset** (§3 "Early subset and release gate"; no sibling-spec dependency)

---

## Context

Spec §2 "Scope seam" and Module 1. Agent Studio and UI surfaces (FEAT-535) must share ONE neutral
scope type and resolver lookup. Today the seam lives in `handlers/ui_surfaces_scope.py`
(`SurfaceScope`, `SessionSurfaceScopeResolver`, `get_scope_resolver`, `scope_grants`) and only knows
`app["ui_surfaces_scope_resolver"]`. This task creates `parrot.handlers.scope` with `RequestScope`
(adds the host flags `may_author`, `may_administer`, `studio_enabled`), the `ScopeResolver`
Protocol, the default `SessionScopeResolver` (moved verbatim), `has_installed_resolver`, the key
precedence `scope_resolver` → `ui_surfaces_scope_resolver` → default, and a pure
`scope_grants(*, tenant, visibility, allowed_groups, scope)` primitive. FEAT-535 names become
aliases/adapters so every UI-surfaces test passes unchanged (AC1, AC2).

Unblocks: **U-FS** — the FieldSync resolver can set the three new flags (package X9).

---

## Scope

- Create `parrot/handlers/scope.py` with `SCOPE_RESOLVER_APP_KEY`, `LEGACY_SCOPE_RESOLVER_APP_KEY`,
  `VISIBILITY_LEVELS`, `VisibilityLevel`, frozen `RequestScope` (field order and the first four
  defaults mirror `SurfaceScope`), `EMPTY_SCOPE`, `ScopeResolver` Protocol, `SessionScopeResolver`
  (moved verbatim from `SessionSurfaceScopeResolver`, incl. "tenant only when `programs` has exactly
  one entry, never `programs[0]`"), `has_installed_resolver(app)`, `get_scope_resolver(app)`,
  `normalize_visibility(value)`, pure `scope_grants(*, tenant, visibility, allowed_groups, scope)`.
- Turn `ui_surfaces_scope.py` into a compatibility layer: `SurfaceScope = RequestScope`,
  `SurfaceScopeResolver = ScopeResolver`, `SessionSurfaceScopeResolver = SessionScopeResolver`,
  `EMPTY_SCOPE` re-exported (and `SurfaceScope.EMPTY` still works), `get_scope_resolver` re-exported,
  and `scope_grants(record, scope)` kept with its exact signature as an adapter over the primitive.
- Write `test_scope_grants_matrix`, `test_legacy_aliases_identity`, `test_resolver_key_precedence`.

**NOT in scope**: Studio code of any kind (`StudioBaseView._scope()` is TASK-3959); the tenant-bound owner rule back-port to FEAT-535 `_LIST_VISIBLE_SQL` (spec §8 Q8, separate follow-up); changing `ui_surfaces.py` / `a2ui.py` imports (they keep importing from `ui_surfaces_scope`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/scope.py` | CREATE | Neutral scope seam: `RequestScope`, resolver Protocol + default, key lookup, primitive `scope_grants` |
| `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces_scope.py` | MODIFY | FEAT-535 names become aliases; `scope_grants(record, scope)` becomes an adapter |
| `packages/ai-parrot-server/tests/handlers/test_request_scope.py` | CREATE | Unit tests: grants matrix (incl. `may_administer`), alias identity, resolver key precedence |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified for this task at `32b1a45d4`, `dev`). The implementing agent MUST use these
> exact imports, class names, and method signatures. **DO NOT** invent, guess, or assume any
> import, attribute, or method not listed here. If you need something not listed, VERIFY it
> exists first with `grep` or `read`. Paths are relative to the repo root unless a line says
> otherwise; `S/` = `packages/ai-parrot-server/src/parrot/handlers/`.

### Verified Imports
```python
from navigator_auth.conf import AUTH_SESSION_OBJECT  # verified: S/ui_surfaces_scope.py:24
from navigator_session import get_session  # verified: S/ui_surfaces_scope.py:25
from parrot.auth.session_identity import resolve_user_id  # verified: S/ui_surfaces_scope.py:26
from parrot.handlers.models.ui_surfaces import SurfaceVisibility, UISurfaceRecord  # verified: S/ui_surfaces_scope.py:27
# tests (precedent: packages/ai-parrot-server/tests/handlers/test_ui_surfaces_scope.py:17-18)
from aiohttp.test_utils import make_mocked_request
from navigator_session.data import SessionData
```

### Existing Signatures to Use
```python
# S/ui_surfaces_scope.py
@dataclass(frozen=True)
class SurfaceScope:                       # :42 — user_id, tenant, groups, is_superuser=False (fields :58-61)
EMPTY_SCOPE = SurfaceScope(user_id=None, tenant=None, groups=frozenset(), is_superuser=False)  # :67
SurfaceScope.EMPTY = EMPTY_SCOPE          # :70 (attribute alias kept by FEAT-535 tests)
class SurfaceScopeResolver(Protocol):     # :73 ; async def resolve(self, request) -> SurfaceScope  :81
class SessionSurfaceScopeResolver:        # :86 ; resolve :103 ; tenant = programs_list[0] if len(programs_list) == 1 else None  :144
def get_scope_resolver(app: Any) -> SurfaceScopeResolver:   # :149 ; app.get("ui_surfaces_scope_resolver") :162
_DEFAULT_RESOLVER = SessionSurfaceScopeResolver()           # :168
def scope_grants(record: UISurfaceRecord, scope: SurfaceScope) -> bool:  # :171 (record.visibility is a SurfaceVisibility enum)
__all__ = ["EMPTY_SCOPE", "SessionSurfaceScopeResolver", "SurfaceScope", "SurfaceScopeResolver",
           "get_scope_resolver", "scope_grants"]            # :31-38
# consumers that must keep working unchanged:
#   S/ui_surfaces.py:39-42  from parrot.handlers.ui_surfaces_scope import SurfaceScope, get_scope_resolver, scope_grants
#   S/a2ui.py:57            from parrot.handlers.ui_surfaces_scope import get_scope_resolver
```

### Does NOT Exist
- ~~`parrot.handlers.scope`~~, ~~`RequestScope`~~, ~~`ScopeResolver`~~, ~~`SessionScopeResolver`~~, ~~`has_installed_resolver`~~, ~~`normalize_visibility`~~ — created by THIS task
- ~~`RequestScope.may_administer`~~, ~~`RequestScope.studio_enabled`~~, ~~`RequestScope.may_author`~~ — created here
- ~~`app["scope_resolver"]`~~ — no code reads it today (only `ui_surfaces_scope_resolver`, `ui_surfaces_scope.py:162`)
- ~~`handlers/crew/_tenancy.resolve_session_tenant` as a reusable resolver~~ — falls back to `programs[0]`; never reuse it

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/scope.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/ui_surfaces_scope.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/handlers/test_request_scope.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/ui_surfaces_scope.py#SurfaceScope",
    "sym:packages/ai-parrot-server/src/parrot/handlers/ui_surfaces_scope.py#SessionSurfaceScopeResolver",
    "sym:packages/ai-parrot-server/src/parrot/handlers/ui_surfaces_scope.py#get_scope_resolver",
    "sym:packages/ai-parrot-server/src/parrot/handlers/ui_surfaces_scope.py#scope_grants"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
FEAT-535's `ui_surfaces_scope.py` is the template (same discipline: type-check every value read from
the session Mapping, fail closed to an empty scope on any session error). Move the resolver body
verbatim; do not "improve" it.

### Key Constraints
- `RequestScope` field order: `user_id, tenant, groups, is_superuser=False, may_author=True, may_administer=False, studio_enabled=True` — so `SurfaceScope(user_id=…, tenant=…, groups=…, is_superuser=…)` keeps working (spec §2 "Scope seam").
- `get_scope_resolver` must tolerate a plain `dict` app (FEAT-535 tests pass one) — keep the `AttributeError` guard.
- `has_installed_resolver(app)` := either key present and non-None. This is the package-wide definition of "opted-in host" (X9).
- `scope_grants` primitive is pure and ignores ownership: False when either tenant is None or they differ; else True when `scope.is_superuser or scope.may_administer`, `visibility == "tenant"`, or (`visibility == "groups"` and groups intersect).
- No module in `ai-parrot` core may import this module (server package only).
- New functions: cyclomatic complexity ≤ 10, ≤ 60 lines (AC22).

### Cross-feature ordering (package X16)
- Cross-feature ordering: none required — this task is in the spec's early subset (X16 "No sibling dependency"); it may merge before any FEAT-621 (storage) or FEAT-622 (toolkits) task.
- FEAT-598 (`a2ui-linked-surfaces`) also touches `ui_surfaces`: keep every re-export in `ui_surfaces_scope.py` (spec "Cross-feature dependencies").
- External consumer: the FieldSync mount spec installs `app["scope_resolver"]` against this API.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces_scope.py` — code being moved/aliased
- `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_scope.py` — must pass UNCHANGED (AC1)

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Create `scope.py` with the block below; move `SessionSurfaceScopeResolver.resolve`'s body verbatim into `SessionScopeResolver.resolve` (only the return type name changes) — *why*: one resolver, two names; behaviour must be byte-identical for FEAT-535.
2. Replace the definitions in `ui_surfaces_scope.py` with aliases/re-exports, keep `__all__` names — *why*: `ui_surfaces.py` and `a2ui.py` import from there and must not change (Integration Points table).
3. Re-implement `ui_surfaces_scope.scope_grants(record, scope)` as an adapter that converts the `SurfaceVisibility` enum to its string value — *why*: keep the FEAT-535 truth table exactly (`may_administer` defaults False, so surfaces are unaffected).
4. Write the new tests; then run the unchanged FEAT-535 suite.

### `packages/ai-parrot-server/src/parrot/handlers/scope.py` (CREATE)
```python
"""Neutral request scope seam shared by UI surfaces and Agent Studio (FEAT-605 M1)."""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from aiohttp import web
from navigator_auth.conf import AUTH_SESSION_OBJECT  # verified: ui_surfaces_scope.py:24
from navigator_session import get_session  # verified: ui_surfaces_scope.py:25
from parrot.auth.session_identity import resolve_user_id  # verified: ui_surfaces_scope.py:26

logger = logging.getLogger(__name__)

SCOPE_RESOLVER_APP_KEY = "scope_resolver"
LEGACY_SCOPE_RESOLVER_APP_KEY = "ui_surfaces_scope_resolver"  # verified: ui_surfaces_scope.py:162
VISIBILITY_LEVELS: frozenset[str] = frozenset({"private", "tenant", "groups"})
VisibilityLevel = Literal["private", "tenant", "groups"]


@dataclass(frozen=True)
class RequestScope:
    """Caller identity + host-computed gates for one request (spec §2 "Scope seam")."""

    user_id: str | None
    tenant: str | None
    groups: frozenset[str]
    is_superuser: bool = False
    may_author: bool = True
    may_administer: bool = False
    studio_enabled: bool = True


EMPTY_SCOPE = RequestScope(user_id=None, tenant=None, groups=frozenset(), is_superuser=False)
RequestScope.EMPTY = EMPTY_SCOPE  # type: ignore[attr-defined]  # FEAT-535 `SurfaceScope.EMPTY`


class ScopeResolver(Protocol):
    """Host-pluggable resolver installed at ``app["scope_resolver"]``."""

    async def resolve(self, request: web.Request) -> RequestScope:
        """Resolve the caller's scope for this request."""
        ...


class SessionScopeResolver:
    """Default resolver — moved verbatim from ``SessionSurfaceScopeResolver``."""

    async def resolve(self, request: web.Request) -> RequestScope:
        """See ``SessionSurfaceScopeResolver.resolve`` (ui_surfaces_scope.py:103-146)."""
        # FILL IN: paste the body of ui_surfaces_scope.py:103-146 verbatim, building RequestScope
        # instead of SurfaceScope — bounded by AC1 (FEAT-535 tests unchanged); never programs[0].
        raise NotImplementedError


_DEFAULT_RESOLVER = SessionScopeResolver()


def _app_get(app: Any, key: str) -> Any:
    try:
        return app.get(key)
    except AttributeError:
        return None


def has_installed_resolver(app: Any) -> bool:
    """True when the host installed a resolver under either key (package X9 "opted-in host")."""
    return _app_get(app, SCOPE_RESOLVER_APP_KEY) is not None or _app_get(app, LEGACY_SCOPE_RESOLVER_APP_KEY) is not None


def get_scope_resolver(app: Any) -> ScopeResolver:
    """``app["scope_resolver"]`` → ``app["ui_surfaces_scope_resolver"]`` → module default."""
    return _app_get(app, SCOPE_RESOLVER_APP_KEY) or _app_get(app, LEGACY_SCOPE_RESOLVER_APP_KEY) or _DEFAULT_RESOLVER


def normalize_visibility(value: Any) -> str:
    """Return ``value`` (str or enum with ``.value``) as one of VISIBILITY_LEVELS; else ``"private"``."""
    # FILL IN: accept SurfaceVisibility-like enums via getattr(value, "value", value); unknown ⇒ "private"
    #   — bounded by "fail closed" (spec §7 "Type-check what is read from a Mapping").
    raise NotImplementedError


def scope_grants(*, tenant: str | None, visibility: str, allowed_groups: Iterable[str], scope: RequestScope) -> bool:
    """Pure grant rule, ignores ownership (spec §3 M1 skeleton)."""
    if scope.tenant is None or tenant is None or tenant != scope.tenant:
        return False
    if scope.is_superuser or scope.may_administer:
        return True
    level = normalize_visibility(visibility)
    if level == "tenant":
        return True
    if level == "groups":
        return bool(scope.groups & set(allowed_groups))
    return False
```
**Why**: Signatures and names are frozen by spec §3 Module 1 and package X9 (FieldSync codes against them). `has_installed_resolver` is THE opted-in test used by every later task.

### `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces_scope.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class SurfaceScope:' ui_surfaces_scope.py) — :42
# REPLACE the SurfaceScope dataclass (:41-61), EMPTY_SCOPE (:67-70), SurfaceScopeResolver (:73-83),
# SessionSurfaceScopeResolver (:86-146), get_scope_resolver (:149-165) and _DEFAULT_RESOLVER (:168) with:
from parrot.handlers.scope import (  # noqa: E402
    EMPTY_SCOPE,
    RequestScope,
    ScopeResolver,
    SessionScopeResolver,
    get_scope_resolver,
)
from parrot.handlers.scope import scope_grants as _scope_grants

SurfaceScope = RequestScope
SurfaceScopeResolver = ScopeResolver
SessionSurfaceScopeResolver = SessionScopeResolver

# occurrences: 1 (verified: grep -c 'def scope_grants(record: UISurfaceRecord, scope: SurfaceScope) -> bool:') — :171
def scope_grants(record: UISurfaceRecord, scope: SurfaceScope) -> bool:
    """FEAT-535 adapter over :func:`parrot.handlers.scope.scope_grants` (signature unchanged)."""
    return _scope_grants(
        tenant=record.tenant,
        visibility=getattr(record.visibility, "value", record.visibility),
        allowed_groups=record.allowed_groups,
        scope=scope,
    )
```
**Why**: Keeps every FEAT-535 import site working (AC1). Drop the now-unused imports (`get_session`, `AUTH_SESSION_OBJECT`, `resolve_user_id`, `dataclass`, `Protocol`) only if ruff reports them unused; keep `SurfaceVisibility` if still referenced.

### `packages/ai-parrot-server/tests/handlers/test_request_scope.py` (CREATE)
```python
"""FEAT-605 M1 — RequestScope seam (spec §4 unit tests)."""
from __future__ import annotations

import pytest
from parrot.handlers import ui_surfaces_scope as legacy
from parrot.handlers.scope import (
    EMPTY_SCOPE, RequestScope, SessionScopeResolver, get_scope_resolver,
    has_installed_resolver, scope_grants,
)


class _Resolver:
    def __init__(self, tag: str) -> None:
        self.tag = tag

    async def resolve(self, request):  # real ScopeResolver implementation, not a Mock
        return RequestScope(user_id=self.tag, tenant=None, groups=frozenset())


def test_legacy_aliases_identity():
    assert legacy.SurfaceScope is RequestScope
    assert legacy.SessionSurfaceScopeResolver is SessionScopeResolver
    old = legacy.SurfaceScope(user_id="u", tenant="t", groups=frozenset(), is_superuser=True)
    assert (old.may_author, old.may_administer, old.studio_enabled) == (True, False, True)
    assert legacy.EMPTY_SCOPE is EMPTY_SCOPE and legacy.SurfaceScope.EMPTY is EMPTY_SCOPE


def test_resolver_key_precedence():
    new, old = _Resolver("new"), _Resolver("old")
    assert get_scope_resolver({"scope_resolver": new, "ui_surfaces_scope_resolver": old}) is new
    assert get_scope_resolver({"ui_surfaces_scope_resolver": old}) is old
    assert isinstance(get_scope_resolver({}), SessionScopeResolver)
    assert has_installed_resolver({"ui_surfaces_scope_resolver": old}) and not has_installed_resolver({})


@pytest.mark.parametrize("case", [...])  # FILL IN
def test_scope_grants_matrix(case):
    # FILL IN: tenant None / mismatch / match × private/tenant/groups × is_superuser × may_administer
    #   (spec §4 unit row). Mutation: drop `or scope.may_administer` ⇒ an admin row goes RED.
    ...
```
**Why**: Names are the spec §4 unit-test names (mutation table references them).

### FILL IN checklist
- [ ] `scope.py::SessionScopeResolver.resolve` — verbatim move of `ui_surfaces_scope.py:103-146`; bounded by AC1
- [ ] `scope.py::normalize_visibility` — enum/str handling, unknown ⇒ `"private"`; bounded by fail-closed rule
- [ ] `test_request_scope.py::test_scope_grants_matrix` — full matrix incl. `may_administer`; bounded by spec §4

---

## Acceptance Criteria

- [ ] AC1: `parrot.handlers.scope` exists; `ui_surfaces_scope` names are aliases; `tests/handlers/test_ui_surfaces_scope.py` passes **unchanged**
- [ ] AC2: resolver lookup prefers `app["scope_resolver"]`, falls back to `app["ui_surfaces_scope_resolver"]`, then the default
- [ ] `RequestScope` built FEAT-535-style gets `may_author=True, may_administer=False, studio_enabled=True`
- [ ] Mutation: drop `scope.may_administer` from the primitive ⇒ `test_scope_grants_matrix` RED; return `_DEFAULT_RESOLVER` before checking `scope_resolver` ⇒ `test_resolver_key_precedence` RED
- [ ] `ruff check` clean on the two source files; new functions ≤ 10 complexity, ≤ 60 lines (AC22)

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/handlers/test_request_scope.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_ui_surfaces_scope.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_ui_surfaces_handler.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass. Rule 6 / spec §4: requests are
> built with `aiohttp_client` or `make_mocked_request` plus a real
> `navigator_session.data.SessionData` at `request[SESSION_OBJECT]`; never patch
> `_get_user`, `_resolve_session` or `_scope` (they are the join under test).

```python
# packages/ai-parrot-server/tests/handlers/test_request_scope.py — see blueprint block; required names:
def test_scope_grants_matrix(): ...          # tenant None/mismatch/match × levels × superuser × may_administer
def test_legacy_aliases_identity(): ...      # SurfaceScope is RequestScope; old construction; flag defaults
def test_resolver_key_precedence(): ...      # scope_resolver > ui_surfaces_scope_resolver > default; has_installed_resolver
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-tenant-visibility --feature-id FEAT-605`)
2. **Read the spec** at the path listed above for full context (§2 is normative; §3 has the task table)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/agentstudio-tenant-visibility.json`, AND every
   "Cross-feature ordering" item in Implementation Notes must hold (sibling feature tasks merged)
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - Re-run each blueprint `grep -c` anchor; a count of `0` means drift — stop and report
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/agentstudio-tenant-visibility.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands, and run each
   listed mutation check (revert the guard, see the named test go RED, restore by re-applying
   the edit — never with `git checkout` of the file)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3956 agentstudio-tenant-visibility verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
