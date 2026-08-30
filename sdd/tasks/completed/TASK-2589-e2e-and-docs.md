# TASK-2589: E2E CRUD round-trip test, generated-types sync check, and Admin UI docs section

**Feature**: FEAT-475 — UI Agent Management — Admin UI Agent CRUD
**Spec**: `sdd/specs/ui-agent-management.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2583, TASK-2584, TASK-2587, TASK-2588
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7, §4 Integration Tests, §5 ACs 14–16. Closes the feature:
proves the exact payload shapes the UI sends round-trip through
`ChatbotHandler`, guards codegen drift, and documents agent management
for adopters.

---

## Scope

- `packages/ai-parrot-server/tests/test_admin_ui_agent_crud.py`: aiohttp
  test client with `ChatbotHandler.configure(app, '/api/v1/bots')`, a stub
  `bot_manager` (`registry.has → False`, `remove_bot` no-op,
  `_register_bot_into_manager` monkeypatched to a no-op returning a stub
  bot) and an in-memory `BotModel` persistence stand-in (monkeypatch
  `_get_db_agents`, `_get_db_agent`, and `BotModel.insert/update/delete`
  or the `self.handler` connection). Flow:
  1. `PUT` name `"My Bot"` + `storage:"database"` → 201, `name == "my-bot"`, body matches `BotMutationResponse`.
  2. `GET /api/v1/bots` lists it; `POST /api/v1/bots/my-bot` `{enabled:false}` → 200.
  3. `GET /api/v1/bots` hides it; `GET ?include_disabled=true` shows it with `enabled:false`.
  4. `DELETE /api/v1/bots/my-bot` → 200; subsequent `GET /api/v1/bots/my-bot` → 404.
  Validate each response body with the Pydantic descriptors from
  `parrot.server.ui.models` (`BotMutationResponse`, `BotsListResponse`).
- Extend the FEAT-468 generated-types sync test so regenerating schemas
  for the six FEAT-475 models yields no diff.
- `docs/admin-ui.md`: add "Agent management" section — tab ↔ field map,
  name slugification caveat on create, registry agents read-only, disabled
  agents + "Show disabled", catalog endpoint, `include_disabled` param,
  library-owned `/api/v1/agent_tools`.

**NOT in scope**: browser-level E2E (Playwright) — not part of this feature.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/test_admin_ui_agent_crud.py` | CREATE | round-trip test |
| `packages/ai-parrot-server/tests/test_ts_codegen.py` (existing, FEAT-468; contract corrected — task named `test_generate_ts_types.py`, actual file is `test_ts_codegen.py`, same correction TASK-2584 made) | VERIFY | `test_schemas_in_sync_with_committed` already generically diffs every model in `_models()` (all 11, including the 6 FEAT-475 ones) against `ui/schemas/*.json` — confirmed still green, no edit needed |
| `docs/admin-ui.md` | MODIFY | agent management section |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.handlers.bots import ChatbotHandler                          # handlers/bots.py:424
from parrot.handlers.models.bots import BotModel                         # handlers/models/bots.py:20
from parrot.server.ui.models import BotsListResponse, BotMutationResponse  # models.py (BotMutationResponse from TASK-2584)
from parrot.utils.naming import slugify_name, deduplicate_name           # utils/naming.py:15, :42 (used by put())
from aiohttp import web; from aiohttp.test_utils import TestClient, TestServer
```

### Existing Signatures to Use
```python
# handlers/bots.py
ChatbotHandler.put()            # :756 — pops storage; slugify+dedup (:789-812) — dedup calls self._check_duplicate (:490) → _get_db_agent + registry.has
ChatbotHandler._put_database()  # :852 — db = self.handler; async with await db(self.request) as conn; BotModel(**payload).insert(); _register_bot_into_manager (:505); _provision_vector_store (:910) with {} → returns {"status": ...}
ChatbotHandler._post_database() # :1116 — agent.set(k, v); agent.update(); manager.remove_bot; re-register
ChatbotHandler.delete()         # :1247 — registry check first, then _get_db_agent → db_agent.delete()
ChatbotHandler._get_all()       # :702 — include_disabled param (TASK-2583)
# Auth: ChatbotHandler is an AbstractModel view; `await self.session()` is called in put/post/delete — reuse the
#   session/auth short-circuit pattern from tests/test_admin_status.py (request["authenticated"], monkeypatched get_session).
# self.handler / self._manager: see :445-453 (_manager reads request.app['bot_manager'])
```

### Does NOT Exist
- ~~a live Postgres/Redis in CI~~ — the test must be infra-free (monkeypatched persistence), like `test_admin_status.py`.
- ~~`ChatbotHandler` test fixtures in the repo~~ — grep first (`grep -rl ChatbotHandler packages/ai-parrot-server/tests`); if none, build them here and keep them reusable.
- ~~Playwright / browser tests~~ — not part of this feature.

---

## Implementation Notes

- If monkeypatching `BotModel` persistence proves brittle, patch the
  handler's private helpers (`_get_db_agents`, `_get_db_agent`) and the
  `self.handler` connection factory with an async context manager stub
  whose `insert/update/delete` mutate an in-memory dict — document the
  choice in the test module docstring.
- Docs must state plainly: `name` is the identity; the server may rename
  on create; renaming later is unsupported in the UI.

---

## Acceptance Criteria

- [ ] Round-trip test passes infra-free and validates bodies with the codegen descriptors
- [ ] Generated-types sync test covers the six new models and passes
- [ ] `docs/admin-ui.md` has the "Agent management" section per scope
- [ ] `pytest packages/ai-parrot-server/tests/ -v` and `pnpm test` pass

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_admin_ui_agent_crud.py
async def test_admin_ui_agent_crud_roundtrip(app_with_bots, client): ...
async def test_create_slugifies_and_returns_final_name(...): ...
```

---

## Agent Instructions

1. Read spec §3 Module 7, §4, §5, §6.
2. Confirm all dependency tasks are completed.
3. Implement + docs; move to `sdd/tasks/completed/`, update index → `done`, fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-30
**Notes**: Created `test_admin_ui_agent_crud.py` exercising the REAL
`ChatbotHandler.put`/`get`/`post`/`delete` code paths (not monkeypatched
away) against an in-memory `BotModel` persistence stand-in: `ChatbotHandler
.handler` (the `ConnectionHandler` class attribute) replaced by a stub
async-context-manager factory (patched *after* `configure()` runs, since
the attribute doesn't exist on the class before that — first attempt hit
`AttributeError`, fixed by reordering); `BotModel.insert`/`update`/
`delete` monkeypatched to mutate an in-memory dict;
`ChatbotHandler._get_db_agents`/`_get_db_agent` monkeypatched to read
from that same dict (mirrors TASK-2583's harness);
`_register_bot_into_manager` monkeypatched to a no-op stub bot (the
FEAT-133 reranker/parent_searcher factory sequence and
`BotManager.create_bot`/`configure` are out of scope for a UI-payload
round-trip); `_provision_vector_store` needed no patch (empty
`vector_store_config` short-circuits to `{"status": "none"}`);
`ChatbotHandler._registry` overridden to always return `None` (no
registry-backed agent in this test, so every `registry.has()` check
short-circuits). 3 tests: the full round-trip (PUT "My Bot" → 201
`name=="my-bot"` → `GET` lists it → `POST {enabled:false}` → `GET`
hides it by default / `?include_disabled=true` shows it with
`enabled:false` → `DELETE` → subsequent `GET` 404), a dedicated
slugification-with-non-alphanumeric-input case, and a dedup-collision
case asserting the second same-named agent becomes `my-bot-2`. Every
response body is validated against `BotMutationResponse`/
`BotsListResponse` via `.model_validate()`, not just spot-checked keys.

Corrected the same stale contract entry TASK-2584 already found: the
task named `test_generate_ts_types.py`/described modifying it, but the
actual FEAT-468 file is `test_ts_codegen.py`, whose
`test_schemas_in_sync_with_committed` already generically diffs every
model in `_models()` (all 11, the 5 FEAT-468 + 6 FEAT-475 ones) against
`ui/schemas/*.json` — re-ran it, still green, no edit needed.

Added the "Agent management" section to `docs/admin-ui.md` per scope:
tab ↔ field map (all six tabs, every `BotWritePayload` key), a
dedicated "Name slugification" subsection spelling out that `PUT` may
return a different `name` than typed, the UI always navigates to
`response.name`, and renaming an existing agent is unsupported (`name`
read-only in edit); registry agents stay read-only (with the 403 DELETE
message quoted verbatim); disabled agents + "Show disabled" behavior
(`include_disabled` byte-identical-by-default guarantee); the
`GET /api/v1/admin/catalog` shape + provider-dedup/KB-degradation notes;
and the `/api/v1/agent_tools` library-ownership change. Also updated the
FEAT-468 "What it is" bullet for the Agents page (previously said "No
create/edit/delete — that is a future spec"), which this feature makes
obsolete, with a forward link to the new section.

`pytest packages/ai-parrot-server/tests/`: 1296 passed (1293
pre-TASK-2589 + 3 new), 7 pre-existing failures unrelated to this
feature (identical to every prior task's baseline in this feature), 1
skipped. `ruff check` clean on the new test file. `pnpm test`/`pnpm
build` unaffected (no UI files touched by this task — confirmed via
`git status`, only `docs/admin-ui.md` and the new Python test file).

**Deviations from spec**: none.
