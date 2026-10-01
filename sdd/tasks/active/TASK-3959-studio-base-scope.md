# TASK-3959: [W1.1] Studio base scope — _scope(), tenant_mismatch, studio_disabled, authoring gate (M3)

**Feature**: FEAT-605 — Agent Studio — Tenant Scope, Owner-Controlled Visibility & Host Mount
**Spec**: `sdd/specs/agentstudio-tenant-visibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3956, TASK-3957
**Assigned-to**: unassigned
**Spec task label**: W1.1 (spec §3 "Task plan") — **early subset** (§3 "Early subset and release gate"; no sibling-spec dependency)

---

## Context

Spec §2 "Scope seam", "Host mount" (lazy scope), Module 3, C8, AC15. Every Studio view needs one
per-request `RequestScope` with a fixed check order — `tenant_mismatch` (prefixed mount, declared
≠ resolved tenant, incl. resolved `None`) then `studio_disabled` (except the `/me` view) — before
any record access, plus an authoring gate, one identical 404 body helper, one non-enumerating
`name_taken` 409 helper, and, in an opted-in host, `is_superuser`/`groups` taken from the scope so
`_require_owner` and the access rule can never disagree. This lands with no storage code
(`_access()` and `_studio_partition()` are TASK-3964).

---

## Scope

- `StudioUser` gains `tenant: str | None = None`, `may_author: bool = True`, `may_administer: bool = False`.
- `StudioBaseView` gains: `_STUDIO_ENABLED_EXEMPT: ClassVar[bool] = False`; `_opted_in()`;
  `async _scope()` (resolved lazily once per request via `get_scope_resolver(app).resolve(request)`,
  falsy tenant normalised to `None`, cached on the instance); `async _studio_gate()` raising
  403 `tenant_mismatch` when `match_info` has `tenant` ≠ `scope.tenant`, then 404 `studio_disabled`
  unless exempt; `_require_author()` (403 `authoring_denied` JSON response or `None`);
  `_not_found(kind, name)` (one body for invisible and absent); `_name_taken(slug)` (409
  `{"code": "name_taken", "message": "Name '<slug>' is not available."}`).
- Run `_studio_gate()` before every verb by overriding aiohttp `web.View._iter` (call it, then
  `super()._iter()`), only when opted in or when the route declares `{tenant}` — so plain hosts
  are untouched (G9) and a host seam whose prologue lives in its own `_iter` (FieldSync
  `ProgrammeScopedView._iter`, which calls `super()._iter()`) runs first.
- `_get_user()` in an opted-in host: `is_superuser`, `groups`, `tenant`, `may_author`,
  `may_administer` come from the scope; without a resolver the FEAT-467 session parsing is unchanged.
- Tests (routed, real `SessionData`): `test_tenant_mismatch_403`, `test_studio_disabled_404`,
  `test_identity_from_scope_when_opted_in`, `test_wrapper_prologue_runs_before_scope`.

**NOT in scope**: `StudioAccess`, `_access()`, `_studio_partition()` override, `StudioTenantRequired` (TASK-3964); applying `_require_author`/`_not_found`/`_name_taken` inside handlers (each handler task does that); `/me` (TASK-3960).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/_base.py` | MODIFY | Scope resolution + check order, `_studio_gate` via `_iter`, `_require_author`, `_not_found`, `_name_taken`, scope-sourced identity |
| `packages/ai-parrot-server/tests/studio/test_base_scope.py` | CREATE | Routed tests over a prefixed app with a real resolver and a real `SessionData` |

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
from aiohttp import web  # verified: S/studio/_base.py:19
from navigator.views import BaseView  # verified: S/studio/_base.py:20
from navigator_auth.conf import AUTH_SESSION_OBJECT  # verified: S/studio/_base.py:23 (inside try/except)
from parrot.handlers.scope import RequestScope, get_scope_resolver, has_installed_resolver  # TASK-3956
from .models import StudioError  # verified: S/studio/models.py:23 (handlers already import it, e.g. meta_agent.py:25)
# tests
from aiohttp.test_utils import make_mocked_request  # precedent tests/handlers/test_ui_surfaces_scope.py:17
from navigator_session.data import SessionData      # precedent tests/handlers/test_ui_surfaces_scope.py:18
from parrot.handlers.studio import setup_studio_routes  # TASK-3957 signature (prefix=, view_wrapper=)
```

### Existing Signatures to Use
```python
# S/studio/_base.py
@dataclass(slots=True)
class StudioUser:                     # :102 ; user_id :114, email, username, groups :117 (list[str]), is_superuser :118
class StudioBaseView(BaseView):       # :121 ; _logger_name = "Parrot.AgentStudio" :139
    async def _resolve_session(self) -> Any            # :141
    async def _get_user(self) -> StudioUser            # :164 (raises HTTPUnauthorized :178/:181)
    @staticmethod
    def _is_superuser(userinfo: dict, user: Any = None) -> bool   # :199
    def _require_owner(self, resource_owner, user) -> None        # :230 (superuser bypass :242)
    async def _pbac_gate(self, resource, action)                  # :308
# navigator.views.BaseView(aiohttp_cors.CorsViewMixin, BaseHandler, web.View) — does NOT override _iter
#   (verified in the installed navigator: navigator/views/base.py:619); aiohttp web.View._iter dispatches verbs.
# FieldSync host seam (external): fieldsync/helpers/tenancy/seam.py:430 ProgrammeScopedView._iter runs its
#   prologue, then `return await super()._iter()` — so StudioBaseView._iter runs AFTER it in the wrapped MRO.
```

### Does NOT Exist
- ~~`StudioUser.tenant`~~, ~~`StudioUser.may_author`~~, ~~`StudioUser.may_administer`~~ — added here
- ~~`StudioBaseView._scope`~~, ~~`_require_author`~~, ~~`_not_found`~~, ~~`_name_taken`~~, ~~`_opted_in`~~, ~~`_studio_gate`~~ — added here
- ~~`StudioBaseView._access`~~, ~~`_studio_partition`~~, ~~`StudioTenantRequired`~~ — TASK-3964 / FEAT-621 W1; do NOT add
- ~~`self._session`~~ on plain `BaseView` subclasses — not populated (`_base.py:132-138`); use `_resolve_session()`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/_base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_base_scope.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/_base.py#StudioUser",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/_base.py#StudioBaseView",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/_base.py#StudioBaseView._get_user",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/_base.py#StudioBaseView._resolve_session",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/_base.py#StudioBaseView._is_superuser",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/_base.py#StudioBaseView._require_owner"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`_error(...)` helpers in handlers return `self.json_response(StudioError(message=…, code=…).model_dump(), status=…)`
(e.g. `meta_agent.py:49-53`, `agents.py:150-162`). Gate errors raised from `_iter` use the same body,
raised as `web.HTTPForbidden` / `web.HTTPNotFound` with `text=json.dumps(body)` and `content_type="application/json"`.

### Key Constraints
- Check order is fixed: `tenant_mismatch` → `studio_disabled` (spec M3 skeleton); `/me` is exempt only from `studio_disabled`.
- `scope.tenant is None` on a `{tenant}` route ⇒ 403 `tenant_mismatch` (spec §2 "Host mount").
- Never resolve the scope in `__init__` or at class creation (C5 / host prologue first).
- Plain host (no resolver, no `{tenant}` in the route): `_iter` adds nothing and `_get_user()` is byte-for-byte the FEAT-467 path (G9, AC3).
- `_not_found` body must be identical to what handlers return for a truly absent record today (`code: "not_found"`, message `"<Kind> '<name>' not found."`, e.g. `drafts.py:290`).
- `_name_taken` body carries no owner, source or tenant (G8).
- Never patch `_get_user`/`_resolve_session`/`_scope` in tests (spec §4 Rule-6 model).

### Cross-feature ordering (package X16)
- Cross-feature ordering: none required — this task is in the spec's early subset (X16 "No sibling dependency"); it may merge before any FEAT-621 (storage) or FEAT-622 (toolkits) task.
- Cross-feature ordering: `studio/_base.py` is also edited by FEAT-621 W1 "Backend selection + partition hook" (adds `_studio_partition`, `_studio_storage`) — serialise, whichever merges first (X16).

### References in Codebase
- `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_scope.py` — real `SessionData` at `request[SESSION_OBJECT]`
- `fieldsync/helpers/tenancy/seam.py:430` (FieldSync repo) — the `_iter` prologue shape the wrapper uses

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Extend `StudioUser` with the three fields (defaults keep every existing constructor call valid) — *why*: spec M3 skeleton.
2. Add `_scope`, `_opted_in`, `_studio_gate`, `_iter` override — *why*: one check order before any record access (AC15) without editing every handler.
3. Add `_require_author`, `_not_found`, `_name_taken` — *why*: later handler tasks reuse exactly one body per condition (X14 "one code, one status").
4. Make `_get_user()` scope-sourced when opted in — *why*: C8 "single source of identity".
5. Write routed tests over `setup_studio_routes(app, prefix="/api/v1/{tenant}/astudio", view_wrapper=…)` with a test middleware that installs a real `SessionData` at `request[SESSION_OBJECT]`.

### `packages/ai-parrot-server/src/parrot/handlers/studio/_base.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    is_superuser: bool = False' _base.py) — :118
# AFTER — insert below `    is_superuser: bool = False` (verified: _base.py:118)
    tenant: str | None = None
    may_author: bool = True
    may_administer: bool = False

# occurrences: 1 (verified: grep -c '    async def _get_user(self) -> StudioUser:' _base.py) — :164
# BEFORE — insert above `    async def _get_user(self) -> StudioUser:` (verified: _base.py:164)
    _STUDIO_ENABLED_EXEMPT: ClassVar[bool] = False

    def _opted_in(self) -> bool:
        """Package X9: a scope resolver is installed on the app."""
        return has_installed_resolver(self.request.app)

    async def _scope(self) -> RequestScope:
        """Resolve the caller's scope once per request (lazy; never in __init__)."""
        cached = getattr(self, "_studio_scope_cache", None)
        if cached is not None:
            return cached
        scope = await get_scope_resolver(self.request.app).resolve(self.request)
        if not scope.tenant:
            scope = dataclasses.replace(scope, tenant=None)
        self._studio_scope_cache = scope
        return scope

    async def _studio_gate(self) -> None:
        """403 tenant_mismatch, then 404 studio_disabled (unless exempt)."""
        declared = self.request.match_info.get("tenant")
        if declared is None and not self._opted_in():
            return
        scope = await self._scope()
        if declared is not None and declared != scope.tenant:
            raise web.HTTPForbidden(text=self._json_error("Tenant mismatch.", "tenant_mismatch"), content_type="application/json")
        if not scope.studio_enabled and not self._STUDIO_ENABLED_EXEMPT:
            raise web.HTTPNotFound(text=self._json_error("Agent Studio is disabled.", "studio_disabled"), content_type="application/json")

    async def _iter(self):  # aiohttp web.View dispatch
        await self._studio_gate()
        return await super()._iter()

    @staticmethod
    def _json_error(message: str, code: str) -> str:
        return json.dumps(StudioError(message=message, code=code).model_dump())

    async def _require_author(self) -> web.Response | None:
        """403 authoring_denied when the resolved scope may not author; None otherwise."""
        # FILL IN: return None when not opted in; else when not (await self._scope()).may_author return
        #   self.json_response(StudioError(message="Authoring is not allowed.", code="authoring_denied").model_dump(), status=403)
        #   — bounded by AC13 / X14 (403).
        raise NotImplementedError

    def _not_found(self, kind: str, name: str) -> web.Response:
        """One 404 body for invisible and absent records (AC5)."""
        return self.json_response(StudioError(message=f"{kind.capitalize()} '{name}' not found.", code="not_found").model_dump(), status=404)

    def _name_taken(self, slug: str) -> web.Response:
        """Non-enumerating 409 (G8): no owner, source or tenant."""
        return self.json_response(StudioError(message=f"Name '{slug}' is not available.", code="name_taken").model_dump(), status=409)

# inside _get_user (:164-197): after building the FEAT-467 StudioUser, when self._opted_in():
#   FILL IN: scope = await self._scope(); return dataclasses.replace(user, is_superuser=scope.is_superuser,
#   groups=sorted(scope.groups), tenant=scope.tenant, may_author=scope.may_author, may_administer=scope.may_administer)
#   — bounded by C8 (scope is the single source in opted-in hosts) and AC3 (unchanged otherwise).
```
**Why**: Helper names and check order are fixed by spec M3. Add imports `import dataclasses`, `import json`, `from typing import ClassVar`, `from parrot.handlers.scope import RequestScope, get_scope_resolver, has_installed_resolver`, `from .models import StudioError` (`models.py:20` imports `parrot.manager.manager` at module level: if importing `.models` from `_base` creates an import cycle, import `StudioError` lazily inside `_json_error`/`_require_author`/`_not_found`/`_name_taken`). `StudioUser` is `slots=True`: use `dataclasses.replace`, never attribute assignment.

### `packages/ai-parrot-server/tests/studio/test_base_scope.py` (CREATE)
```python
"""FEAT-605 M3 — StudioBaseView scope, check order and identity (routed, real SessionData)."""
from __future__ import annotations

import pytest
from aiohttp import web
from navigator_session.data import SessionData
from parrot.handlers.scope import RequestScope
from parrot.handlers.studio import setup_studio_routes
from parrot.handlers.studio._base import StudioBaseView

PREFIX = "/api/v1/{tenant}/astudio"


class _Resolver:
    """Real ScopeResolver returning a configurable RequestScope (never a Mock)."""

    def __init__(self, scope: RequestScope) -> None:
        self.scope = scope

    async def resolve(self, request):
        return self.scope


@web.middleware
async def _session_mw(request, handler):
    # FILL IN: install a real SessionData at request[SESSION_OBJECT] the way navigator_session does
    #   (precedent tests/handlers/test_ui_surfaces_scope.py) — never a Mock with hand-set attributes.
    return await handler(request)


async def test_tenant_mismatch_403(aiohttp_client): ...          # FILL IN (mutation: drop the declared≠resolved check ⇒ RED)
async def test_tenant_none_on_prefixed_route_403(aiohttp_client): ...
async def test_studio_disabled_404(aiohttp_client): ...          # FILL IN (mutation: drop the studio_enabled check ⇒ RED)
async def test_identity_from_scope_when_opted_in(aiohttp_client): ...
async def test_wrapper_prologue_runs_before_scope(aiohttp_client): ...  # wrapper subclass _iter stashes, resolver reads it
async def test_plain_host_unchanged(aiohttp_client): ...         # no resolver, default prefix ⇒ no gate, FEAT-467 identity
```
**Why**: Names match spec §4 mutation table rows `tenant_mismatch check`, `studio_disabled check`, `view_wrapper applied` and unit row `test_identity_from_scope_when_opted_in`.

### FILL IN checklist
- [ ] `_base.py::_require_author` — opted-in gate; bounded by AC13, X14 (403)
- [ ] `_base.py::_get_user` — scope-sourced fields when opted in; bounded by C8 / AC3
- [ ] `test_base_scope.py::_session_mw` — real `SessionData` at `request[SESSION_OBJECT]`; bounded by Rule 6
- [ ] all six tests; bounded by AC15 and the §4 mutation rows

---

## Acceptance Criteria

- [ ] AC15: under `/api/v1/{tenant}/astudio`, declared ≠ resolved tenant ⇒ 403 `tenant_mismatch` before any record access; `studio_enabled=False` ⇒ 404 `studio_disabled` on every route but the exempt view
- [ ] AC16 (scope part): a `view_wrapper` subclass's `_iter` prologue runs before scope resolution and the resolver reads what it stashed (`test_wrapper_prologue_runs_before_scope`)
- [ ] In an opted-in host `StudioUser.is_superuser`/`groups` equal the scope's (`test_identity_from_scope_when_opted_in`)
- [ ] Plain host: no behaviour change (FEAT-467 suites green: `test_scaffold.py`, `test_integration.py`)
- [ ] Mutation: remove the tenant check ⇒ `test_tenant_mismatch_403` RED; remove the enabled check ⇒ `test_studio_disabled_404` RED; resolve the scope in `__init__` ⇒ `test_wrapper_prologue_runs_before_scope` RED

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_base_scope.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_scaffold.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_integration.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass. Rule 6 / spec §4: requests are
> built with `aiohttp_client` or `make_mocked_request` plus a real
> `navigator_session.data.SessionData` at `request[SESSION_OBJECT]`; never patch
> `_get_user`, `_resolve_session` or `_scope` (they are the join under test).

```python
# packages/ai-parrot-server/tests/studio/test_base_scope.py
async def test_tenant_mismatch_403(aiohttp_client): ...
async def test_tenant_none_on_prefixed_route_403(aiohttp_client): ...
async def test_studio_disabled_404(aiohttp_client): ...
async def test_identity_from_scope_when_opted_in(aiohttp_client): ...
async def test_wrapper_prologue_runs_before_scope(aiohttp_client): ...
async def test_plain_host_unchanged(aiohttp_client): ...
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3959 agentstudio-tenant-visibility verified`
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
