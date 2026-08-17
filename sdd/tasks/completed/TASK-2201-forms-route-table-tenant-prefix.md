# TASK-2201: Forms route table under `/t/{tenant}` + tenant-qualified public-form paths

**Feature**: FEAT-421 — Client-declared tenant in the forms URL
**Spec**: `sdd/specs/forms-tenant-in-url.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2200
**Assigned-to**: unassigned

---

## Context

Implements spec Modules 4 **and** 7 as one atomic change. They are deliberately
fused: `public_form_paths` derives the auth-exempt globs that navigator-auth
matches, so a re-prefixed route with an unqualified glob means every public
form 404s for anonymous users. Splitting them across two commits guarantees a
window where public forms are broken.

This is the hard cut. Old forms paths are simply not registered — `GET
/api/v1/forms/{uid}` becomes a router 404.

---

## Scope

- `api/routes.py`: re-prefix every **forms** route from `{bp}/forms/...` to
  `{bp}/t/{{tenant}}/forms/...`, and `{bp}/fields` to
  `{bp}/t/{{tenant}}/fields`. Old paths are NOT registered.
- Pass `tenant="none"` on the **nine** `/org/*` routes; their paths stay
  byte-identical (spec G7).
- Pass `tenant="public"` on the five public-form routes
  (`{form_uid}`, `/schema`, `/render/{format}`, `/data`, `/validate`).
- `ui/routes.py`: re-prefix the HTML page + Telegram routes the same way.
- `services/public_forms.py`: `public_form_paths(form_uid, tenant, base_path)`
  emits `{bp}/t/{tenant}/forms/{form_uid}...` globs. Update the `_public_toggle`
  closure in `api/routes.py` to pass the form's tenant.
- Add the router-wide coverage tests `test_every_forms_route_is_decorated` and
  `test_no_org_route_is_decorated`.

**NOT in scope**: `handlers.py` internals (TASK-2202), module-level handlers
(TASK-2203), telegram/audio internals (TASK-2204), migrating the existing test
suite's URLs (TASK-2206).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | Route table + `_public_toggle` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/ui/routes.py` | MODIFY | HTML + Telegram route paths |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/public_forms.py` | MODIFY | `tenant` parameter |
| `packages/parrot-formdesigner/tests/unit/services/test_public_forms.py` | MODIFY | Tenant-qualified globs |
| `packages/parrot-formdesigner/tests/unit/api/test_route_tenant_coverage.py` | CREATE | Router introspection |

---

## Codebase Contract (Anti-Hallucination)

### Verified Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/public_forms.py:6-41
def public_form_paths(form_uid: str, base_path: str = "/api/v1") -> list[str]:
    bp = base_path.rstrip("/")                    # :33
    base = f"{bp}/forms/{form_uid}"               # :34
    return [base, f"{base}/schema", f"{base}/render/*",
            f"{base}/data", f"{base}/validate"]   # :35-41
# ^ EXACTLY five globs. Keep the count and the order.

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
bp = base_path.rstrip("/")                        # :204
# route table                                     # :207-360
```

### The nine `/org/*` routes — paths MUST NOT change (spec G7, AC11)

```
GET    {bp}/org/graph                                   -> handler.get_org_graph
POST   {bp}/org/projects                                -> handler.create_project
POST   {bp}/org/cost-centers/{project_id}/workday-map   -> handler.map_project_workday
POST   {bp}/org/users/{user_id}/assign                  -> handler.assign_user_role
POST   {bp}/org/sync/workday                            -> handler.sync_workday_identities
GET    {bp}/org/stores/{store_id}/sites                 -> handler.list_sites
POST   {bp}/org/stores/{store_id}/sites                 -> handler.create_site
GET    {bp}/org/sites/{site_id}/locations               -> handler.list_locations
POST   {bp}/org/sites/{site_id}/locations               -> handler.create_location
GET    {bp}/org/locations/{location_id}                 -> handler.get_location
```

(`sync_workday_identities` does not resolve a tenant today; the other nine
call sites do — see TASK-2202. All ten `/org/*` routes take `tenant="none"`.)

### Ordering constraints that MUST be preserved

```python
# api/routes.py:211-214 — literal segments registered BEFORE the {form_uid}
# catch-all so "blank" is never captured as a form_uid:
app.router.add_post(f"{bp}/forms/from-db", ...)   # :209
app.router.add_post(f"{bp}/forms/blank", ...)     # :213
app.router.add_get(f"{bp}/forms/{{form_uid}}", ...)  # :214
```

### Does NOT Exist

- ~~backwards-compatible aliases for the old paths~~ — the spec mandates a hard
  cut (resolved decision, §8). Do NOT register both shapes, and do NOT add a
  redirect.
- ~~`request.query.get("program_slug")`~~ — forbidden (AC3).
- ~~a tenant on the `/org/*` routes~~ — G7. If a `/org/*` path gains
  `/t/{tenant}`, AC11 fails.
- ~~`public_form_paths` having a tenant parameter today~~ — this task adds it.
  Both call sites (`_public_toggle` in `api/routes.py`, and the FEAT-241
  exclude-provider) must be updated together or the exclusions silently drift.

---

## Implementation Notes

### Key Constraints

- The audio WS route (`{bp}/forms/{form_uid}/audio/ws`) is registered WITHOUT
  `_wrap_auth` — it is mounted directly because navigator-auth returns 401 and
  breaks the WS upgrade. Re-prefix its path here; its inline tenant check is
  TASK-2204's job. Do not wrap it.
- `ui/routes.py` also registers `{bp}/api/v1/forms/{form_uid}/telegram-submit`
  (a nested `api/v1` under the UI prefix) — re-prefix it consistently and note
  it for TASK-2204.
- Keep `bp = base_path.rstrip("/")` and build the tenant prefix as a separate
  local (e.g. `tp = f"{bp}/t/{{tenant}}"`) so the table stays readable.
- `_public_toggle` receives `(form_uid, is_public)` from the registry callback.
  It now needs the tenant too — resolve it from the registry at callback time
  rather than caching it, so a re-tenanted form cannot leave a stale exemption.

### References in Codebase

- `api/routes.py:204-360` — the table.
- `api/routes.py` FEAT-241 M6 block — `_public_toggle` and `register_exclusions`.
- `services/public_forms.py:6-41` — the globs.

---

## Acceptance Criteria

- [ ] Every forms route is mounted under `{bp}/t/{tenant}/` (spec AC1)
- [ ] `GET {bp}/forms/{uid}` resolves to a 404 from the router (hard cut)
- [ ] All ten `/org/*` paths are byte-identical to 0.8.21 and registered with `tenant="none"` (AC11)
- [ ] `POST /forms/blank` still registers before the `{form_uid}` catch-all
- [ ] `public_form_paths("u", "flexroc")` returns five globs, all containing `/t/flexroc/`
- [ ] `test_every_forms_route_is_decorated` passes
- [ ] `test_no_org_route_is_decorated` passes
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/`

> Note: the package test suite will be RED after this task — the existing 26
> test files still use old URLs. TASK-2206 restores green. Do not "fix" those
> tests here; that is a separate task by design.

---

## Test Specification

```python
class TestPublicFormPaths:
    def test_paths_are_tenant_qualified(self):
        paths = public_form_paths("abc-uid", "flexroc")
        assert len(paths) == 5
        assert all("/t/flexroc/forms/abc-uid" in p for p in paths)
        assert paths[0].endswith("/forms/abc-uid")
        assert any(p.endswith("/render/*") for p in paths)


class TestRouteTenantCoverage:
    def test_every_forms_route_is_decorated(self, app):
        for route in app.router.routes():
            path = _path_of(route)
            if "/forms" in path or path.endswith("/fields"):
                assert _has_tenant_layer(route.handler), f"undecorated: {path}"

    def test_no_org_route_is_decorated(self, app):
        for route in app.router.routes():
            if "/org/" in _path_of(route):
                assert not _has_tenant_layer(route.handler)

    def test_org_paths_unchanged(self, app):
        paths = {_path_of(r) for r in app.router.routes() if "/org/" in _path_of(r)}
        assert "/api/v1/org/graph" in paths
        assert not any("/t/" in p for p in paths)

    def test_legacy_forms_path_not_registered(self, app):
        paths = {_path_of(r) for r in app.router.routes()}
        assert "/api/v1/forms/{form_uid}" not in paths
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/forms-tenant-in-url.spec.md` (Modules 4 and 7, §7 risks)
2. **Check dependencies** — TASK-2200 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/forms-tenant-in-url.json` → `"in-progress"`
5. **Implement** Modules 4 and 7 in ONE commit — never separately
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2201-forms-route-table-tenant-prefix.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-16
**Notes**: Modules 4+7 landed atomically as instructed. `api/routes.py`: all
forms/fields routes re-prefixed to `{bp}/t/{tenant}/...`; all ten `/org/*`
routes kept byte-identical paths with `tenant="none"`; the five public-form
routes (`{form_uid}`, `/schema`, `/render/{format}`, `/data`, `/validate`)
got `tenant="public"`; `/forms/blank` still precedes the `{form_uid}`
catch-all; audio WS route re-prefixed but deliberately left undecorated
(TASK-2204). `ui/routes.py`: HTML page routes re-prefixed the same way;
Telegram routes re-prefixed for path consistency but left unwrapped
(inline check is TASK-2204's job). `services/public_forms.py`:
`public_form_paths` gained a required `tenant` positional param, building
`/t/{tenant}/forms/...` globs.

Two implementation decisions beyond the literal task text, both
necessitated by constraints the task didn't fully resolve on its own:
1. **`/form-controls`**: not classified as forms or org in the spec. It's
   static, tenant-agnostic field-type catalog metadata (no registry
   access) — I gave it `tenant="none"` and left its path unprefixed, same
   carve-out as `/org/*`. Flagging for spec-owner confirmation.
2. **`_public_toggle` tenant resolution**: `FormRegistry`'s callback
   signature is fixed to `(form_uid, is_public)` and is explicitly
   "unchanged" per the spec's Integration Points, and `unregister()` fires
   the callback AFTER deleting the form — so the registry can no longer
   answer "what tenant was this form under" by the time `is_public=False`
   fires. Register-time (`is_public=True`) resolves the tenant by
   searching `list_tenants()` + `registry.get(uid, tenant=t)` — exactly
   "resolve at callback time, don't cache" as instructed. Unregister-time
   (`is_public=False`, covering both real deletes and public→private
   updates) instead sweeps `unregister_exclusions` across every known
   tenant's glob for that form_uid — idempotent/harmless for tenants that
   never had the exemption, and the only way to guarantee no stale
   exemption survives a delete or a re-tenant given the fixed callback
   signature.

Also worth flagging for the spec owner (not a deviation — implemented
exactly as directed): the five routes sharing `tenant="public"` (e.g. `GET
/forms/{uid}`) serve BOTH public and private forms through the same route
registration. Since `public=True` skips the authorization step for the
whole route (not per-request based on the specific form's `is_public`
flag), an authenticated user who can correctly guess/knows another
tenant's form_uid AND that tenant's slug could reach a private form outside
their `programs` membership — bounded in practice by form_uid being an
unguessable UUID and the 404-on-mismatch `_assert_form_tenant` check
(TASK-2202), but worth a second look given G6.

Full `tests/unit/` suite: confirmed via before/after diff against the
pre-existing 36-failure baseline that exactly 9 additional tests broke,
all attributable to old URL-shape assertions in files explicitly deferred
to TASK-2206 (`test_exclude_provider.py`, `test_setup_form_api.py`,
`test_setup_form_api_rest.py`, `test_setup_form_ui_protect_pages.py`,
`test_setup_form_ui_routes.py`) — no unexpected regressions. New/changed
files carry zero new ruff findings (diff-counted against pre-edit
baselines for `routes.py`/`ui/routes.py`, which carry pre-existing,
unrelated lint debt).

**Deviations from spec**: none (see the two implementation decisions and
the one flagged design risk above — all within the letter of the task,
documented for reviewer visibility, not unilateral redesigns).
