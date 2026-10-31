# TASK-5048: Remove the `/enable` compatibility route, handler branch and `EnableResponse` (server + core)

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5035, TASK-5047
**Assigned-to**: unassigned

---

## Context

Spec §2 "Panel and cleanup (M5, M6)", §3 Module 5 (REMOVED lines), G6, AC-9. S-1 kept
`POST /api/v1/agents/integrations/{agent_id}/{provider}/enable` as a no-op returning the current descriptor so the
admin UI kept working. After the UI stops calling it (TASK-5057 removes `confirmIntegrationEnable`; TASK-5055 removes the
pill's call), the route, its handler branch and the `EnableResponse` model go away. The other agent-scoped routes
(list / connect / delete) stay as S-1 aliases (spec Non-Goals).

**Open question gate.** Spec §8 still lists, unresolved: "External callers of
`/api/v1/agents/integrations/{agent}/{provider}/enable` (TROC AgentChat repo) before removal — *Owner: Jesus*."
The spec's §7 risk says removing it "breaks any external client still calling it". This task MUST NOT remove anything
while that question is open (Step 1).

---

## Scope

- Step 1 gate (below). Only if it passes:
- Remove the `/enable` route registration in `BotManager.setup()` routes block.
- Remove the `if path.endswith("/enable")` branch, `_post_enable`, and every `/enable` mention in the handler's
  module/class/`post` docstrings and its 404 message.
- Remove `EnableResponse` from `parrot/auth/oauth2/models.py` and from `parrot/auth/oauth2/__init__.py` (import + `__all__`).
- Tests: replace `test_confirm_enable_removed_enable_route_noop` with `test_enable_route_removed`; drop
  `TestEnableResponse` and its import from `test_models.py`.

**NOT in scope**: UI removal of `confirmIntegrationEnable` / `EnableResponse` TS type (TASK-5057) and the pill (TASK-5055);
generated TS types (TASK-5052); the list/connect/delete agent-scoped routes (they stay).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | drop the `/enable` route |
| `packages/ai-parrot-server/src/parrot/handlers/integrations.py` | MODIFY | drop branch, `_post_enable`, docstrings |
| `packages/ai-parrot/src/parrot/auth/oauth2/models.py` | MODIFY | drop `EnableResponse` |
| `packages/ai-parrot/src/parrot/auth/oauth2/__init__.py` | MODIFY | drop the export |
| `tests/unit/integrations/oauth2/test_handler.py` | MODIFY | `test_enable_route_removed` |
| `tests/unit/integrations/oauth2/test_models.py` | MODIFY | drop `TestEnableResponse` + import |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.handlers.integrations import IntegrationsHandler   # verified: handlers/integrations.py:34
from parrot.manager.manager import BotManager                  # verified: tests/unit/test_register_oauth2_providers.py:8
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/integrations.py
#   module docstring lists the /enable route (:9-10); class docstring (:40)
async def post(self) -> web.Response:   # :91 — docstring mentions /enable (:96); branch :104-105; 404 text :106-108
async def _post_enable(self) -> web.Response:   # :170-197 (lazy `from parrot.auth.oauth2.models import EnableResponse` :193)

# packages/ai-parrot-server/src/parrot/manager/manager.py
router.add_view("/api/v1/agents/integrations/{agent_id}/{provider}/enable", IntegrationsHandler)   # :2479-2482

# packages/ai-parrot/src/parrot/auth/oauth2/models.py
class EnableResponse(BaseModel): integration: IntegrationDescriptor   # :96-103
# packages/ai-parrot/src/parrot/auth/oauth2/__init__.py
#   `    EnableResponse,` in the `from .models import (` block (:37); `    "EnableResponse",` in __all__ (:69)

# tests/unit/integrations/oauth2/test_handler.py
def handler_request(method: str, suffix: str) -> web.Request   # :18
async def test_confirm_enable_removed_enable_route_noop() -> None   # :89-105 (calls _post_enable)
# tests/unit/integrations/oauth2/test_models.py — EnableResponse import (:13); class TestEnableResponse (:135-145)
```

### Does NOT Exist
- ~~Other `EnableResponse` / `_post_enable` users under `packages/*/src`~~ — `grep -rn "EnableResponse\|_post_enable" packages/*/src`
  lists only the sites above (verified 2026-10-31).
- ~~A resolved answer to spec §8's `/enable` question~~ — still `[ ]` at spec rev 0.3.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/manager/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/handlers/integrations.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/auth/oauth2/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/auth/oauth2/__init__.py", "action": "MODIFY"},
    {"path": "tests/unit/integrations/oauth2/test_handler.py", "action": "MODIFY"},
    {"path": "tests/unit/integrations/oauth2/test_models.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/integrations.py#IntegrationsHandler.post",
    "sym:packages/ai-parrot-server/src/parrot/handlers/integrations.py#IntegrationsHandler._post_enable",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/models.py#EnableResponse"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. **GATE — run first, before any edit**:
   `git fetch origin && git show origin/dev:sdd/specs/connections-web-slack.spec.md | grep -n 'External callers of'`.
   If that line still starts with `- [ ]`, STOP: make no code change, set this task `done-with-issues` via
   `scripts/sdd/close_task.sh TASK-5048 connections-web-slack partial`, and write in the Completion Note
   "Blocked: spec §8 /enable external-callers question unresolved". Continue only when it is `- [x]` **and** says the
   route may be removed — *why*: removing a route an external client still calls is an irreversible API break (spec §7).
2. Delete the route registration — *why*: unknown POST paths then 404 via the router.
3. Delete the handler branch, `_post_enable`, and docstring mentions — *why*: AC-9 "gone end to end".
4. Delete `EnableResponse` and its export — *why*: AC-9; `test_enable_route_removed` asserts it is not importable.
5. Update the two test files and run them.

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            "/api/v1/agents/integrations/{agent_id}/{provider}/enable",' …manager.py)
# DELETE the whole add_view call (verified: manager.py:2479-2482):
#        router.add_view(
#            "/api/v1/agents/integrations/{agent_id}/{provider}/enable",
#            IntegrationsHandler,
#        )
```

### `packages/ai-parrot-server/src/parrot/handlers/integrations.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        if path.endswith("/enable"):' …integrations.py)
# REPLACE :101-108 with:
        path = self.request.path
        if path.endswith("/connect"):
            return await self._post_connect()
        return web.json_response({"error": "Unknown POST endpoint.  Use /connect."}, status=404)

# occurrences: 1 (verified: grep -c '    async def _post_enable(self) -> web.Response:' …integrations.py)
# DELETE `_post_enable` entirely (verified: :170-197).
# Docstrings: drop the /enable bullets at :9-10, :40 and :96; module docstring "four routes" → "three routes".
```

### `packages/ai-parrot/src/parrot/auth/oauth2/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class EnableResponse(BaseModel):' …models.py)
# DELETE `class EnableResponse(BaseModel):` and its body (verified: models.py:96-103, ends before the next class).
# FILL IN: re-verify line numbers — TASK-5035 edits this file first (retry_safe, ChannelLinkPreview); keep its additions.
```

### `packages/ai-parrot/src/parrot/auth/oauth2/__init__.py` (MODIFY)
```python
# occurrences: 1 each (verified: grep -c '    EnableResponse,' / grep -c '    "EnableResponse",' …oauth2/__init__.py)
# DELETE `    EnableResponse,` (:37) and `    "EnableResponse",` (:69).
```

### Tests (MODIFY)
```python
# tests/unit/integrations/oauth2/test_handler.py — REPLACE test_confirm_enable_removed_enable_route_noop (:89-105) with:
@pytest.mark.asyncio
async def test_enable_route_removed() -> None:
    """POST …/{provider}/enable is not routed (404) and EnableResponse is gone."""
    # FILL IN: build the routes the way BotManager.setup() does (or assert on a router built by it) and check that
    #          app.router.resolve() for POST /api/v1/agents/integrations/a1/jira/enable has no IntegrationsHandler match;
    #          IntegrationsHandler(handler_request("POST", "enable")).post() → 404; hasattr(IntegrationsHandler, "_post_enable") is False
    with pytest.raises(ImportError):
        from parrot.auth.oauth2.models import EnableResponse  # noqa: F401

# tests/unit/integrations/oauth2/test_models.py — delete `    EnableResponse,` from the import (:13) and class TestEnableResponse (:135-145).
```

### FILL IN checklist
- [ ] Step 1 gate result recorded in the Completion Note — bounded by spec §8 / §7
- [ ] `models.py` line re-verification after TASK-5035 — bounded by "keep TASK-5035's additions"
- [ ] `test_enable_route_removed` route assertion — bounded by AC-9

---

## Acceptance Criteria

- [ ] Gate passed (or task closed `partial` with the blocker recorded and NO code change).
- [ ] `grep -rn "EnableResponse\|_post_enable\|/enable\"" packages/*/src tests/unit/integrations/oauth2` returns nothing (AC-9).
- [ ] `POST /api/v1/agents/integrations/{agent_id}/{provider}/enable` → 404; list/connect/delete aliases still pass their tests.
- [ ] `ruff check` clean on the four source files.

---

## Validation Commands

- `pytest tests/unit/integrations/oauth2/test_handler.py -q`
- `pytest tests/unit/integrations/oauth2/test_models.py -q`

---

## Test Specification

| Test | Must assert |
|---|---|
| `test_enable_route_removed` | 404 on POST …/enable; `_post_enable` absent; `EnableResponse` not importable |
| existing `test_post_connect_*`, `test_delete_*`, `test_get_keeps_agent_scoped_alias` | unchanged and passing |

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Run the Step 1 gate** before anything else
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/connections-web-slack.json`
4. **Verify the Codebase Contract** before writing ANY code
5. **Update status** in the per-spec index → `"in-progress"` and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit the code** — stage only the files listed above
9. **Close the task** with `scripts/sdd/close_task.sh TASK-5048 connections-web-slack verified` (or `partial` per the gate)
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator
**Date**: 2026-10-31
**Notes**: Step 1 gate NOT passed. Spec §8 open question "External callers of /api/v1/agents/integrations/{agent}/{provider}/enable (TROC AgentChat repo) before removal" (owner: Jesus) is unresolved, so per the task NO code was changed. Two codex seats (sol, terra) correctly returned empty deliveries. Closed `partial`. Follow-up once Jesus confirms no external callers: remove the /enable route, handler branch + _post_enable, EnableResponse (models.py, __init__.py) and update test_handler.py/test_models.py; AC-9 stays open until then.

**Deviations from spec**: none | describe if any
