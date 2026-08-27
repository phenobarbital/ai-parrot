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

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-27
**Notes**:
- `StudioAgentsHandler` (GET list/single, POST create, DELETE) +
  `StudioAgentReloadHandler` (POST reload) in `handlers/studio/agents.py`,
  registered in `setup_studio_routes`.
- Create resolves `bot_class` via `BotManager.get_bot_class()` (the
  SAME resolver DB-origin bots use) into an actual `Type[AbstractBot]`,
  then calls `AgentRegistry.register(slug, bot_class, bot_config=...)`
  — NOT `create_agent_factory()` + `register()`, since `register()`
  requires `issubclass(factory, AbstractBot)` and would `TypeError` on
  the async factory FUNCTION `create_agent_factory` returns (confirmed
  by reading `_put_registry`'s own `# TODO: replace with register() once
  signature confirmed` comment in `bots.py` — it bypasses `register()`
  for exactly this reason, reaching into `_registered_agents` directly;
  Studio's `bot_class`-driven design sidesteps the mismatch entirely by
  registering the resolved CLASS).
- `persist: true` writes the lossless YAML (TASK-2509) then re-registers
  FROM that YAML via `load_agent_definitions(file_path.parent)` — not
  just `create_agent_definition()` alone — so `BotMetadata.file_path`
  reflects the on-disk definition of record, not the class-based
  registration's `inspect.getmodule()` fallback. This was REQUIRED, not
  cosmetic: see the safety-guard note below.
- **Safety fix (caught during test-writing, not in the task's explicit
  scope but required for correctness)**: `AgentRegistry.
  delete_factory_agent()` unconditionally unlinks `metadata.file_path`
  once `bot_config.origin == "factory"`. For an agent created WITHOUT
  `persist=true`, `AgentRegistry.register()` still resolves `file_path`
  via `inspect.getmodule(bot_class)` — i.e. the bot_class's own
  FRAMEWORK SOURCE FILE (e.g. `parrot/bots/basic.py`), never a
  throwaway YAML. Without a guard, `DELETE
  /astudio/agents/{non_persisted_name}` would attempt to unlink real
  framework source code. Added a check in `delete()`: refuse (409
  `no_definition`) unless `metadata.file_path` resolves under
  `AGENTS_DIR`. Regression test
  `test_delete_non_persisted_agent_refuses_without_touching_source`
  asserts the source file survives. This is exactly why the
  re-registration in the previous bullet was necessary — a persisted
  agent that DIDN'T re-register from its YAML would ALSO fail this same
  safety check (verified: it did, before the fix).
- **`_base.py` fix (small, necessary correction to TASK-2511's own
  helper — not in this task's Files table, but blocking)**: discovered
  that `navigator_auth.decorators.user_session()`'s class-method wrapper
  OVERWRITES `self.session` with the already-resolved session VALUE
  before the handler body runs (confirmed empirically) — it does not
  leave `BaseView.session()` in place as a callable. TASK-2511's
  `_get_user()` called `await self.session()` unconditionally, which
  would `TypeError` on any REAL (decorated) Studio handler — TASK-2512
  is the first task to actually build one. Added `_resolve_session()`
  (calls `self.session` if callable, else uses it directly) and
  switched `_get_user()` to use it. Verified against both decorated and
  undecorated call sites; TASK-2511's own scaffold tests (which use
  undecorated `StudioBaseView(request)`) still pass unchanged.
- `BaseHandler.error()` only maps a fixed status whitelist (400/401/403/
  404/406/412/428) and silently falls back to 400 for anything outside
  it — this task needs 409/422/503, so handlers return a local `_error()`
  → plain `json_response(StudioError(...), status=...)` instead.
- Tests bypass `@is_authenticated()`/`@user_session()` via
  `__wrapped__` peeling (pattern: `test_comm_center_handler.py::
  _call_get_batches`), constructing handlers via the real `Handler
  (request)` constructor (not `__new__`) since `aiohttp.web.View
  .__init__` just sets `self._request` — no router/middleware needed.
  Auth enforcement itself stays covered by TASK-2511's
  `test_scaffold.py`.
- **Process note**: caught mid-run that `AGENTS_DIR` is imported (bound
  as a separate local name) in BOTH `parrot.registry.registry` AND
  `parrot.handlers.studio.agents` — patching only one in tests left
  `create_agent_definition` writing into the REAL machine's
  `agents/agents/{general,test}/` directories (verified: 3 stray YAML
  files landed in the actual `~/proyectos/ai-parrot/agents/` tree, NOT
  the worktree). Removed them immediately (confirmed via `git status`
  that directory is untracked/gitignored — no repo history impact) and
  fixed the fixture to patch both bindings. No lasting effect; noting
  here so the same footgun isn't repeated in TASK-2513+ tests that also
  call `create_agent_definition`/`load_agent_definitions`.

**Deviations from spec**: none functionally.
1. `_base.py` was modified (see note above) even though not listed in
   this task's Files table — a minimal, necessary bugfix to a helper
   TASK-2511 shipped but never exercised through a real decorated
   handler. No other unrelated changes were made to that file.
2. PBAC checks (`_pbac_allowed`) are NOT invoked by these endpoints —
   the task's scope explicitly separates PBAC *content* from this
   task ("NOT in scope" only lists drafts/files/vector-store
   provisioning, but the broader spec/TASK-2511 note PBAC policy
   *content* is out of scope everywhere in FEAT-467); ownership
   enforcement via `_require_owner` is the access-control mechanism
   this task actually implements, matching its own acceptance criteria.

Verification: `pytest packages/ai-parrot-server/tests/studio/
test_agents_lifecycle.py -v` → 17/17 passed. `ruff check
packages/ai-parrot-server/src/parrot/handlers/studio/` → clean except 3
intentional `BLE001`/`G201` best-effort/fail-open patterns matching
`handlers/bots.py::_put_registry`'s identical style. Full regression
sweep (`tests/studio/`, `tests/manager/`, ephemeral-owner, DB-bot
fallback tests) → 64/64 passed.
