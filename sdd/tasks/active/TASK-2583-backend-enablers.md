# TASK-2583: Backend enablers — `?include_disabled` on GET /api/v1/bots and library-owned `/api/v1/agent_tools`

**Feature**: FEAT-475 — UI Agent Management — Admin UI Agent CRUD
**Spec**: `sdd/specs/ui-agent-management.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Python half" items 1–2 and §3 Module 1. Two backend gaps block a
correct CRUD UI: (a) `ChatbotHandler._get_db_agents()` filters
`enabled=True`, so an agent toggled off in the form vanishes from the list;
(b) the tools listing view `ToolList` is registered only in the repo-root
`app.py`, so a wheel install of `ai-parrot-server` has no
`/api/v1/agent_tools` route for the tools picker.

---

## Scope

- Add `include_disabled: bool = False` to `ChatbotHandler._get_db_agents()`;
  when true use `BotModel.all()`-equivalent (no `enabled` filter), otherwise
  keep `BotModel.filter(enabled=True)` verbatim.
- In `ChatbotHandler._get_all()`, read the query param `include_disabled`
  via `self.query_parameters(self.request)` (already used at `:459`);
  truthy values: `"1"`, `"true"`, `"yes"` (case-insensitive).
- In `BotManager.setup()` (next to `ChatbotHandler.configure(...)` at
  `manager.py:1952`), register `ToolList` at `/api/v1/agent_tools` with
  `name='tools_list'`, **idempotently**: skip if
  `'tools_list' in self.app.router.named_resources()`.
- Remove the `ToolList` registration block from repo-root `app.py:151-155`
  (and its now-unused import if nothing else uses it).
- Tests for both behaviours.

**NOT in scope**: the catalog endpoint (TASK-2584), any UI change, any
change to `put`/`post`/`delete` or slugify logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/bots.py` | MODIFY | `_get_db_agents(include_disabled)`, `_get_all` reads the param |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | idempotent `ToolList` registration in `setup()` |
| `app.py` (repo root) | MODIFY | drop `ToolList` route registration |
| `packages/ai-parrot-server/tests/test_bots_include_disabled.py` | CREATE | list behaviour with/without the param |
| `packages/ai-parrot-server/tests/test_tools_list_route.py` | CREATE | route registered by manager; idempotent |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.handlers.bots import ChatbotHandler, ToolList   # handlers/bots.py:424, :1332
from parrot.handlers.models.bots import BotModel            # handlers/models/bots.py:20 (asyncdb datamodel, NOT pydantic)
from asyncdb.exceptions import NoDataFound                  # already imported at bots.py:6
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/bots.py
class ChatbotHandler(_PBACHandlerMixin, AbstractModel):     # :424
    def _agent_name_from_request(self) -> str | None       # :455 — uses self.query_parameters(self.request) at :459
    async def _get_db_agents(self) -> list[BotModel]:      # :463
        #   async with await db(self.request) as conn: BotModel.Meta.connection = conn
        #   agents = await BotModel.filter(enabled=True)   # :469  ← change site
    async def _get_all(self)                                # :702 — db_agents = await self._get_db_agents() at :711; response :751 {"agents","total"}
@user_session()
class ToolList(_PBACHandlerMixin, BaseView):               # :1332; async def get(self) :1343 → {"tools": {...}} :1388

# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:                                           # :109
    def setup(self, app) -> web.Application                 # :1686; self.app set :1688-1703
        ChatbotHandler.configure(self.app, '/api/v1/bots')  # :1952  ← add ToolList registration right after
        setup_admin_ui(self.app)                            # :2230

# app.py (repo root) :151-155
        self.app.router.add_view('/api/v1/agent_tools', ToolList, name='tools_list')   # ← remove
# app.py:20 imports ToolList from parrot.handlers.bots (check other uses before removing the import)
```

### Does NOT Exist
- ~~`GET /api/v1/bots?include_disabled`~~ — new here.
- ~~`ToolList` registered anywhere under `packages/ai-parrot-server/src/`~~ — only `app.py`.
- ~~`BotModel` as Pydantic (`model_json_schema`)~~ — asyncdb `Model`; use `BotModel.filter(...)` / `BotModel.all()` per asyncdb datamodel API (verify `all()` exists in the installed `datamodel` before use; fallback `BotModel.filter()` with no kwargs).
- ~~`ChatbotHandler.patch()`~~ — no such method.

---

## Implementation Notes

### Pattern to Follow
- Test harness: `packages/ai-parrot-server/tests/test_admin_status.py` shows
  the auth short-circuit (`request["authenticated"]`) and a stub
  `bot_manager`; monkeypatch `ChatbotHandler._get_db_agents` /
  `_get_db_agent` with in-memory `BotModel`-shaped stand-ins rather than
  touching a DB.
- For the manager test, build a bare `web.Application()`, call the
  minimal code path that registers routes (or call the extracted helper
  directly if you factor the registration into a small
  `_register_tools_list(app)` function — allowed), assert
  `app.router.named_resources()['tools_list']`, call twice, no exception.

### Key Constraints
- Default behaviour byte-identical (AC: "without the param behaviour is
  byte-identical to today").
- No changes to `put`/`post`/`delete`.
- Async throughout; `self.logger` for diagnostics.

---

## Acceptance Criteria

- [ ] `GET /api/v1/bots` without the param hides `enabled=False` DB agents (regression test)
- [ ] `GET /api/v1/bots?include_disabled=true` returns them, `enabled` field present
- [ ] `BotManager.setup()` registers `tools_list`; calling registration twice / pre-registered by host does not raise
- [ ] `app.py` no longer registers `ToolList`; `python -c "import app"`-level import still works
- [ ] `pytest packages/ai-parrot-server/tests/test_bots_include_disabled.py packages/ai-parrot-server/tests/test_tools_list_route.py -v` passes
- [ ] `ruff check` clean on touched files

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_bots_include_disabled.py
async def test_get_all_default_hides_disabled(app_with_bots, client): ...
async def test_get_all_include_disabled(app_with_bots, client): ...   # ?include_disabled=true / =1 / =yes

# packages/ai-parrot-server/tests/test_tools_list_route.py
def test_tools_list_registered_by_manager(): ...
def test_tools_list_registration_idempotent(): ...
```

---

## Agent Instructions

1. Read the spec §2, §3 Module 1, §6.
2. Verify the Codebase Contract line numbers before editing.
3. Implement, run the tests above plus `pytest packages/ai-parrot-server/tests/ -q`.
4. Move this file to `sdd/tasks/completed/`, update `sdd/tasks/index/ui-agent-management.json` → `done`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
