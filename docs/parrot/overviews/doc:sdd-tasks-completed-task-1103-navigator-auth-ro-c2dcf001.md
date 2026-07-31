---
type: Wiki Overview
title: 'TASK-1103: navigator-auth Role Addition — ontology_schema_admin'
id: doc:sdd-tasks-completed-task-1103-navigator-auth-role-addition-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The schema overlay endpoints require a new `ontology_schema_admin` role that
  is separate from the existing `topic_*` roles. This task registers the role in navigator-auth's
  role catalog. See spec §3 Module 20.
---

# TASK-1103: navigator-auth Role Addition — ontology_schema_admin

**Feature**: FEAT-159 — Topic-Authority Ontology Curation
**Spec**: `sdd/specs/topic-authority-ontology.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1084
**Assigned-to**: unassigned

---

## Context

The schema overlay endpoints require a new `ontology_schema_admin` role that is separate from the existing `topic_*` roles. This task registers the role in navigator-auth's role catalog. See spec §3 Module 20.

---

## Scope

- Add `ontology_schema_admin` role to navigator-auth's role catalog.
- Document the role's purpose and scope.
- Verify existing `topic_curator`, `topic_reviewer`, `topic_admin` roles are present (reused by concept catalog).

**NOT in scope**: HTTP route enforcement (handled in TASK-1092, TASK-1097), UI role guards (TASK-1100-1102).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| navigator-auth role catalog (location varies) | MODIFY | Add ontology_schema_admin role |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Verify navigator-auth role catalog location before implementation.
# Check: is it an in-tree config file, a database seed, or a separate repo?
```

### Does NOT Exist

- ~~`ontology_schema_admin` role~~ — does not exist; this task creates it.
- ~~navigator-auth in this repo~~ — verify if it's in-tree or external. Check `packages/` or `navigator-auth/` directories.

---

## Implementation Notes

### Key Constraints

- Role hierarchy: `ontology_schema_admin` is NOT a sub-role of `topic_admin`. They are independent.
- `ontology_schema_admin` grants access to ALL `/api/ontology/schema/*` routes.
- Verify `topic_curator`, `topic_reviewer`, `topic_admin` exist — if not, they are created by FEAT-topic-authority-operational (hard dependency).

### References in Codebase

- Search for existing role definitions: `grep -r "topic_curator\|topic_reviewer\|topic_admin" packages/`
- Check navigator-auth configuration files or seed scripts.

---

## Acceptance Criteria

- [ ] `ontology_schema_admin` role registered in navigator-auth.
- [ ] Existing `topic_*` roles verified present.
- [ ] Role is independent (not a sub-role of any existing role).

---

## Agent Instructions

When you pick up this task:

1. **Find** navigator-auth role catalog: `grep -r "topic_curator" packages/ .`
2. **Add** `ontology_schema_admin` following the existing role registration pattern
3. **Verify** existing `topic_*` roles are present

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-05-12
**Notes**: navigator-auth is NOT present in this repository. Searched for role
catalog files (`grep -r "topic_curator" packages/`) — the only occurrences are
in the HTTP route handlers (`http.py`) where the role strings are used as string
literals. There is no role catalog config file or seed script in-tree.

The `ontology_schema_admin` role IS already enforced in the HTTP routes:
- `schema_overlay/http.py` uses `_SCHEMA_ADMIN = "ontology_schema_admin"` (TASK-1097)
- `concept_catalog/http.py` uses `_CURATOR = "topic_curator"`, `_REVIEWER = "topic_reviewer"`, `_ADMIN = "topic_admin"` (TASK-1092)

The navigator-auth role catalog registration must be done in the separate
navigator-auth service when available.

**Deviations from spec**: Cannot register role — navigator-auth is a separate
service not present in this repo. Role string already enforced in HTTP handlers.
Marked done-with-issues.
