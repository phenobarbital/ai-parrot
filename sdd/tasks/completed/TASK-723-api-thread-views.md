# TASK-723: API Endpoints — Thread Views

**Feature**: FEAT-103 — Agent Artifact Persistency
**Spec**: `sdd/specs/agent-artifact-persistency.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-720, TASK-722
**Assigned-to**: unassigned

---

## Context

Implements spec Module 7. Creates aiohttp views for thread management: list, create, load, update metadata, delete with cascade. The `user_id` comes from the JWT/session (same pattern as existing handlers).

---

## Scope

- Create `parrot/handlers/threads.py` with aiohttp views:
  - `GET /api/v1/threads?agent_id=X` — list conversations (sidebar)
  - `POST /api/v1/threads` — create new thread
  - `GET /api/v1/threads/{session_id}` — load thread turns (limit=10)
  - `PATCH /api/v1/threads/{session_id}` — update metadata (title, pinned, tags)
  - `DELETE /api/v1/threads/{session_id}` — delete thread + cascade artifacts
- Register routes in the application router
- Use authentication decorators consistent with existing handlers
- Write integration tests

**NOT in scope**: Artifact CRUD endpoints (TASK-724), handler auto-save integration (TASK-725).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/threads.py` | CREATE | Thread management views |
| `tests/handlers/test_threads.py` | CREATE | API endpoint tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.storage import ChatStorage                    # parrot/storage/__init__.py
from parrot.storage.artifacts import ArtifactStore        # after TASK-720
from parrot.storage.models import ThreadMetadata          # after TASK-717
```

### Does NOT Exist
- ~~`parrot.handlers.threads`~~ — does not exist yet; this task creates it
- ~~`parrot.handlers.ThreadListView`~~ — does not exist

---

## Implementation Notes

### Pattern to Follow
Follow the existing handler pattern in `parrot/handlers/agent.py` and `parrot/handlers/infographic.py`:
- Use `@is_authenticated()` and `@user_session()` decorators
- Extract `user_id` from `request.session` or JWT context
- Access `chat_storage` from `self.request.app.get('chat_storage')`
- Return JSON responses with appropriate status codes

### Key Constraints
- `GET /threads` must return ONLY thread metadata (session_id, title, updated_at) — never turns or artifact content
- `GET /threads/{session_id}` loads the last 10 turns by default; accept `?limit=N` query param
- `DELETE /threads/{session_id}` must cascade to both tables (conversations + artifacts)
- `agent_id` comes from query param on list, from thread metadata on detail views

---

## Acceptance Criteria

- [ ] All 5 endpoints respond correctly
- [ ] `GET /threads` returns lightweight metadata list
- [ ] `GET /threads/{id}` returns last 10 turns
- [ ] `DELETE /threads/{id}` cascade-deletes from both tables
- [ ] Authentication enforced on all endpoints
- [ ] Tests pass

---

## Agent Instructions

When you pick up this task:

1. **Read** existing handler patterns in `parrot/handlers/agent.py` and `parrot/handlers/infographic.py`
2. **Check dependencies** — TASK-720 and TASK-722 must be completed
3. **Implement** thread views following existing patterns
4. **Register** routes in the app router
5. **Run tests** and verify

---

## Completion Note

*(Agent fills this in when done)*
