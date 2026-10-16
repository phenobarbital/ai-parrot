---
type: feature
base_branch: dev
feature_id: FEAT-691
projects: [ai-parrot-server]
tags: [security, authorization, pbac, ui-surfaces, a2ui]
---

# Feature Specification: Viewer pctx for authenticated share-token holders

**Feature ID**: FEAT-691
**Date**: 2026-10-16
**Author**: Jesus Lara (sdd-fix lane)
**Status**: approved
**Target version**: next

Resolves ledger issue:ca055067b827 (vulnerability, major; discovered from
spec:FEAT-636).

---

## 1. Motivation & Business Requirements

### Problem Statement

`UISurfacesHandler._source_data` (`ui_surfaces.py:782`) selects the principal
context for the guarded one-source fetch with:

```python
share_only = bool(token) and record.user_id != user_id and not (scope and scope_grants(record, scope))
pctx = build_principal_context(record.user_id if share_only else user_id, channel="ui_surfaces")
```

An **authenticated** user who is neither the owner nor scope-granted, but who
presents a valid `?share=` token, satisfies `share_only` and therefore executes
the data fetch under the **owner's** principal context. Their own PBAC is
bypassed: QuerySource scopes rows for the owner, not for them. Any
share-token holder with a session is silently promoted to the owner's
data-plane permissions.

This is a privilege escalation on a data-returning endpoint, so it is filed as
a `vulnerability`, not a `bug`.

### The intended rule is already specified

The issue text noted an apparent conflict with `_refresh`. There is none for
this endpoint — FEAT-636's spec states the rule three times, consistently:

- §2: "an authenticated viewer executes under their own `PermissionContext`
  […] a share-token viewer **has no JWT**, so the endpoint executes under the
  **owner's** pctx".
- §3 M5: "share-token access (**no session user**) → owner pctx
  (`record.user_id`)".
- AC8: "authenticated viewer → viewer pctx; share token → owner pctx".

So the owner's pctx is correct **only when there is no session user**. The
implementation's `share_only` condition is simply the wrong predicate: it tests
*how access was granted* rather than *whether the caller is authenticated*.

### Why the existing test did not catch it

`tests/handlers/test_ui_surfaces_source_data.py::test_share_only_viewer_uses_owner_pctx`
passes `user_id="viewer-9"` (authenticated) with a share token and asserts
`pctx.user_id == "owner-1"`. The test encodes the vulnerable behavior rather
than the spec's rule, so it must be corrected as part of this fix — it is the
reason the defect survived review.

### Goals
- `_source_data` runs under the **caller's** pctx whenever the caller is
  authenticated, regardless of how access was granted (owner, scope, or share
  token).
- `_source_data` runs under the **owner's** pctx only for an anonymous
  (no session user) share-token viewer.
- Stop re-deriving the access reason in the handler: the corrected rule needs
  only `user_id`, so the duplicated `scope_grants` test at the call site is
  deleted rather than re-expressed.
- Regression tests cover the authenticated non-owner, non-scope token holder.

### Non-Goals
- **`_refresh` / `_refresh_linked` are NOT changed.** They use the owner's
  pctx unconditionally, which is deliberate and documented at
  `ui_surfaces.py:660-661` ("Share-bearer refresh runs with the OWNER's
  PermissionContext — never the bearer's identity (spec Known Risk)") and in
  FEAT-636 §2. Refresh re-runs the *owner's* recipe; that is its semantics.
  Revisiting that Known Risk is a separate decision and a separate issue.
- `resolve_surface_access` keeps its current `(record, error)` return shape.
  The issue suggested returning the access reason so the handler stops
  re-deriving it; the corrected predicate removes the re-derivation entirely,
  so widening a function shared with `A2UIHandler` (`a2ui.py:295`) buys
  nothing and is not done.
- No change to access control itself — who may reach the endpoint is
  unchanged. Only which principal the fetch executes as.

---

## 2. Architectural Design

One predicate, in `UISurfacesHandler._source_data`:

```python
# Owner pctx ONLY for an anonymous share viewer (FEAT-636 AC8: "no session
# user"). An authenticated caller always runs under their OWN pctx, however
# access was granted, so a share token can never lend them the owner's PBAC.
pctx = build_principal_context(user_id or record.user_id, channel="ui_surfaces")
```

`build_principal_context(principal: str, *, channel: str)` requires a `str`;
`user_id` is `str | None` (`_user_id()`, `ui_surfaces.py:378`) and
`record.user_id` is the owner's id, so `user_id or record.user_id` is always a
`str`.

The `share_only` local disappears. `scope_grants` stays imported — it is still
used by `resolve_surface_access` at `ui_surfaces.py:214`.

### Resulting identity matrix for `_source_data`

| Caller | Token | Access via | pctx |
|---|---|---|---|
| Owner | — | owner | caller |
| Authenticated, scope-granted | — | scope | caller |
| Authenticated, scope-granted | valid | scope | caller (unchanged) |
| **Authenticated, not owner, not scoped** | **valid** | **share** | **caller — was owner (the fix)** |
| Anonymous | valid | share | owner |
| Anyone | invalid/absent | denied | n/a (404 / 410) |

---

## 3. Module Breakdown

### Module 1: Viewer pctx for authenticated callers
- `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` — the
  predicate above, plus the docstring line that currently says "access granted
  ONLY by a share token → the owner's pctx" (now: anonymous share viewer).
- `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_source_data.py` —
  correct the mis-encoded test, add the regression test.

---

## 4. Test Specification

- `test_share_only_viewer_uses_owner_pctx` — **corrected** to the anonymous
  case (`user_id=None` + valid token) and still asserts `pctx.user_id ==
  "owner-1"`. Renamed to `test_anonymous_share_viewer_uses_owner_pctx` so the
  name states the condition the spec actually requires.
- `test_authenticated_share_token_holder_uses_own_pctx` — **new regression
  test for the vulnerability**: authenticated `viewer-9`, not owner, no scope
  grant, valid `?share=` token → 200 and `pctx.user_id == "viewer-9"`.
  This test fails on `dev` before the fix.
- `test_owner_gets_rows_with_own_pctx` and
  `test_scope_granted_viewer_uses_own_pctx_even_with_share_token` must remain
  green unchanged — they pin the paths the fix must not disturb.

---

## 5. Acceptance Criteria

- [ ] AC1 — An authenticated non-owner, non-scope caller with a valid share
      token executes `_source_data` under their OWN pctx.
- [ ] AC2 — An anonymous share-token viewer still executes under the owner's
      pctx.
- [ ] AC3 — Owner and scope-granted paths are unchanged.
- [ ] AC4 — The new regression test fails on `dev` before the change and
      passes after it (demonstrated, not asserted).
- [ ] AC5 — `_refresh` is untouched.
- [ ] AC6 — `pytest packages/ai-parrot-server/tests/handlers/test_ui_surfaces_source_data.py`
      green; `ruff check` clean on both touched files.

---

## 6. Codebase Contract

### Verified Imports
- `from parrot.auth.permission import build_principal_context` — `ui_surfaces.py:31`
- `scope_grants` — imported `ui_surfaces.py:42`, used `ui_surfaces.py:214`

### Existing Signatures
- `async def _source_data(self) -> web.Response` — `ui_surfaces.py:755`
- `async def _user_id(self) -> str | None` — `ui_surfaces.py:378`
- `def build_principal_context(principal: str, *, channel: str, tenant_id=None, roles=None) -> PermissionContext`
  — `packages/ai-parrot/src/parrot/auth/permission.py:166`
- `async def resolve_surface_access(store, surface_id, user_id, token, *, scope=None) -> tuple[UISurfaceRecord | None, tuple[str, int] | None]`
  — `ui_surfaces.py:180` (NOT modified)

### Does NOT Exist
- No access-reason/enum return from `resolve_surface_access` — and none is
  added by this feature.

---

## 7. Implementation Notes & Constraints
- Touch only `_source_data`; `_refresh` and `_refresh_linked` are out of scope.
- `resolve_surface_access` is shared with `A2UIHandler` (`a2ui.py:295`) — do
  not change its signature.

## 8. Open Questions
None. The identity rule is pinned by FEAT-636 §2/§3 M5/AC8; the `_refresh`
divergence is an accepted, documented Known Risk recorded as out of scope above.
