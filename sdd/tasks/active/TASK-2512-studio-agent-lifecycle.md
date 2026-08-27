# TASK-2512: Studio agent lifecycle endpoints (create/list/read/reload/delete)

**Feature**: FEAT-467 — Agent Studio — Management API
**Spec**: `sdd/specs/agentstudio-management.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2509, TASK-2510, TASK-2511
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 — the core agent CRUD of the Studio:
`POST/GET /api/v1/astudio/agents[/{name}]`,
`POST /api/v1/astudio/agents/{name}/reload`, `DELETE`. Reuses the proven
patterns of `ChatbotHandler` (slugify, server-set ownership, merged
registry+DB view) without touching `bots.py`.

---

## Scope

- Implement `StudioAgentsHandler(StudioBaseView)` in
  `handlers/studio/agents.py`:
  - `POST /api/v1/astudio/agents` — validate `CreateAgentRequest`; slugify
    name; duplicate check against registry + DB; register into
    `AgentRegistry`; `persist: true` → `create_agent_definition`
    (lossless, TASK-2509); owner = session user (server-set, never
    client-supplied). 201 with `{name, persisted, source}`.
  - `GET /api/v1/astudio/agents[/{name}]` — merged registry+DB view
    (pattern `ChatbotHandler._get_all` / `_get_one`); includes origin,
    owner, enabled, file/YAML path when applicable.
  - `POST /api/v1/astudio/agents/{name}/reload` — delegate to
    `BotManager.reload_agent` (TASK-2510); 200 with `ReloadResult`,
    404 unknown, 422 on reload failure (old agent still serving).
  - `DELETE /api/v1/astudio/agents/{name}` — factory-origin YAML agents
    via `delete_factory_agent` + `manager.remove_bot`; ownership enforced.
- Register routes in `setup_studio_routes`.
- Unit tests for each verb + ownership/admin matrix.

**NOT in scope**: drafts (TASK-2513), file CRUD (TASK-2514), vector-store
provisioning (reuse note only — Studio create does NOT provision stores).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/agents.py` | CREATE | lifecycle handler |
| `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` | MODIFY | add routes |
| `packages/ai-parrot-server/tests/studio/test_agents_lifecycle.py` | CREATE | verb + ownership tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.registry import agent_registry                    # registry/__init__.py:7-12
from parrot.registry.registry import BotConfig                # registry.py:222
from parrot.utils.naming import slugify_name, deduplicate_name  # used at handlers/bots.py:28
# BotModel: packages/ai-parrot-server/src/parrot/handlers/models/bots.py:20
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:  # :109 — reach via self.request.app['bot_manager'] (:1702)
    async def reload_agent(self, name: str) -> ReloadResult: ...  # NEW (TASK-2510)
    def remove_bot(self, name): ...  # :811

# packages/ai-parrot/src/parrot/registry/registry.py
class AgentRegistry:
    def register(self, name, factory, *, replace=False, bot_config=None, **kw): ...  # :522
    def has(self, name) -> bool: ...                 # :621
    def list_agents(self) -> List[BotMetadata]: ...  # :1310
    def get_metadata(self, name) -> Optional[BotMetadata]: ...  # :624
    def create_agent_definition(self, config: BotConfig, category="general") -> Path: ...  # :1053 (lossless after TASK-2509)
    def delete_factory_agent(self, name: str) -> tuple[bool, str]: ...  # :1090
    def create_agent_factory(self, config: BotConfig) -> AgentFactory: ...  # :839

# Patterns (READ, do not modify): handlers/bots.py
#   ChatbotHandler.put :756 — storage split, slugify (:790-800), created_by
#     server-set from session (:864-869), 201 payload (:894-905)
#   _get_all :702 / _get_one :653 — merged view; _registry_agent_to_dict :618
#   _check_duplicate :490
```

### Does NOT Exist
- ~~Vector-store provisioning in Studio create~~ — out of scope; only
  `ChatbotHandler._provision_vector_store` (bots.py:910) does that today.
- ~~`AgentRegistry.delete` for repo-origin agents~~ — only factory-origin
  YAML agents are deletable via `delete_factory_agent`; repo/decorator
  agents → 409 explaining why.
- ~~`BotManager.create_bot_from_config` one-shot helper~~ — compose from
  `create_agent_factory` + `register` yourself.
- ~~`owner` column on `BotMetadata`~~ — carry owner in
  `bot_config.config['created_by']` (mirrors BotModel.created_by).

---

## Implementation Notes

### Pattern to Follow
`ChatbotHandler.put` (bots.py:756-905) is the reference create flow —
replicate its slugify/duplicate/created_by discipline, but target the
registry (+optional YAML persist) instead of `BotModel` writes.
Merged listing: mirror `_get_all`/`_registry_agent_to_dict`.

### Key Constraints
- Ownership: `created_by` from session, never from payload; mutations
  require owner-or-admin (`_require_owner` from TASK-2511).
- `bot_class` values validated against the base-class catalog names
  (`parrot.bots.__all__`); unknown → 400.
- Reload endpoint must NOT leave the name unregistered on failure —
  that guarantee lives in `reload_agent` (TASK-2510); the handler just
  maps the typed errors (404/422).
- async, Pydantic, `self.logger`.

### References in Codebase
- `handlers/agents/ephemeral.py` — clean modern handler shape (error
  mapping 401/400/503/500 at :165-207).

---

## Acceptance Criteria

- [ ] Create → registered; `persist: true` writes lossless YAML under
      `AGENTS_DIR/agents/<category>/`.
- [ ] Duplicate name → 409; bad slug → 400; unknown bot_class → 400.
- [ ] GET list merges registry + DB agents; GET one → 404 when absent.
- [ ] Reload delegates to `reload_agent`; 422 keeps old agent serving.
- [ ] DELETE enforces ownership; repo-origin delete → 409.
- [ ] `pytest packages/ai-parrot-server/tests/studio/test_agents_lifecycle.py -v` passes.
- [ ] `ruff check packages/ai-parrot-server/src/parrot/handlers/studio/` clean.

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_agents_lifecycle.py
class TestStudioAgents:
    async def test_create_registers_agent(self, studio_app): ...
    async def test_create_persist_writes_yaml(self, studio_app, tmp_agents_dir): ...
    async def test_create_duplicate_409(self, studio_app): ...
    async def test_created_by_server_set(self, studio_app): ...
    async def test_list_merges_registry_and_db(self, studio_app): ...
    async def test_reload_success_and_failure(self, studio_app): ...
    async def test_delete_ownership_matrix(self, studio_app): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2509, TASK-2510, TASK-2511 completed
3. **Verify the Codebase Contract** before writing any code
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
