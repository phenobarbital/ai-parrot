# TASK-2936: Documentation — reference guide, Postman collection, host-resolver contract

**Feature**: FEAT-535 — Tenant-aware, permission-based visibility for UI surfaces
**Spec**: `sdd/specs/ui-surfaces-tenant-visibility.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2934, TASK-2935
**Assigned-to**: unassigned

---

## Context

Implements **Module 4**. The frontend reference is the contract Svelte
consumers (navigator-svelte FEAT-560) and hosts (FieldSync) build against;
the Postman collection is how they replay requests. Both must describe the
new columns, the `access` values, the `PATCH` verb, the host hook and the
resolver contract on group vocabulary.

---

## Scope

- `docs/frontend/agentdashboard-a2ui-reference.md`:
  - §3.4 (`:230-267`): the list row's `access` values become `owner|tenant|shared`; metadata gains `tenant`, `visibility`, `allowed_groups`, `recipe_name`, `recipe_params`; add the `PATCH /api/v1/ui/surfaces/{surface_id}` row (body, `200/400/404/422`); note that `POST` accepts `visibility`/`allowed_groups` and that `tenant` is server-set; note `422` when non-private without a tenant.
  - New subsection **3.4.1 Visibility and the host scope resolver**: the three visibilities and their rule (owner → scope → token → 404); viewers read + refresh, owner-only for delete/share/PATCH; superuser = the declared tenant, never cross-tenant; `app["ui_surfaces_scope_resolver"]` protocol with the default's single-program rule; the FieldSync example (URL-declared program + session groups); the **resolver contract**: `allowed_groups` and `scope.groups` are opaque strings intersected as sets, the host guarantees a shared vocabulary, a mismatch makes a `groups` surface visible to its owner only.
  - §3.3 mirror-route row (`:216`): mention the scope-aware access.
  - Back-compat statement: rows and clients that ignore the new fields behave exactly as before.
- `docs/postman/a2ui-agentdashboard.postman_collection.json`, folder "3. UI surfaces (FEAT-492 rehydration)": add `visibility`/`allowed_groups` to the "Pin/save: dashboard" body, add a `PATCH visibility (owner)` request and a `List my surfaces (tenant view)` note in the description.
- If `packages/ai-parrot-server` keeps a changelog, add an entry; otherwise skip (say so in the Completion Note).

**NOT in scope**: code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/frontend/agentdashboard-a2ui-reference.md` | MODIFY | §3.3 row, §3.4 table, new §3.4.1 |
| `docs/postman/a2ui-agentdashboard.postman_collection.json` | MODIFY | body fields + PATCH request |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
None (docs). Every path, verb, status code and field name quoted must match the merged code of TASK-2932..2935 — read `handlers/ui_surfaces.py` and `handlers/ui_surfaces_scope.py` in the worktree before writing.

### Existing Signatures to Use
```text
docs/frontend/agentdashboard-a2ui-reference.md — §3.3 at :207-229 (mirror row :216), §3.4 at :230-267 (list row :236, GET row :237)
docs/postman/a2ui-agentdashboard.postman_collection.json — folder "3. UI surfaces (FEAT-492 rehydration)": List my surfaces · List by kind=dashboard · List by kind=widget · Pin/save: widget · Pin/save: dashboard · Pin/save: refreshable dashboard · …
```

### Does NOT Exist
- ~~a per-user ACL~~ — do not document one.
- ~~cross-tenant listings~~ — never.
- ~~a `tenant` body field~~ — server-set only.

---

## Implementation Notes

### Key Constraints
- Same voice and table style as the surrounding sections; no marketing.
- Keep the Postman JSON valid (`python -m json.tool` round-trip).

---

## Acceptance Criteria

- [ ] §3.4 table and new §3.4.1 present; §3.3 mirror row updated; back-compat statement present
- [ ] Postman collection valid JSON with the PATCH request and the new body fields
- [ ] Every quoted field/status matches the code (spot-checked against the handler)

---

## Test Specification

Documentation only. `python -m json.tool docs/postman/a2ui-agentdashboard.postman_collection.json > /dev/null` must succeed.

---

## Agent Instructions

1. Read spec §2 HTTP contract table, §3 Module 4, §7, §8; read the Completion Notes of TASK-2932..2935 for deviations the docs must reflect.
2. Index → `in-progress` → `done`; move to `completed/`; Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
