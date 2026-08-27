# TASK-2522: API documentation + end-to-end integration tests

**Feature**: FEAT-467 — Agent Studio — Management API
**Spec**: `sdd/specs/agentstudio-management.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2512, TASK-2513, TASK-2514, TASK-2515, TASK-2516, TASK-2517, TASK-2518, TASK-2519, TASK-2520, TASK-2521
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 14 — closes the feature: a complete API reference for the
`/api/v1/astudio/*` surface (pattern: `docs/vectorstore_handler_api.md`)
and the end-to-end integration tests from spec §4 that exercise the
primary loops across modules.

---

## Scope

- Write `docs/agent_studio_api.md`: every endpoint (method, route, request/
  response models, error codes), the draft→activate lifecycle, reload
  semantics (including the "working memory not migrated" contract),
  BYOK behavior, skills-catalog flows (publish/import/resync), scheduler
  run-now, and the `/api/v1/agents/factory` alias note.
- Implement integration tests (spec §4 table):
  - `test_studio_full_loop` — create → PUT identity/kb/skill files →
    reload → `test/ask` reflects new identity.
  - `test_draft_to_live` — assistant scaffolds draft → validate →
    activate → agent listed + answers.
  - `test_skills_catalog_share_flow` — user A publishes → user B lists by
    category/owner → imports → reload → skill triggers.
  - `test_byok_test_run` — stored user key reaches the provider client
    (assert `api_key` kwarg), not the server key.
  - `test_scheduler_run_now_e2e` — schedule → run_now → last-result
    populated.
  - `test_factory_alias` — legacy factory route still functions.
- Update `docs/API_ENDPOINTS.md` with the astudio section (file exists —
  verified in wiki index).
- Run the full studio test suite + ruff as the feature's exit gate.

**NOT in scope**: new functionality; fixing bugs found belongs to the
owning task (reopen it) unless trivial.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/agent_studio_api.md` | CREATE | full API reference |
| `docs/API_ENDPOINTS.md` | MODIFY | add astudio section |
| `packages/ai-parrot-server/tests/studio/test_integration.py` | CREATE | six e2e tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Everything exercised through the HTTP surface built by TASK-2511..2521 —
# import the studio conftest fixtures:
#   studio_app, tmp_agents_dir, vault_keys  (tests/studio/conftest.py, TASK-2511/2516)
```

### Existing Signatures to Use
```python
# Documentation pattern to copy: docs/vectorstore_handler_api.md
#   (~7.6k tokens: endpoint tables, payload examples, error tables)
# Existing endpoint inventory to extend: docs/API_ENDPOINTS.md

# Route inventory (as built by prior tasks — verify against
# handlers/studio/__init__.py setup_studio_routes before documenting):
#   POST/GET  /api/v1/astudio/agents[/{name}]
#   POST      /api/v1/astudio/agents/{name}/reload
#   DELETE    /api/v1/astudio/agents/{name}
#   POST/GET  /api/v1/astudio/drafts[/{name}] ; POST .../activate ; DELETE
#   POST      /api/v1/astudio/assistant
#   GET/PUT/DELETE /api/v1/astudio/agents/{name}/files/{kind}[/{filename}]
#   POST      /api/v1/astudio/agents/{name}/test/ask ; DELETE .../test
#   POST      /api/v1/astudio/tools/{slug}/execute
#   POST      /api/v1/astudio/agents/{name}/tools
#   GET       /api/v1/astudio/toolkits/{slug}/schema
#   POST      /api/v1/astudio/agents/{name}/toolkits
#   GET/POST  /api/v1/astudio/skills ; GET/PUT/DELETE /{id} ;
#   POST      /api/v1/astudio/agents/{name}/skills/import/{id} ;
#   POST      /api/v1/astudio/skills/resync
#   GET/POST  /api/v1/astudio/keys ; DELETE /{provider}
#   GET       /api/v1/astudio/catalog/{base-classes,llm-clients,tools,vector-stores}
#   PATCH     /api/v1/parrot/scheduler/schedules/{id} action="run_now"
#   GET       /api/v1/parrot/scheduler/schedules/{id}/last-result
```

### Does NOT Exist
- ~~Swagger/OpenAPI auto-generation for these routes~~ — documentation is
  the markdown reference (ENABLE_SWAGGER exists on BotManager but do not
  rely on it here).
- ~~Deprecation notes for `/api/v1/bot_management`~~ — resolved: silent;
  the doc must NOT declare the old surface deprecated.

---

## Implementation Notes

### Key Constraints
- Every documented payload copied from the actual Pydantic models
  (`handlers/studio/models.py`) — no invented fields.
- Integration tests mock only the LLM/provider network calls; filesystem,
  registry, and DB paths run real (tmp AGENTS_DIR + test DB/fakes per
  conftest).
- Exit gate: `pytest packages/ai-parrot-server/tests/studio/ -v` fully
  green + `ruff check packages/ai-parrot-server/src/parrot/handlers/studio/`.

### References in Codebase
- `docs/vectorstore_handler_api.md` — structure template.
- `packages/ai-parrot/tests/integration/test_echo_agent_smoke.py` —
  no-mock round-trip precedent.

---

## Acceptance Criteria

- [ ] `docs/agent_studio_api.md` covers every shipped endpoint with
      request/response examples and error tables.
- [ ] `docs/API_ENDPOINTS.md` lists the astudio section.
- [ ] All six integration tests pass.
- [ ] Full suite green: `pytest packages/ai-parrot-server/tests/studio/ -v`
- [ ] `ruff check` clean on the studio package.

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_integration.py
class TestStudioIntegration:
    async def test_studio_full_loop(self, studio_app, tmp_agents_dir): ...
    async def test_draft_to_live(self, studio_app, tmp_agents_dir): ...
    async def test_skills_catalog_share_flow(self, studio_app, tmp_agents_dir): ...
    async def test_byok_test_run(self, studio_app, vault_keys): ...
    async def test_scheduler_run_now_e2e(self, scheduler_app): ...
    async def test_factory_alias(self, studio_app): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — ALL prior FEAT-467 tasks completed
3. **Verify the Codebase Contract** — enumerate the real registered routes
   from `setup_studio_routes` before documenting
4. **Update status** in `sdd/tasks/index/agentstudio-management.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`, fill Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
