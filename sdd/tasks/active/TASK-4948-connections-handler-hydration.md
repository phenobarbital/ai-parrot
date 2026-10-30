# TASK-4948: /api/v1/connections handler, hydration from connections, route registration

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4947
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (G7, AC-8, AC-19, S5). A principal-level API: `GET /api/v1/connections`, `POST
/api/v1/connections/{provider}/start`, `GET /api/v1/connections/{provider}`, `DELETE /api/v1/connections/{provider}`.
The principal comes from the authenticated session only, never the body. `configure_tool_manager` hydrates toolkits
from the principal's connections instead of `user_agent_toolkits` rows — this must land with (or before) the
removal of that table's code (TASK-4949) or web users lose tools.

---

## Scope

- New `handlers/connections.py`: `ConnectionsHandler(BaseView)` decorated like `IntegrationsHandler`; user id via the
  same session lookup; body may carry `return_origin`, `scopes` — any `user_id` in the body is ignored; 401 without session;
  `PermissionError` → 403; `ValueError` → 400.
- `handlers/user_objects.py`: import `list_users_integrations`; hydrate one toolkit per `active` row whose provider is
  registered and has a non-None `toolkit_factory`; resolver `OAuthCredentialResolver(provider.manager)`.
- `manager/manager.py`: import `ConnectionsHandler`; register the four routes next to the integrations routes.
- Tests: `test_connections_handler_principal_from_session`, `test_hydration_from_connections`.

**NOT in scope**: removing `list_user_agent_toolkits` from persistence.py (TASK-4949); provider registration (TASK-4957).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/connections.py` | CREATE | ConnectionsHandler |
| `packages/ai-parrot-server/src/parrot/handlers/user_objects.py` | MODIFY | hydrate from connections |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | 4 routes + import |
| `packages/ai-parrot-server/tests/unit/test_connections_handler.py` | CREATE | handler tests |
| `packages/ai-parrot-server/tests/unit/test_user_objects_hydration.py` | CREATE | hydration test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from navigator.views import BaseView                                        # verified: handlers/integrations.py:21
from navigator_auth.decorators import is_authenticated, user_session        # verified: handlers/integrations.py:23
from navigator_session import get_session                                   # verified: handlers/integrations.py:24
from parrot.auth.oauth2.service import IntegrationsService                  # verified: handlers/integrations.py:27
from parrot.auth.oauth2.persistence import list_users_integrations          # TASK-4946
from parrot.auth.credentials import OAuthCredentialResolver                 # verified: credentials.py:184
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry              # verified: registry.py:69
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/integrations.py — pattern to copy
@is_authenticated()
@user_session()
class IntegrationsHandler(BaseView):                       # :32-34
    async def _get_user_id(self) -> str | None             # :43 request["user_id"] → session user_id/id/username
# packages/ai-parrot-server/src/parrot/handlers/user_objects.py
from parrot.auth.oauth2.persistence import list_user_agent_toolkits        # :18 anchor
async def configure_tool_manager(...)                                      # :99
            enablements = await list_user_agent_toolkits(user_id, agent_id)   # :218 anchor; loop :222-241
# packages/ai-parrot-server/src/parrot/manager/manager.py
from ..handlers.integrations import IntegrationsHandler                    # :41 anchor
        router.add_view("/api/v1/agents/integrations/{agent_id}", IntegrationsHandler)   # :2460-2472 block
# IntegrationsService (after TASK-4947): list_for_principal(user_id, request=None); start_connect(user_id, provider_id,
#   return_origin=None, *, channel="web", principal=None, scopes=None, request=None, extra_state=None);
#   status(user_id, provider_id, request=None); disconnect(user_id, provider_id, request=None)
```

### Does NOT Exist
- ~~`/api/v1/connections*`~~ — new here (only the agent-scoped routes exist, manager.py:2459-2472).
- ~~`ConnectionsHandler`~~ — new.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/connections.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/user_objects.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/manager/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/test_connections_handler.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/test_user_objects_hydration.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/integrations.py#IntegrationsHandler._get_user_id",
    "sym:packages/ai-parrot-server/src/parrot/handlers/user_objects.py#UserObjectsHandler.configure_tool_manager"
  ]
}
```

---

## Implementation Notes

- aiohttp class-based views dispatch by method; `post` must only serve `/{provider}/start` (match_info has `provider`).
- Response for GET list: `[d.model_dump(mode="json") for d in descriptors]` — includes `provider`, `status`, `updated_at` (AC-19).
- Keep `configure_tool_manager`'s session caching and its outer `try/except` unchanged.

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Create the handler (block A) — *why*: G7.
2. Switch hydration (block B) — *why*: U2; must precede TASK-4949.
3. Register routes (block C).
4. Tests.

### `packages/ai-parrot-server/src/parrot/handlers/connections.py` (CREATE)
```python
"""Principal-level connections API (FEAT-773 M6): /api/v1/connections*."""
from __future__ import annotations

import logging

from aiohttp import web
from navigator.views import BaseView  # type: ignore[import]
from navigator_auth.decorators import is_authenticated, user_session  # type: ignore[import]
from navigator_session import get_session  # type: ignore[import]

from parrot.auth.oauth2.service import IntegrationsService


@is_authenticated()
@user_session()
class ConnectionsHandler(BaseView):
    """GET list/one, POST /{provider}/start, DELETE /{provider}. Principal from the session only."""

    async def _get_user_id(self) -> str | None:
        # FILL IN: copy IntegrationsHandler._get_user_id (handlers/integrations.py:43-62) verbatim
        raise NotImplementedError

    async def get(self) -> web.Response:
        # FILL IN: 401 without user; provider in match_info → svc.status(...); else svc.list_for_principal(...)
        raise NotImplementedError

    async def post(self) -> web.Response:
        # FILL IN: body = await self.request.json() (tolerate empty); ignore body user_id; svc.start_connect(user_id,
        #          provider, body.get("return_origin"), scopes=body.get("scopes"), request=self.request);
        #          PermissionError → 403, ValueError → 400
        raise NotImplementedError

    async def delete(self) -> web.Response:
        # FILL IN: svc.disconnect(user_id, provider, request=self.request); PermissionError → 403
        raise NotImplementedError
```

### `packages/ai-parrot-server/src/parrot/handlers/user_objects.py` (MODIFY)
```python
# occurrences: 1 (verified: 'from parrot.auth.oauth2.persistence import list_user_agent_toolkits' :18)
from parrot.auth.oauth2.persistence import list_users_integrations
# occurrences: 1 (verified: '            enablements = await list_user_agent_toolkits(user_id, agent_id)' :218)
            connections = [r for r in await list_users_integrations(user_id) if r.status == "active"]
            if not connections:
                return None
# FILL IN: loop over connections (provider = registry.get(row.provider); skip None and factory → None;
#          idempotency guard on toolkit name); update docstrings at :125 and :205 (no user_agent_toolkits)
```

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: 'from ..handlers.integrations import IntegrationsHandler' :41)
from ..handlers.connections import ConnectionsHandler
# FILL IN: after the last IntegrationsHandler add_view (:2469-2472) register
#   "/api/v1/connections", "/api/v1/connections/{provider}", "/api/v1/connections/{provider}/start"
#   with router.add_view(..., ConnectionsHandler)
```

### FILL IN checklist
- [ ] `connections.py` four methods
- [ ] `user_objects.py` hydration loop + docstrings
- [ ] `manager.py` three add_view calls (four HTTP routes)
- [ ] tests

---

## Acceptance Criteria

- [ ] AC-8: `/api/v1/connections` GET/POST/DELETE exist; principal from the session only (body `user_id` ignored); 401 without session
- [ ] AC-19: GET list returns `provider`, `status`, `updated_at`
- [ ] `configure_tool_manager` registers one toolkit per active connection, with no `user_agent_toolkits` read

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_connections_handler.py -q`
- `pytest packages/ai-parrot-server/tests/unit/test_user_objects_hydration.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/unit/test_connections_handler.py
@pytest.mark.asyncio
async def test_connections_handler_principal_from_session(): ...   # body {"user_id": "999"} ignored; svc called with session id

# packages/ai-parrot-server/tests/unit/test_user_objects_hydration.py
@pytest.mark.asyncio
async def test_hydration_from_connections(): ...                   # two active rows + one revoked → two toolkits
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug delegated-auth-connections --feature-id FEAT-773`)
2. **Read the spec** (`sdd/specs/delegated-auth-connections.spec.md`) — at least §2, the module section named in Context, §5 and §7
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/delegated-auth-connections.json`
4. **Verify the Codebase Contract** before writing ANY code (re-grep each anchor; line numbers drift). If an entry is stale, fix the contract in this file first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH` set to every touched `packages/<dist>/src` (the shared `.venv` imports the main checkout otherwise)
8. **Commit the code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> delegated-auth-connections verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
