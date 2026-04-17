# TASK-724: API Endpoints — Artifact Views

**Feature**: FEAT-103 — Agent Artifact Persistency
**Spec**: `sdd/specs/agent-artifact-persistency.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-720
**Assigned-to**: unassigned

---

## Context

Implements spec Module 8. Creates aiohttp views for artifact CRUD operations. This is the API the frontend uses to save/load/update/delete artifacts (charts, canvas tabs, infographics, etc.).

---

## Scope

- Create `parrot/handlers/artifacts.py` with aiohttp views:
  - `GET /api/v1/threads/{session_id}/artifacts` — list all artifacts for session (summaries)
  - `POST /api/v1/threads/{session_id}/artifacts` — save new artifact
  - `GET /api/v1/threads/{session_id}/artifacts/{artifact_id}` — get full artifact definition
  - `PUT /api/v1/threads/{session_id}/artifacts/{artifact_id}` — update artifact definition
  - `DELETE /api/v1/threads/{session_id}/artifacts/{artifact_id}` — delete artifact
- Register routes in the application router
- Use authentication decorators
- Write integration tests

**NOT in scope**: Thread management (TASK-723), handler auto-save (TASK-725).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/artifacts.py` | CREATE | Artifact CRUD views |
| `tests/handlers/test_artifacts.py` | CREATE | API endpoint tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.storage.artifacts import ArtifactStore        # after TASK-720
from parrot.storage.models import Artifact, ArtifactType, ArtifactSummary  # after TASK-717
```

### Does NOT Exist
- ~~`parrot.handlers.artifacts`~~ — does not exist yet; this task creates it

---

## Implementation Notes

### Key Constraints
- `user_id` from JWT/session, `agent_id` from request context or thread metadata
- `POST` endpoint: accepts full artifact JSON, creates `Artifact` model, calls `ArtifactStore.save_artifact()`
- `PUT` endpoint: accepts updated definition, calls `ArtifactStore.update_artifact()` — replaces in-place
- `GET` list endpoint: returns `ArtifactSummary` list (no full definitions)
- `GET` detail endpoint: returns full artifact with definition resolved (S3 refs transparent)
- Validate `artifact_type` against `ArtifactType` enum
- Return 404 for non-existent artifacts

---

## Acceptance Criteria

- [ ] All 5 artifact endpoints respond correctly
- [ ] `POST` creates artifact and returns artifact_id
- [ ] `GET` list returns summaries only
- [ ] `GET` detail returns full definition (including S3-resolved)
- [ ] `PUT` replaces artifact definition
- [ ] `DELETE` removes artifact + S3 object
- [ ] Authentication enforced
- [ ] Tests pass

---

## Agent Instructions

When you pick up this task:

1. **Read** existing handler patterns
2. **Check dependencies** — TASK-720 must be completed
3. **Implement** artifact views
4. **Register** routes
5. **Run tests**

---

## Completion Note

*(Agent fills this in when done)*
