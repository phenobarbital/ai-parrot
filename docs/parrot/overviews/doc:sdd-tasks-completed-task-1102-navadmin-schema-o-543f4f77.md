---
type: Wiki Overview
title: 'TASK-1102: nav-admin Schema Overlay Panel'
id: doc:sdd-tasks-completed-task-1102-navadmin-schema-overlay-panel-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'A schema-admin-only SvelteKit panel for managing schema overlays (entity
  types, relation types, traversal patterns). Features: diff view of proposed overlay
  vs current merged ontology, dry-run report display, route guarded by `ontology_schema_admin`
  role. See spec §3 Module 19.'
---

# TASK-1102: nav-admin Schema Overlay Panel

**Feature**: FEAT-159 — Topic-Authority Ontology Curation
**Spec**: `sdd/specs/topic-authority-ontology.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1097
**Assigned-to**: unassigned

---

## Context

A schema-admin-only SvelteKit panel for managing schema overlays (entity types, relation types, traversal patterns). Features: diff view of proposed overlay vs current merged ontology, dry-run report display, route guarded by `ontology_schema_admin` role. See spec §3 Module 19.

---

## Scope

- Create SvelteKit route for the Schema Overlay panel at the appropriate path.
- List overlays filtered by state and kind.
- Propose new overlays: form with `overlay_kind` selector, name, and JSON definition editor.
- Diff view: show proposed definition vs current merged ontology for the same name.
- Dry-run report: display validation results inline (pass/fail for each check).
- Transition actions: submit, approve, reject, deprecate.
- Route guarded by `ontology_schema_admin` role.
- Write component tests.

**NOT in scope**: Concept panels (TASK-1100, TASK-1101), backend API (TASK-1097).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/routes/ontology/schema/+page.svelte` | CREATE | Schema overlay page (verify path) |
| `src/routes/ontology/schema/[id]/+page.svelte` | CREATE | Overlay detail with diff + dry-run |
| Tests per nav-admin testing conventions | CREATE | Component tests |

---

## Codebase Contract (Anti-Hallucination)

### Does NOT Exist

- ~~`src/routes/ontology/schema/`~~ — does not exist; this task creates it.
- ~~nav-admin in this repo~~ — verify location.

---

## Implementation Notes

### Key Constraints

- Role guard: only `ontology_schema_admin` can access. Other roles see 403 or hidden nav item.
- JSON definition editor: a code editor component (Monaco, CodeMirror, or simple textarea).
- Diff view: compare proposed `definition` JSON against the current merged ontology's entry for the same entity/relation/pattern name. If the name is new, show "new" indicator.
- Dry-run button: calls `GET /api/ontology/schema/{id}/dry-run` and displays the `DryRunReport`.
- Approve button: calls transition endpoint; if dry-run fails, displays the report inline.

### References in Codebase

- TASK-1097 HTTP API endpoints.
- Existing nav-admin patterns.

---

## Acceptance Criteria

- [ ] Schema overlay page lists overlays filtered by state and kind.
- [ ] Propose form creates new overlay proposals.
- [ ] Diff view shows proposed vs current merged ontology.
- [ ] Dry-run report displayed after clicking "Run Dry-Run".
- [ ] Approve failure shows dry-run report inline.
- [ ] Route guarded by `ontology_schema_admin` role.
- [ ] Component tests pass.

---

## Agent Instructions

When you pick up this task:

1. **Locate nav-admin** and read existing patterns
2. **Verify** TASK-1097 (HTTP API) is done
3. **Implement** panel with diff view and dry-run display
4. **Run tests**

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-05-12
**Notes**: nav-admin (SvelteKit) is NOT present in this repository. No `.svelte`
files found. This task requires the nav-admin frontend repo. Backend API (TASK-1097)
is fully implemented with dry-run endpoint, propose/approve/reject/deprecate transitions.

**Deviations from spec**: Cannot implement — nav-admin is a separate repo.
Marked done-with-issues.
