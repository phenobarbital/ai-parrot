# TASK-3660: Studio views: agent toolkits GET/PUT/DELETE, options, mcp-servers + routes

**Feature**: FEAT-593 — Tool Configuration for Agent Studio
**Spec**: `sdd/specs/tool-configuration-agentstudio.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3659
**Assigned-to**: unassigned

---

## Context

Spec §2 New Public Interfaces, §2 Overview (8), §3 Module 7; design research S7 (options on the
persisted spec only); AC1, AC5, AC12. PBAC actions: `astudio:toolkits:persist`,
`astudio:toolkits:options`, `astudio:mcp:persist`. Every write answers `reload_required: true`.

---

## Scope

- `StudioAgentToolkitsHandler`: `GET /agents/{name}/toolkits` (masked specs via `mask_spec`,
  `unavailable` = slugs whose class no longer resolves), `PUT /agents/{name}/toolkits/{slug}`
  (body `ToolkitConfigPutRequest`), `DELETE /agents/{name}/toolkits/{slug}`.
- `StudioToolkitOptionsHandler`: `GET /agents/{name}/toolkits/{slug}/options/{param}` — param must
  be in the class's `options_params` (404 otherwise); spec must be persisted (409 `not_configured`);
  build the instance from `await hydrate_params(spec)` filtered to the ctor; `asyncio.wait_for(instance.config_options(param), 15)`;
  close via `await instance._close()` if `auto_open`/`_opened` (best-effort); failures → 502 `options_failed`.
  **Request query parameters are ignored** (S7).
- `StudioAgentMcpServersHandler`: `GET`/`PUT /agents/{name}/mcp-servers`.
- Error mapping: LookupError → 404 `not_found`; PermissionError → 409 `read_only_definition`;
  ValueError → 422 `invalid_params`; RuntimeError (vault) → 503 `vault_unavailable`; ValidationError/JSON → 400.
- Order in every method: PBAC gate → resolve agent/owner → `_require_owner` → act.
- Routes in `setup_studio_routes` after the existing toolkits routes (:113-114).
- Tests via `make_mocked_request` like test_toolkits.py, patching `AgentToolingStore`.

**NOT in scope**: `/me` override routes (TASK-3661).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py` | CREATE | StudioAgentToolkitsHandler, StudioToolkitOptionsHandler, StudioAgentMcpServersHandler |
| `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` | MODIFY | Register the new routes |
| `packages/ai-parrot-server/tests/studio/test_toolkit_config.py` | CREATE | Handler tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (dev @ `ce602539c`, 2026-09-23). Use these exact imports,
> names and signatures. Anything not listed here must be verified with `grep`/`read` first.

### Verified Imports
```python
from navigator_auth.decorators import is_authenticated, user_session  # verified: toolkits.py:22
from pydantic import ValidationError
from ._base import StudioBaseView  # verified: toolkits.py:33
from .agents import _StudioAgentsMixin  # verified: toolkits.py:34
from .models import (StudioError, ToolkitConfigPutRequest, AgentToolkitsResponse, ToolkitPersistResponse,
                     AgentMcpServersPutRequest, AgentMcpServersResponse, ToolkitOptionsResponse)  # StudioError :23; rest TASK-3659
from .tooling_store import AgentToolingStore  # TASK-3659
from parrot.tools.spec import hydrate_params, mask_spec, mask_mcp  # TASK-3645
import asyncio, inspect
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/_base.py
@dataclass(slots=True)
class StudioUser: user_id: str; email; username; groups; is_superuser: bool = False  # :102-119
class StudioBaseView(BaseView):  # :121
    async def _get_user(self) -> StudioUser: ...                 # :164
    def _require_owner(self, resource_owner, user) -> None: ...  # :230 — raises web.HTTPForbidden; superuser bypass
    async def _pbac_gate(self, resource: str, action: str): ...  # :308 — returns a denial response or None
# packages/ai-parrot-server/src/parrot/handlers/studio/agents.py
class _StudioAgentsMixin:
    def _manager(self)  # :42 — request.app.get("bot_manager")
    def _registry(self)  # :46 — manager.registry
    async def _get_db_agent(self, name) -> BotModel | None  # :51 — `db = self.request.app.get("database")`;
        #   `async with await db.acquire() as conn: BotModel.Meta.connection = conn; await BotModel.get(name=name)`
    @staticmethod
    def _registry_agent_owner(meta) -> str | None  # :106 — str(bot_config.config["created_by"])
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py — handler pattern to copy (decorators + error helper + PBAC + owner):
@is_authenticated()
@user_session()
class StudioToolkitsHandler(_StudioAgentsMixin, StudioBaseView):  # :217-219
    def _error(self, message, *, status, code=None, details=None):  # :227 → json_response(StudioError(...).model_dump(), status=)
    async def post(self):  # :286-316 — `if (denied := await self._pbac_gate("toolkits", "astudio:toolkits:assign")) is not None: return denied`
        # owner = str(db_agent.created_by) if db agent else self._registry_agent_owner(meta); self._require_owner(owner, user)
# packages/ai-parrot-server/src/parrot/handlers/studio/byok.py — vault error convention: `except RuntimeError` → 503 code="vault_unavailable" (:104-109)

# packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py
STUDIO_PREFIX = "/api/v1/astudio"  # :23
    from .toolkits import StudioToolkitsHandler  # :111
    app.router.add_view(f"{STUDIO_PREFIX}/toolkits/{{slug}}/schema", StudioToolkitsHandler)  # :113
    app.router.add_view(f"{STUDIO_PREFIX}/agents/{{name}}/toolkits", StudioToolkitsHandler)  # :114 ← anchor
# test helpers pattern: packages/ai-parrot-server/tests/studio/test_toolkits.py:30-55 (_unwrap, _decode, _make_handler)
```

### Does NOT Exist
- ~~`GET /astudio/toolkits/{slug}/options/{param}` (unscoped)~~ — options are agent-scoped by design (S7).
- ~~reading options inputs from the query string~~ — forbidden.
- ~~`/agents/{name}/datasets` endpoint~~ — datasets are the `dataset_manager` toolkit (spec §2).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_toolkit_config.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py#StudioToolkitsHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/_base.py#StudioBaseView._pbac_gate",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/_base.py#StudioBaseView._require_owner"
  ]
}
```

---

## Implementation Notes

- aiohttp routing: `/agents/{name}/toolkits` (GET list) is already registered to
  `StudioToolkitsHandler` for POST. Register the NEW handler on distinct paths:
  `/agents/{name}/toolkits/{slug}` (PUT/DELETE), `/agents/{name}/toolkit-config` (GET list — FILL IN:
  decide between a distinct GET path or adding a `get` method to `StudioToolkitsHandler` that
  delegates when `name` is in match_info — bounded by "one view class per path" in aiohttp; the
  existing POST must keep working), `/agents/{name}/toolkits/{slug}/options/{param}`,
  `/agents/{name}/mcp-servers`. Record the final GET path in the Completion Note and in the docs task.
- Use `ToolkitPersistResponse(...).model_dump()` for write responses.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks derive from the spec's Interface
> Skeletons (§3) and the §6 Edit Sites table, re-verified at task time. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Decide the GET-list path (see notes) — *why*: aiohttp maps one view class per resource path.
2. Implement the three views with the shared `_resolve_owner(name)` helper — *why*: PBAC → owner → act order.
3. Register routes — *why*: AC1.
4. Tests: happy PUT, read-only 409, vault 503, options 409/404/502/200, query params ignored.

### `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py` (CREATE — skeleton)
```python
"""Agent Studio agent-level tooling endpoints (FEAT-593)."""
from __future__ import annotations

# imports exactly as listed in the Codebase Contract

_OPTIONS_TIMEOUT_S = 15.0


class _ToolingViewMixin(_StudioAgentsMixin):
    def _error(self, message: str, *, status: int, code: str | None = None, details: dict | None = None):
        return self.json_response(StudioError(message=message, code=code, details=details).model_dump(), status=status)

    async def _authorize(self, name: str, action: str):
        """PBAC gate then ownership; returns (store, state) or an error response."""
        if (denied := await self._pbac_gate("toolkits", action)) is not None:
            return denied
        store = AgentToolingStore(self)
        try:
            state = await store.load(name)
        except LookupError:
            return self._error(f"Agent '{name}' not found.", status=404, code="not_found")
        self._require_owner(state.owner, await self._get_user())  # raises HTTPForbidden
        return store, state

    def _map_exc(self, exc: Exception):
        # FILL IN: PermissionError→409 read_only_definition; ValueError→422 invalid_params;
        #   RuntimeError→503 vault_unavailable; LookupError→404 not_found (message only, no secrets)
        raise exc


@is_authenticated()
@user_session()
class StudioAgentToolkitsHandler(_ToolingViewMixin, StudioBaseView):
    """GET list · PUT/DELETE one toolkit's agent-level config."""

    async def get(self): ...      # FILL IN — AgentToolkitsResponse with mask_spec dumps + unavailable
    async def put(self): ...      # FILL IN — ToolkitConfigPutRequest → store.put_toolkit → ToolkitPersistResponse
    async def delete(self): ...   # FILL IN — store.delete_toolkit → ToolkitPersistResponse


@is_authenticated()
@user_session()
class StudioToolkitOptionsHandler(_ToolingViewMixin, StudioBaseView):
    """GET dynamic options evaluated on the PERSISTED spec only (never request input)."""

    async def get(self): ...      # FILL IN — see scope; action "astudio:toolkits:options"


@is_authenticated()
@user_session()
class StudioAgentMcpServersHandler(_ToolingViewMixin, StudioBaseView):
    """GET/PUT the agent-level MCP server list."""

    async def get(self): ...      # FILL IN — AgentMcpServersResponse with mask_mcp dumps
    async def put(self): ...      # FILL IN — AgentMcpServersPutRequest → store.put_mcp_servers; action "astudio:mcp:persist"
```

### `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'app.router.add_view(f"{STUDIO_PREFIX}/agents/{{name}}/toolkits", StudioToolkitsHandler)' __init__.py)
# AFTER that line (verified: __init__.py:114) insert:

    # FEAT-593: agent-level tooling persistence (Agent Studio Tools tab)
    from .toolkit_config import (  # pylint: disable=import-outside-toplevel
        StudioAgentMcpServersHandler,
        StudioAgentToolkitsHandler,
        StudioToolkitOptionsHandler,
    )

    app.router.add_view(f"{STUDIO_PREFIX}/agents/{{name}}/toolkits/{{slug}}", StudioAgentToolkitsHandler)
    app.router.add_view(f"{STUDIO_PREFIX}/agents/{{name}}/toolkits/{{slug}}/options/{{param}}", StudioToolkitOptionsHandler)
    app.router.add_view(f"{STUDIO_PREFIX}/agents/{{name}}/mcp-servers", StudioAgentMcpServersHandler)
    # FILL IN: GET list route per Implementation Notes decision
```

### FILL IN checklist
- [ ] GET-list path decision; bounded by aiohttp one-view-per-path + existing POST
- [ ] `_map_exc` mapping; bounded by spec §2 error codes
- [ ] Each view method body; bounded by AC1/AC5/AC12

---

## Acceptance Criteria

- [ ] PUT returns `{agent, slug, reload_required: true, persisted: true}` (AC1).
- [ ] GET never returns plaintext secrets (AC2).
- [ ] Read-only agent → 409 `read_only_definition` (AC5); vault down → 503 `vault_unavailable`.
- [ ] Options: unknown param 404, unsaved 409 `not_configured`, failure 502 `options_failed`, success list; query params ignored (AC12).
- [ ] PBAC gate is the first statement of every method.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_toolkit_config.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_toolkit_config.py
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers.studio import toolkit_config as tc
from parrot.handlers.studio._base import StudioUser


def _unwrap(m):
    while hasattr(m, "__wrapped__"):
        m = m.__wrapped__
    return m


def _handler(cls, method, match_info, body=None, query=""):
    req = make_mocked_request(method, f"/x{query}", match_info=match_info, app=web.Application())
    if body is not None:
        req.json = AsyncMock(return_value=body)
    h = cls(req)
    h._get_user = AsyncMock(return_value=StudioUser(user_id="42"))
    h._pbac_gate = AsyncMock(return_value=None)
    return h


@pytest.mark.asyncio
async def test_put_read_only_409(monkeypatch):
    # FILL IN: patch tc.AgentToolingStore so load() returns an owned state and put_toolkit raises
    #   PermissionError("py agent"); assert status 409 and code read_only_definition
    ...


@pytest.mark.asyncio
async def test_options_ignores_query(monkeypatch):
    # FILL IN: persisted jira spec; query "?server_url=http://evil"; assert the instance is built from the
    #   persisted server_url and config_options result is returned
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2 Overview, §3 module, §7 risks).
2. **Check dependencies** — verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — before writing ANY code, confirm every import and
   signature listed still exists (`grep`/`read`). If anything moved, update the contract first.
4. **Update status** in `sdd/tasks/index/tool-configuration-agentstudio.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   marker, and never change a signature or path the blueprint fixes.
6. **Verify** all acceptance criteria; run the Validation Commands (in a worktree prefix with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src:packages/ai-parrot-tools/src`).
7. **Move this file** to `sdd/tasks/completed/` and set the index entry to `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker orchestrator (execution `a3f5c9e2-7b41-4d8a-9c3e-591fd0d7a5b2`), coder seat `gpt-5.6-terra` (MCP backend `codex`), delivered via `coder_run_chunk` job `job-2e2efec1764a`, attempt `b61d73771fc94d7bbbcab454646b11a9`.
**Date**: 2026-09-23
**Feature branch**: `feat-FEAT-593-tool-configuration-agentstudio`
**Implementation SHA**: `c7d8b29ddb5f838acce50ff5aab63c529cc591de` (`feat(tool-configuration-agentstudio): TASK-3660 — engine-committed coder deliverable`)
**Lint autofix SHA**: `46137bd27` (`style(tool-configuration-agentstudio): TASK-3660 — engine lint autofix`, 1 residual, 0 errors)
**Merge commit**: `011d79e54`
**Review**: `coder_record_review` recorded — `feedback_id: coder-review:596bb7ccf5a2bc36e0da41d4`, `fix_commits: []`.

**Notes**: `coder_wait`/`coder_merge` returned `outcome: "merged"`, attempt `terminal: "completed"`, 1 attempt,
0 retries, 0 failures (286s). Diff verified against the task's file table: `handlers/studio/toolkit_config.py`
(CREATE, 213 insertions — `StudioAgentToolkitsHandler`, `StudioToolkitOptionsHandler`,
`StudioAgentMcpServersHandler`), `handlers/studio/__init__.py` (MODIFY, 16 insertions — route registration),
and `tests/studio/test_toolkit_config.py` (CREATE, 231 insertions) — exactly the 3 declared files, no unlisted
files, nothing under `sdd/` touched. 1 residual lint finding at merge time — deferred to `/sdd-done` per
project policy (style debt, not fixed per-task).

**Deviations from spec**: none.
