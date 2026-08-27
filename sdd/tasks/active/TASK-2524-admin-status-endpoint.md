# TASK-2524: Admin status endpoint — `GET /api/v1/admin/status`

**Feature**: FEAT-468 — UI Server Backend — Embedded Admin UI Foundation
**Spec**: `sdd/specs/ui-server-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2523
**Assigned-to**: unassigned

---

## Context

Spec §2 Data Models + §3 Module 2. The dashboard needs one authenticated
JSON endpoint aggregating what the server already knows: version, uptime,
agent/crew counts and dependency health (Postgres, Redis, configured vector
store). Its Pydantic models are also the source for the TS codegen
(TASK-2526).

---

## Scope

- Implement `packages/ai-parrot-server/src/parrot/server/ui/status.py`:
  - Pydantic models `DependencyHealth`, `AgentCounts`, `AdminStatus`
    exactly as in spec §2 Data Models.
  - `AdminStatusHandler(BaseView)` decorated `@is_authenticated()
    @user_session()`, `async def get()` returning `AdminStatus` as JSON.
  - Uptime: record a monotonic start timestamp at registration time.
  - Counts: from `app['bot_manager']` — `get_bots()` (loaded),
    `registry.list_agents()` (registry), DB-agent count (see notes), and
    `list_crews()`.
  - Health probes for `postgres`, `redis`, `vector_store`: each wrapped in
    `asyncio.wait_for(..., timeout=<short>)` + try/except; failure yields
    `status="unreachable"` (or `"unconfigured"`), NEVER a 500.
- Register the route `GET /api/v1/admin/status` from `setup_admin_ui`
  (TASK-2523) — the API part registers even when `dist/` is absent
  (endpoint is UI-agnostic; adjust `setup_admin_ui` accordingly).
- Unit tests: auth required, response shape, degraded dependency.

**NOT in scope**: dashboard UI (TASK-2529), TS codegen (TASK-2526).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/server/ui/status.py` | CREATE | models + handler + probes |
| `packages/ai-parrot-server/src/parrot/server/ui/serving.py` | MODIFY | register status route (API part independent of dist) |
| `packages/ai-parrot-server/src/parrot/server/ui/__init__.py` | MODIFY | export models/handler |
| `packages/ai-parrot-server/tests/test_admin_status.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web
from pydantic import BaseModel
from navigator.views import BaseView                 # pattern across parrot/handlers/*
from navigator_auth.decorators import is_authenticated, user_session
    # decorators.py:144 (is_authenticated), :92 (user_session);
    # class-view form sets self.session / self.user (:118-138)
from parrot.server.version import __version__        # version.py:3 ("0.27.0" today)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:  # :109
    def get_bots(self) -> Dict[str, AbstractBot]: ...  # :918 — loaded/live bots
    def list_crews(self): ...                          # :2381
    # registry attribute set in __init__ (:150); app['bot_manager'] set at :1703

# packages/ai-parrot/src/parrot/registry/registry.py
class AgentRegistry:  # :252
    def list_agents(self) -> List[BotMetadata]: ...    # :1310 (name-sorted)

# Decorator usage precedent — packages/ai-parrot-server/src/parrot/handlers/agent.py:102-104
@is_authenticated()
@user_session()
class AgentTalk(BaseView): ...

# Response-shape precedent (json_response on BaseView) —
# handlers/bots.py:751-754: return self.json_response({...})
```

### Does NOT Exist
- ~~a server-status endpoint today~~ — `GET /api/v1/admin/status` is NEW.
- ~~`BotManager.uptime` / `BotManager.started_at`~~ — no uptime tracking
  exists; this task introduces it (module-level monotonic timestamp).
- ~~a unified health-check framework~~ — probes are hand-written here,
  individually timeboxed.
- ~~a guaranteed DB-agent count API~~ — `ChatbotHandler._get_all` merges
  sources internally (bots.py:702); for counts, derive database count from
  what is cheaply available (e.g. `get_bots()` metadata / registry diff) —
  if no cheap source exists, report `database` from the bot_manager's DB
  loading state and document the choice in the completion note. Do NOT
  invent a `BotManager.count_database_bots()`.

---

## Implementation Notes

### Key Constraints
- Vector-store probe mechanics are the ONE open question in spec §8:
  detect the configured backend and do the cheapest possible liveness
  check; if none configured → `status="unconfigured"`. Respect the
  timebox/fail-soft contract. Document the chosen mechanism.
- Probe timeouts short (~1-2s); run probes concurrently (`asyncio.gather`
  with `return_exceptions=True`).
- All models feed TS codegen — keep field names stable and JSON-friendly
  (no exotic types).
- Google-style docstrings + strict type hints; `self.logger`, never print.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/chat.py:39-41` — decorated BaseView precedent.
- Spec §2 Data Models — copy the model definitions verbatim.

---

## Acceptance Criteria

- [ ] Unauthenticated `GET /api/v1/admin/status` → 401.
- [ ] Authenticated GET → JSON matching `AdminStatus` (version, uptime > 0,
  agent counts, crews, dependencies dict with postgres/redis/vector_store).
- [ ] Dead Redis (probe raises/times out) → its entry `unreachable`,
  endpoint still 200 (test with monkeypatched probe).
- [ ] Endpoint registers even when dist/ is absent.
- [ ] `pytest packages/ai-parrot-server/tests/test_admin_status.py -v` passes; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_admin_status.py
import pytest

class TestAdminStatus:
    async def test_requires_auth(self, app_client): ...
    async def test_shape(self, authed_client, stub_bot_manager):
        # stub_bot_manager: get_bots -> {"a": ...}, registry.list_agents -> [meta],
        # list_crews -> [...] ; assert counts match
        ...
    async def test_degraded_dependency(self, authed_client, monkeypatch):
        # monkeypatch redis probe to raise TimeoutError
        # assert resp.status == 200 and body["dependencies"]["redis"]["status"] == "unreachable"
        ...
    async def test_registered_without_dist(self): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2523 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/ui-server-backend.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/` and update index → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
