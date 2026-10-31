# TASK-4970: ConnectionsHandler: /me, /{provider}/token, /{provider}/complete, CLI start + route registration

**Feature**: FEAT-774 — Connections for CLI agents and local MCP toolkits
**Spec**: `sdd/specs/connections-cli-local-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4969
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (AC-5, AC-9): expose the TASK-4969 service methods over HTTP behind navigator-auth
(`@is_authenticated` already decorates `ConnectionsHandler`, so a `parrot-cli` bearer validated by
`Oauth2Provider.authenticate` is accepted). FEAT-773's `POST /{provider}/start` always uses the **web** channel today
(it never passes `channel`/`principal`), so a CLI start would fail the web origin check — this task lets the body pick
`channel: "cli"`. `/api/v1/connections/me` must be registered before `/{provider}` or aiohttp treats `me` as a provider.

---

## Scope

- `handlers/connections.py`: `_route_suffix()` helper; `GET /me` → `whoami`; `POST /{provider}/token` →
  `pull_access_token` (409 + `AuthRequiredPayload` body on `NotConnected`); `POST /{provider}/complete` →
  `complete_connect(channel="cli")`; `POST /{provider}/start` accepts `channel` ∈ {web, cli} (cli builds a `Principal`);
  `device/start` / `device/poll` suffixes return 404 here (TASK-4971 wires them).
- `manager/manager.py`: register `/me` (before `/{provider}`) and the four POST sub-routes.
- Tests.

**NOT in scope**: device endpoint behaviour (TASK-4971); service logic (TASK-4969); PBAC policy content.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/connections.py` | MODIFY | new routes + CLI start |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | route registration |
| `packages/ai-parrot-server/tests/unit/test_connections_cli_routes.py` | CREATE | handler + ordering tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified against `dev` @ `8ab2f60782` (2026-10-31), after FEAT-773 merged. The spec's §6 entries marked
> **planned** are re-anchored to code here; line numbers below are the current ones.

### Verified Imports
```python
from aiohttp import web                                               # connections.py:7
from parrot.auth.oauth2.service import IntegrationsService            # connections.py:12
from parrot.auth.oauth2.models import NotConnected                    # TASK-4969
from parrot.auth.principal import Principal                           # principal.py:18
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/connections.py (136 lines)
@is_authenticated() @user_session()
class ConnectionsHandler(BaseView):                           # :19
    async def _get_user_id(self) -> str | None                # :22 (request["user_id"] → session user_id/id; never username)
    def _is_start_route(self) -> bool                         # :41 — True only for /{provider}/start
    async def get(self) -> web.Response                       # :46 — list (no provider) or status(provider)
    async def post(self) -> web.Response                      # :74 — parses JSON body; start_connect(user_id, provider, body["return_origin"], scopes=, request=)
    async def delete(self) -> web.Response                    # :112
# error mapping convention: PermissionError → 403 {"error": "forbidden"}; ValueError → 400 {"error": str}; else 500 "internal_error"
# packages/ai-parrot-server/src/parrot/manager/manager.py — inside BotManager.setup() (:2331)
        router.add_view("/api/v1/connections", ConnectionsHandler)                 # :2488
        router.add_view("/api/v1/connections/{provider}", ConnectionsHandler)      # :2489
        router.add_view("/api/v1/connections/{provider}/start", ConnectionsHandler) # :2490
# IntegrationsService (TASK-4969): whoami(user_id, request=None) -> WhoAmI ; pull_access_token(user_id, provider_id, request=None)
#   -> PulledToken | raises NotConnected(payload) ; complete_connect(user_id, provider_id, *, code, state, channel, request=None)
#   start_connect(user_id, provider_id, return_origin=None, *, channel="web", principal=None, scopes=None, request=None)  # service.py:288
```

### Does NOT Exist
- ~~`/api/v1/connections/me`, `/{provider}/token`, `/{provider}/complete`, `/{provider}/device/*` routes~~ — added here (device behaviour in TASK-4971).
- ~~`ConnectionsHandler._route_suffix`~~ — added here.
- ~~a `channel` field honoured by today's `POST /start`~~ — `post()` never passes `channel`, so every start is web (`connections.py:96-102`).
- ~~a principal guard that lets the body choose `user_id`~~ — the user id comes only from `_get_user_id()`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/connections.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/manager/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/test_connections_cli_routes.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/connections.py#ConnectionsHandler"
  ]
}
```

---

## Implementation Notes

- Keep `_is_start_route` and its existing tests (`test_provider_named_start_is_not_mistaken_for_start_route`) green:
  `_route_suffix()` returns the path tail after `/{provider}/` (e.g. `token`, `complete`, `device/start`) and `""`
  otherwise, so a provider literally named `start` still means "status".
- `GET /me`: the `/api/v1/connections/me` route has no `provider` match; detect it by path suffix `/connections/me`.
- `/token` response: `PulledToken.model_dump(mode="json")`; `NotConnected` → 409 with
  `exc.payload.model_dump(mode="json", exclude_none=True)`.
- `/complete` body `{code, state}` — both required strings → else 400.
- CLI start: `channel = body.get("channel", "web")`; anything outside {"web", "cli"} → 400. For cli build
  `Principal(user_id=user_id, channel="cli", channel_user_id=user_id)` and call
  `start_connect(user_id, provider, None, channel="cli", principal=principal, scopes=body.get("scopes"), request=self.request)`.
- Never log bodies of `/token` or `/complete` responses (token material, codes).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. This is NOT the full
> implementation: branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add `_route_suffix()` and the `/me` branch in `get()` — *why*: whoami backs the CLI principal (M2).
2. Rewrite `post()` as a suffix dispatch — *why*: one view serves start/token/complete/device (pattern: integrations.py).
3. Register the routes in manager.py with `/me` first — *why*: aiohttp resolves in registration order (spec §7).
4. Write the tests and run the validation commands, including FEAT-773's handler tests.

### `packages/ai-parrot-server/src/parrot/handlers/connections.py` (MODIFY — helper)
```python
# occurrences: 1 (verified: grep -c '    def _is_start_route(self) -> bool:' handlers/connections.py)
# BEFORE — insert above `    def _is_start_route(self) -> bool:` (verified: connections.py:41); add imports
# `from parrot.auth.oauth2.models import NotConnected` and `from parrot.auth.principal import Principal` after :12.
    def _route_suffix(self) -> str:
        """Tail after ``/{provider}/`` (``token``, ``complete``, ``device/start`` ...), or ``""``."""
        provider = self.request.match_info.get("provider")
        if not provider:
            return ""
        marker = f"/{provider}/"
        path = self.request.path.rstrip("/")
        return path.split(marker, 1)[1] if marker in path else ""

    def _is_me_route(self) -> bool:
        """True for ``GET /api/v1/connections/me``."""
        return not self.request.match_info.get("provider") and self.request.path.rstrip("/").endswith("/connections/me")
```

### `packages/ai-parrot-server/src/parrot/handlers/connections.py` (MODIFY — get / post)
```python
# In get() (verified: connections.py:46) — AFTER the `if not user_id: return 401` block (:54-55), before `provider = ...`:
        if self._is_me_route():
            try:
                who = await IntegrationsService().whoami(user_id, request=self.request)
            except Exception:  # noqa: BLE001
                logger.exception("Error resolving whoami for user=%s", user_id)
                return web.json_response({"error": "internal_error"}, status=500)
            return web.json_response(who.model_dump(mode="json"))

# post() (verified: connections.py:74-110) — REPLACE the block from `provider = self.request.match_info["provider"]`
# to the final `return web.json_response(response.model_dump(mode="json"))` with:
        provider = self.request.match_info["provider"]
        suffix = self._route_suffix()
        service = IntegrationsService()
        try:
            if suffix == "token":
                pulled = await service.pull_access_token(user_id, provider, request=self.request)
                return web.json_response(pulled.model_dump(mode="json"))
            if suffix == "complete":
                # FILL IN: require str code/state in body (else 400); complete_connect(..., channel="cli", request=self.request)
                #          → descriptor.model_dump(mode="json") — AC-9
                raise NotImplementedError
            if suffix in ("device/start", "device/poll"):
                return web.json_response({"error": "not found"}, status=404)  # TASK-4971 wires these
            channel = body.get("channel", "web")
            # FILL IN: channel not in {"web", "cli"} → 400; cli → Principal(user_id, channel="cli", channel_user_id=user_id)
            #          and start_connect(user_id, provider, None, channel="cli", principal=..., scopes=..., request=...);
            #          web → today's call unchanged (return_origin from body)
            raise NotImplementedError
        except NotConnected as exc:
            return web.json_response(exc.payload.model_dump(mode="json", exclude_none=True), status=409)
        except PermissionError:
            return web.json_response({"error": "forbidden"}, status=403)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except Exception:  # noqa: BLE001
            logger.exception("Error handling connections POST for user=%s provider=%s", user_id, provider)
            return web.json_response({"error": "internal_error"}, status=500)
```

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'router.add_view("/api/v1/connections", ConnectionsHandler)' manager/manager.py)
# AFTER — insert below `        router.add_view("/api/v1/connections", ConnectionsHandler)` (verified: manager.py:2488)
        router.add_view("/api/v1/connections/me", ConnectionsHandler)  # FEAT-774: BEFORE /{provider} (route order)

# occurrences: 1 (verified: grep -c 'router.add_view("/api/v1/connections/{provider}/start", ConnectionsHandler)' manager/manager.py)
# AFTER — insert below `        router.add_view("/api/v1/connections/{provider}/start", ConnectionsHandler)` (verified: manager.py:2490)
        router.add_view("/api/v1/connections/{provider}/token", ConnectionsHandler)
        router.add_view("/api/v1/connections/{provider}/complete", ConnectionsHandler)
        router.add_view("/api/v1/connections/{provider}/device/start", ConnectionsHandler)
        router.add_view("/api/v1/connections/{provider}/device/poll", ConnectionsHandler)
```

### `packages/ai-parrot-server/tests/unit/test_connections_cli_routes.py` (CREATE)
```python
"""CLI routes on ConnectionsHandler (FEAT-774 M3)."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from parrot.handlers.connections import ConnectionsHandler

# FILL IN: reuse the `_Request` fake pattern from tests/unit/test_connections_handler.py:13-44 (copy, do not import)


def test_whoami_route_ordering():
    # FILL IN: read parrot/manager/manager.py source; index of '"/api/v1/connections/me"' < index of
    #          '"/api/v1/connections/{provider}"'; and an aiohttp UrlDispatcher built in that order resolves /me to the /me resource
    ...

async def test_token_route_success_and_not_connected_409(monkeypatch):
    # FILL IN: pull_access_token → PulledToken → 200 keys ⊆ {provider, access_token, expires_at, scopes, account_id};
    #          raises NotConnected(payload) → 409 body validates as AuthRequiredPayload
    ...

async def test_token_route_pbac_denied_403(monkeypatch):
    ...

async def test_complete_route_and_cli_start(monkeypatch):
    # FILL IN: /complete without code → 400; with code/state → complete_connect(channel="cli"); POST /start {"channel": "cli"}
    #          → start_connect called with channel="cli" and a Principal; {"channel": "telegram"} → 400
    ...
```

### FILL IN checklist
- [ ] `post()` `/complete` branch — body validation + complete_connect; bounded by AC-9
- [ ] `post()` start branch — channel allow-list + CLI principal; bounded by S10/S12 (identity only from the session)
- [ ] tests — fake request pattern, route ordering, 409/403/400 mapping

---

## Acceptance Criteria

- [ ] `GET /api/v1/connections/me` returns `WhoAmI` and resolves before `/{provider}` (spec §7)
- [ ] `POST /{provider}/token` → 200 access-token-only body, 403 on PBAC denial, 409 + `AuthRequiredPayload` when not connected (AC-5)
- [ ] `POST /{provider}/complete` validates `{code, state}` and completes for channel `cli` (AC-9)
- [ ] `POST /{provider}/start` with `{"channel": "cli"}` starts a CLI connect; unknown channels → 400
- [ ] FEAT-773 `test_connections_handler.py` stays green; `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_connections_cli_routes.py -q`
- `pytest packages/ai-parrot-server/tests/unit/test_connections_handler.py -q`

---

## Test Specification

```python
# see packages/ai-parrot-server/tests/unit/test_connections_cli_routes.py block in the blueprint
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug connections-cli-local-mcp --feature-id FEAT-774 --spec sdd/specs/connections-cli-local-mcp.spec.md --index sdd/tasks/index/connections-cli-local-mcp.json`)
2. **Read the spec** at the path listed above for full context (§2 Overview, §3 for this module, §7 gotchas)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/connections-cli-local-mcp.json`
4. **Verify the Codebase Contract** — before writing ANY code re-run each `grep -c` in the blueprint;
   if a count differs, fix the anchor in this file first. Never use anything under "Does NOT Exist".
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker,
   never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src` (plus one entry per other
   changed package, e.g. `packages/ai-parrot-server/src`) and `ruff check` the touched files
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> connections-cli-local-mcp verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.
