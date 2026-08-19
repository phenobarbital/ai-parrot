# TASK-2250: Reserved-segment guard for tenant/literal collisions

**Feature**: FEAT-429 — Remove `/t/` marker from tenant-qualified URLs
**Spec**: `sdd/specs/fieldsync-tenant-url.spec.md` (v0.2, Module 5)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2246
**Assigned-to**: unassigned

---

## Context

Removing `/t/` puts the dynamic `{tenant}` segment at the same URL tree
level as literal segments (`org`, `form-controls`). **Verified behavior**
(real server, aiohttp 3.14.3, both registration orders — spec §2 v0.2):
aiohttp falls through from a literal branch with no matching sub-route to
the dynamic sibling. A tenant slug equal to a reserved literal therefore
gets a MIXED surface: `/api/v1/org/forms` → 200 with `tenant="org"`, while
`/api/v1/org/graph` silently serves the org handler's data. Not a benign
404 — hence an active guard, resolved as spec Q1.

Implements spec Module 5 (added in v0.2).

---

## Scope

1. **Reserved-set computation**: `setup_form_api` (and `setup_form_ui` for
   the UI root level) compute the set of literal segments they themselves
   register at the same tree level as `{tenant}` — today `{"org",
   "form-controls"}` for the API — and stash it on the app under
   `app["formdesigner_reserved_tenant_segments"]`. DERIVED from the actual
   registrations in the function (a module-level tuple next to the route
   table is acceptable if introspection is impractical, but it must live in
   the same function that registers the literals, so a future literal
   cannot be added without touching the same diff).
2. **Decorator rejection**: `requires_tenant` returns **404** (the plain
   not-found shape — NOT 403, no existence oracle) when the declared tenant
   is in the reserved set. 404 makes the colliding slug's surface
   CONSISTENT (uniformly unreachable) instead of mixed.
3. **Boot warning**: at setup time, log a `WARNING` for each tenant in
   `registry.list_tenants()` that collides with the reserved set — the
   operator's signal that a provisioned tenant is unreachable by design.

**NOT in scope**:
- Changing `declared_tenant()`, `assert_body_tenant_matches()`,
  `enforce_membership_unless_public()` — their bodies stay untouched.
- Any route path change (TASK-2246).
- Rejecting reserved slugs at provisioning time (host-side concern).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../api/tenant.py` | MODIFY | reserved-set check in `requires_tenant` (see AC5 amendment in spec: this is the ONLY body change allowed) |
| `.../api/routes.py` | MODIFY | compute + stash the reserved set in `setup_form_api`; boot WARNING loop |
| `.../ui/routes.py` | MODIFY | same for the UI root level literals |
| `tests/unit/api/test_reserved_segment_guard.py` | CREATE | the three §4 guard tests |

All paths under `packages/parrot-formdesigner/src/parrot_formdesigner/`
unless noted.

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use

```python
# api/tenant.py (post TASK-2246/2247 state)
def requires_tenant(*, public: bool = False) -> Callable    # line ~100
#   inner reads: tenant = (request.match_info.get("tenant") or "").strip()
#   ADD after the empty check, before authorization:
#     reserved = request.config_dict.get("formdesigner_reserved_tenant_segments", frozenset())
#     if tenant in reserved: raise web.HTTPNotFound()  (plain 404 body shape)

# api/routes.py
def setup_form_api(app, registry, *, ...):                  # line 116
#   literal registrations at the {tenant} tree level:
#   f"{bp}/org/..." routes (line 389+), f"{bp}/form-controls" (line 294)

# services/registry.py
def list_tenants(self) -> list[str]                          # exists on FormRegistry
```

### Does NOT Exist

- ~~`RESERVED_TENANT_SEGMENTS` module constant~~ — created by this task
  (inside the setup functions, not module-level in `tenant.py`).
- ~~`requires_tenant(reserved=...)` parameter~~ — do not add one; the set
  travels via the app, so the decorator stays argument-compatible.
- ~~an existing 404 tenant error type~~ — use aiohttp's `HTTPNotFound` with
  the same plain body shape as a missing form (no dedicated slug — spec's
  no-oracle rule).

---

## Implementation Notes

- The check runs AFTER the empty-declaration 400 and BEFORE session
  authorization — a reserved slug 404s identically for members, non-members
  and superusers (no oracle, no mixed surface).
- `request.config_dict` (not `request.app`) so the lookup works if a host
  ever mounts the API on a subapp.
- Keep the decorator's added complexity minimal (one membership test) —
  the declare/authorize/stash semantics must remain byte-compatible
  otherwise (spec AC5).

---

## Acceptance Criteria

- [ ] Declared tenant `"org"` or `"form-controls"` → **404** on EVERY forms
      route (consistent surface), for members, non-members and superusers.
- [ ] The reserved set is derived in the same function that registers the
      literals — no free-floating hardcoded list elsewhere.
- [ ] Boot WARNING logged for a registry tenant colliding with the set.
- [ ] `declared_tenant`, `assert_body_tenant_matches`,
      `enforce_membership_unless_public` bodies unchanged (spec AC5).
- [ ] Spec §4 tests pass: `test_reserved_segment_declared_404`,
      `test_literal_fallthrough_documented`,
      `test_boot_warning_on_colliding_tenant`.
- [ ] `ruff check` clean on the touched files.

---

## Test Specification

| Test | Description |
|---|---|
| `test_reserved_segment_declared_404` | `GET /api/v1/org/forms` and `/api/v1/form-controls/forms` → 404 with the guard active |
| `test_literal_fallthrough_documented` | regression net for the REAL routing: without the guard, `/api/v1/org/forms` reaches `{tenant}` (documents the fall-through this guard exists for); `/api/v1/org/graph` → org handler either way |
| `test_boot_warning_on_colliding_tenant` | registry pre-loaded with tenant `"org"` → WARNING at setup |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (`sdd/specs/fieldsync-tenant-url.spec.md`) — §2 Router
   Ambiguity Analysis (v0.2) and Module 5 are the design.
2. TASK-2246 must already be merged in your worktree (routes without `/t/`).
3. Implement the three scope items; write the three tests.
4. **Run** the new test file + `ruff check`.
5. **Commit**: `feat(formdesigner): reserved-segment guard for tenant/literal collisions (FEAT-429 TASK-2250)`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: *(session or agent ID)*
**Date**: YYYY-MM-DD
**Notes**: *(What was implemented, any deviations from scope, issues encountered.)*

**Deviations from spec**: none | describe if any
