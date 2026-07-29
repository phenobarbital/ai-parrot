---
type: Wiki Overview
title: 'TASK-1100: nav-admin Concept Catalog Queue Panel'
id: doc:sdd-tasks-completed-task-1100-navadmin-concept-catalog-queue-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: A SvelteKit panel in nav-admin for reviewing proposed/pending_review concept
  rows. Reuses UX patterns from the operational Review Queue (or extracts a shared
  `<CurationQueue>` component). See spec §3 Module 17.
---

# TASK-1100: nav-admin Concept Catalog Queue Panel

**Feature**: FEAT-159 — Topic-Authority Ontology Curation
**Spec**: `sdd/specs/topic-authority-ontology.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1092
**Assigned-to**: unassigned

---

## Context

A SvelteKit panel in nav-admin for reviewing proposed/pending_review concept rows. Reuses UX patterns from the operational Review Queue (or extracts a shared `<CurationQueue>` component). See spec §3 Module 17.

---

## Scope

- Create SvelteKit route for the Concept Catalog Queue at the appropriate path (verify nav-admin route conventions).
- List proposed and pending_review concept rows, filtered by tenant from auth session.
- Actions: approve, reject, submit_for_review — calls the HTTP API.
- Polling refresh at 10s interval.
- Extract shared `<CurationQueue>` component if not already extracted from FEAT-topic-authority-operational.
- Write component tests.

**NOT in scope**: Concept browser (TASK-1101), schema overlay panel (TASK-1102), backend API (TASK-1092).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/routes/ontology/concepts/queue/+page.svelte` | CREATE | Queue page (verify path) |
| `src/lib/components/CurationQueue.svelte` | CREATE | Shared queue component (if not extracted) |
| Tests per nav-admin testing conventions | CREATE | Component tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```
<!-- Verify nav-admin conventions before implementation:
     - Route structure pattern
     - Component library imports
     - Auth/role checking pattern
     - API client/fetch pattern
-->
```

### Does NOT Exist

- ~~`src/routes/ontology/`~~ — route directory does not exist; this task creates it.
- ~~`<CurationQueue>` Svelte component~~ — assumed not extracted yet. Check FEAT-topic-authority-operational for any shared components.
- ~~nav-admin in this repo~~ — verify if nav-admin is in-tree or a separate repository. Adjust file paths accordingly.

---

## Implementation Notes

### Key Constraints

- Polling refresh every 10s (not WebSocket/SSE — per spec non-goals).
- Role guard: only `topic_curator+` can view the queue.
- Transition buttons: "Submit for Review" (curator), "Approve" / "Reject" (reviewer+), "Deprecate" (admin).
- Show concept details: slug, label, synonyms, domain, asserted_by, created_at.
- Error handling: display API errors inline (409 for conflicts, 422 for validation).

### References in Codebase

- Check existing nav-admin panels for UX patterns and component reuse.
- TASK-1092 HTTP API for endpoint contracts.

---

## Acceptance Criteria

- [ ] Queue page renders proposed/pending_review rows within one polling cycle (10s).
- [ ] Transition actions call correct HTTP endpoints.
- [ ] Role-based button visibility (curator sees submit, reviewer sees approve/reject).
- [ ] Error messages displayed for failed transitions.
- [ ] Polling refreshes data every 10s.
- [ ] Component tests pass.

---

## Agent Instructions

When you pick up this task:

1. **Locate nav-admin** — determine if it's in-tree or separate repo
2. **Read** existing nav-admin route/component patterns
3. **Check** if `<CurationQueue>` was already extracted by FEAT-topic-authority-operational
4. **Implement** queue panel following existing nav-admin conventions
5. **Run tests** per nav-admin testing setup

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-05-12
**Notes**: nav-admin (SvelteKit) is NOT present in this repository. Confirmed
by searching for `.svelte` files and `svelte.config*` — none found. The
`packages/` directory contains only Python packages (ai-parrot, ai-parrot-loaders,
ai-parrot-pipelines, ai-parrot-tools, parrot-formdesigner). This task requires
a separate nav-admin frontend repository. The Python backend API (TASK-1092) that
this task depends on is fully implemented. The frontend implementation must be
done in the nav-admin repo when it is available.

**Deviations from spec**: Cannot implement — nav-admin SvelteKit app is in a
separate repository not available in this worktree. Marked done-with-issues.
