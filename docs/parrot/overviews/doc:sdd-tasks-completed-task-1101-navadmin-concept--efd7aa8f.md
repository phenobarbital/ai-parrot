---
type: Wiki Overview
title: 'TASK-1101: nav-admin Concept Browser Panel'
id: doc:sdd-tasks-completed-task-1101-navadmin-concept-browser-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'A SvelteKit panel for browsing approved concepts. Features: is_a ancestor/descendant
  tree view, synonym editor, deprecate action with cascade preview. See spec §3 Module
  18.'
---

# TASK-1101: nav-admin Concept Browser Panel

**Feature**: FEAT-159 — Topic-Authority Ontology Curation
**Spec**: `sdd/specs/topic-authority-ontology.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1092
**Assigned-to**: unassigned

---

## Context

A SvelteKit panel for browsing approved concepts. Features: is_a ancestor/descendant tree view, synonym editor, deprecate action with cascade preview. See spec §3 Module 18.

---

## Scope

- Create SvelteKit route for the Concept Browser at the appropriate path.
- List approved concepts with search, domain filter, and pagination.
- Concept detail view: show is_a subgraph (ancestor/descendant tree), synonyms, metadata.
- Synonym editor: inline edit for `topic_reviewer+`.
- Deprecate action with cascade preview (show affected edges before confirming).
- Write component tests.

**NOT in scope**: Queue panel (TASK-1100), schema overlay panel (TASK-1102), backend API.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/routes/ontology/concepts/+page.svelte` | CREATE | Browser page (verify path) |
| `src/routes/ontology/concepts/[id]/+page.svelte` | CREATE | Concept detail page |
| Tests per nav-admin testing conventions | CREATE | Component tests |

---

## Codebase Contract (Anti-Hallucination)

### Does NOT Exist

- ~~`src/routes/ontology/concepts/`~~ — does not exist; this task creates it.
- ~~nav-admin in this repo~~ — verify location.

---

## Implementation Notes

### Key Constraints

- is_a subgraph: call `GET /api/ontology/concepts/{id}/isa` and render as a tree.
- Synonym editor: call `PATCH /api/ontology/concepts/{id}` with updated synonyms.
- Cascade preview: call a cascade-preview endpoint (or compute client-side from subgraph data).
- Deprecate confirmation dialog: show affected operational edges count before proceeding.
- Pagination: use `limit`/`offset` query params.

### References in Codebase

- TASK-1092 HTTP API endpoints.
- Existing nav-admin patterns for data tables and detail views.

---

## Acceptance Criteria

- [ ] Browser lists approved concepts with search and pagination.
- [ ] Concept detail shows is_a tree visualization.
- [ ] Synonym editor works for `topic_reviewer+`.
- [ ] Deprecate action shows cascade preview before confirming.
- [ ] Component tests pass.

---

## Agent Instructions

When you pick up this task:

1. **Locate nav-admin** and read existing patterns
2. **Verify** TASK-1092 (HTTP API) is done
3. **Implement** browser and detail views following existing conventions
4. **Run tests**

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-05-12
**Notes**: nav-admin (SvelteKit) is NOT present in this repository. No `.svelte`
files found. This task requires the nav-admin frontend repo. Backend API (TASK-1092)
is fully implemented and provides the required HTTP endpoints.

**Deviations from spec**: Cannot implement — nav-admin is a separate repo.
Marked done-with-issues.
