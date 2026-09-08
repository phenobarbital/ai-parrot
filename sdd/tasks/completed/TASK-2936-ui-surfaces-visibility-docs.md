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

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-07
**Notes**:
- `docs/frontend/agentdashboard-a2ui-reference.md`:
  - §3.3 mirror-route row updated to mention the scope-aware access rule.
  - §3.4 table: list row gains `tenant`/`visibility`/`allowed_groups`/
    `recipe_name`/`recipe_params` fields and `access: owner|tenant|shared`
    (with the dedupe/tag-priority note); GET row notes the tenant/group
    viewer `200`; POST row notes the `422` tenant rule; refresh row notes
    viewer refresh under owner pctx; NEW `PATCH` row (owner-only,
    `200`/`400`/`404`/`422`); DELETE/share rows explicitly marked
    owner-only.
  - `PublishSurfaceRequest` JSON example gains `visibility`/
    `allowed_groups`; prose gains the "no `tenant` field in the body"
    rule right where the `access` rules are already documented.
  - New §3.4.1 "Visibility and the host scope resolver": the three
    visibilities and their rule, access order (owner → scope → token →
    404), owner-only mutations, superuser rule, the
    `app["ui_surfaces_scope_resolver"]` protocol + default single-program
    resolver, the FieldSync example resolver (using the exact
    `declared_programme`/`resolve_session_authorization` names from spec
    §8), the group-vocabulary contract, and the back-compat statement.
  - Every quoted field/status/class name spot-checked against the merged
    `ui_surfaces.py`/`ui_surfaces_scope.py`/`models/ui_surfaces.py` in this
    worktree (not the spec text alone) — including the Completion Notes
    of TASK-2932..2935 for the two documented deviations (raw-list
    `allowed_groups` encoding is an internal detail, not client-visible,
    so it is NOT mentioned in the client-facing doc; the `_patch_visibility`
    ownership-check-before-tenant-check deviation is also internal-only,
    the client-visible contract — `404` non-owner, `422` tenant rule — is
    unchanged and is what the doc describes).
  - `python -m json.tool` not applicable to this file (Markdown); no other
    validation tooling exists for prose docs in this repo.
- `docs/postman/a2ui-agentdashboard.postman_collection.json`: added
  `visibility`/`allowed_groups` to the "Pin/save: dashboard" body; added a
  "List my surfaces (tenant view)" request (folder note); added a new
  "PATCH visibility (owner)" request with a body and a status-code test
  script. Edited via a Python `json.load`/`json.dump(..., ensure_ascii=False)`
  round-trip to keep the diff scoped to the intended additions (the first
  attempt used the default `ensure_ascii=True`, which re-escaped every
  existing em-dash in the ENTIRE file into `—` — reverted via `git
  checkout` and redone with `ensure_ascii=False`; verified with `git diff`
  that only the 2 intended line replacements + 2 new blocks remain).
  `python -m json.tool docs/postman/a2ui-agentdashboard.postman_collection.json
  > /dev/null` succeeds.
- Changelog: `packages/ai-parrot-server` has no package-scoped
  `CHANGELOG.md` of its own (only a repo-root `CHANGELOG.md` covering all
  distributions together, maintained per-release rather than per-task —
  see its own `[Unreleased]` heading and the FEAT-528 "whoever cuts the
  release decides the number" convention this spec's own header cites).
  Per the task's literal condition ("if `packages/ai-parrot-server`
  keeps a changelog") — skipped, per the task's own instruction to say so.

**Deviations from spec**: none.
