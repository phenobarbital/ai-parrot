# TASK-5041: ChannelLinksHandler — read-only preview + explicit confirm of a Slack link

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5034, TASK-5035, TASK-5036, TASK-5039, TASK-5040
**Assigned-to**: unassigned

---

## Context

Spec §2 "Slack linking (M2, D2)" and §3 Module 2: the admin UI page `/account/link?token=N` first calls a read-only
preview, and only an explicit Confirm click consumes the nonce and claims the Slack identity for the **session's**
Navigator user. This task adds the server handler, its two routes, and the app-level wiring the Slack commands (TASK-5044)
read: `app["channel_link_issuer"]` and `app["connection_authorizer"]`. AC-5, AC-14 (wiring), D5.

---

## Scope

- Create `packages/ai-parrot-server/src/parrot/handlers/channel_links.py` with `ChannelLinksHandler(BaseView)`
  (`@is_authenticated()` + `@user_session()`):
  - `GET /api/v1/channel-links/{nonce}` → 401 without session; 503 when `app["channel_link_issuer"]` absent;
    `issuer.peek(nonce)` `None` → 410; else `ChannelLinkPreview(channel, channel_user_id, team_id, nav_user_id=<session id>)`
    JSON with `Cache-Control: no-store`. No identity write, no consumption.
  - `POST /api/v1/channel-links/{nonce}/confirm` → 401 without session; 403 when the session id is not numeric;
    400 unless the JSON body is exactly `{"confirm": true}` (any other key — e.g. `nav_user_id`, `user_id`,
    `channel_user_id` — is an identity override → 400) **before** consuming; 503 without issuer or `authdb`;
    `issuer.consume(nonce)` `None` → 410; reject a claim whose channel is not `"slack"` or whose `channel_user_id` is not
    `"{team_id}:{slack_user_id}"` consistent with `extra` → 400; then
    `IdentityMappingService(app["authdb"]).claim_channel_identity(nav_user_id=<session id>, auth_provider="slack",
    provider_user_id=claim.channel_user_id, auth_data={"team_id", "slack_user_id"})`:
    `"conflict"` → 409 `{"error": "already_linked"}` (no owner details); `"claimed"`/`"already_owned"` → 200
    `{"channel": "slack", "linked": true}`; DB exception → 500, never success, nonce stays spent.
- In `manager.py`:
  - `_setup_channel_links(self, app)` (sync), called right after `self._setup_connection_push(self.app)` (added by TASK-5040):
    when `CONNECTIONS_LINK_BASE_URL` is set, `app["channel_link_issuer"] = ChannelLinkIssuer(app["redis"], base_url=...,
    ttl_seconds=CHANNEL_LINK_TTL_SECONDS)`; otherwise log one warning (D5: not configured). Also
    `app["connection_authorizer"] = NavigatorConnectionAuthorizer(...)` per TASK-5039's constructor (FILL IN).
  - routes: `/api/v1/channel-links/{nonce}` and `/api/v1/channel-links/{nonce}/confirm` → `ChannelLinksHandler`, after the
    `/api/v1/connections/{provider}/start` route.
- Tests.

**NOT in scope**: the UI page (TASK-5056), Slack `/login` (TASK-5044), the claim SQL (TASK-5036), the PDP adapter itself (TASK-5039).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/channel_links.py` | CREATE | `ChannelLinksHandler` (preview + confirm) |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `_setup_channel_links`, two routes |
| `packages/ai-parrot-server/tests/unit/test_channel_links_handler.py` | CREATE | Handler tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web
from navigator.views import BaseView  # type: ignore[import]                          # handlers/connections.py:8
from navigator_auth.decorators import is_authenticated, user_session  # type: ignore[import]   # handlers/connections.py:9
from navigator_session import get_session  # type: ignore[import]                     # handlers/connections.py:10
from parrot.auth.channel_link import ChannelLinkIssuer, ChannelLinkClaim               # created by TASK-5034
from parrot.auth.oauth2.models import ChannelLinkPreview                              # created by TASK-5035 (fields: channel, channel_user_id, team_id, nav_user_id)
from parrot.services.identity_mapping import IdentityMappingService                   # verified: services/identity_mapping.py:136; claim_channel_identity + ClaimResult by TASK-5036
from parrot.services.connection_authorization import NavigatorConnectionAuthorizer    # created by TASK-5039
from parrot.conf import CONNECTIONS_LINK_BASE_URL, CHANNEL_LINK_TTL_SECONDS            # created by TASK-5034 (conf.py)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/connections.py:22-39 — _get_user_id(): request.get("user_id") → session user_id/id → str|None
# packages/ai-parrot-server/src/parrot/manager/manager.py
#   app["redis"] = aioredis.from_url(REDIS_URL, decode_responses=True)  — set by _register_shared_redis() during setup (:1732, called :2393)
#   self._setup_connection_push(self.app)                                — inserted by TASK-5040 just above :2400
#   router.add_view("/api/v1/connections/{provider}/start", ConnectionsHandler)   # :2490 (anchor, 1 occurrence)
#   app.get("authdb") — navigator-auth pool, available at request time (used at manager.py:2851)
# IdentityMappingService(db_pool) :156; claim_channel_identity(*, nav_user_id, auth_provider, provider_user_id, auth_data, display_name=None, email=None) -> ClaimResult(status) (TASK-5036)
# ChannelLinkIssuer.peek(nonce) / consume(nonce) -> Optional[ChannelLinkClaim]; ChannelLinkClaim(channel, channel_user_id, extra, issued_at) (TASK-5034)
```

### Does NOT Exist
- ~~`parrot.handlers.channel_links`~~, ~~`app["channel_link_issuer"]`~~, ~~`app["connection_authorizer"]`~~ — created here.
- ~~Consuming on GET~~ — preview must never consume (AC-5).
- ~~A principal from the body / query / nonce~~ — session only (spec D2).
- ~~Ownership transfer endpoint~~ — out of v1; 409 directs to an administrator.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/channel_links.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/src/parrot/manager/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/unit/test_channel_links_handler.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/connections.py#ConnectionsHandler._get_user_id",
    "sym:packages/ai-parrot-server/src/parrot/services/identity_mapping.py#IdentityMappingService"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Validation order on confirm is security-relevant: session → numeric id → body `{confirm: true}` → consume → claim.
  The nonce is consumed only after all request-side checks pass.
- Never log the nonce or the Slack ids at info level; never echo another owner on 409.
- `manager.py` edits stay inside the `setup()` call site, one new method and the route block.

---

## Implementation Blueprint

### Steps (in order)
1. Create the handler module.
2. Add `_setup_channel_links` and call it after `_setup_connection_push` — *why*: Slack startup reads these app keys.
3. Register the two routes after `/api/v1/connections/{provider}/start`.
4. Write tests; run them.

### `packages/ai-parrot-server/src/parrot/handlers/channel_links.py` (CREATE)
```python
"""Channel-link preview and explicit confirm (FEAT-777 M2, D2)."""

from __future__ import annotations

import logging
from typing import Any, Dict

from aiohttp import web
from navigator.views import BaseView  # type: ignore[import]
from navigator_auth.decorators import is_authenticated, user_session  # type: ignore[import]
from navigator_session import get_session  # type: ignore[import]

from parrot.auth.oauth2.models import ChannelLinkPreview
from parrot.services.identity_mapping import IdentityMappingService

logger = logging.getLogger(__name__)


@is_authenticated()
@user_session()
class ChannelLinksHandler(BaseView):
    """``GET /api/v1/channel-links/{nonce}`` preview; ``POST …/{nonce}/confirm`` claim."""

    async def _get_user_id(self) -> str | None:
        """Session Navigator id only (same rules as ``ConnectionsHandler._get_user_id``)."""
        # FILL IN: copy handlers/connections.py:22-39 verbatim
        ...

    def _issuer(self) -> Any:
        return self.request.app.get("channel_link_issuer")

    async def get(self) -> web.Response:
        """Read-only preview; ``Cache-Control: no-store``; 410 when the claim is absent."""
        user_id = await self._get_user_id()
        if not user_id:
            return web.json_response({"error": "Authenticated user not identified."}, status=401)
        issuer = self._issuer()
        if issuer is None:
            return web.json_response({"error": "account linking is not configured"}, status=503)
        claim = await issuer.peek(self.request.match_info.get("nonce", ""))
        if claim is None:
            return web.json_response({"error": "link expired"}, status=410, headers={"Cache-Control": "no-store"})
        # FILL IN: team_id = claim.extra.get("team_id") or claim.channel_user_id.split(":", 1)[0];
        #   ChannelLinkPreview(channel=..., channel_user_id=..., team_id=..., nav_user_id=user_id) — bounded by AC-5
        ...

    async def post(self) -> web.Response:
        """Explicit confirm; order: session → numeric id → body → consume → exclusive claim."""
        if not self.request.path.rstrip("/").endswith("/confirm"):
            return web.json_response({"error": "method not allowed"}, status=405)
        # FILL IN: implement the Scope's confirm sequence and status codes exactly (401/403/400/503/410/400/409/200/500);
        #   body must be exactly {"confirm": true}; claim via IdentityMappingService(self.request.app["authdb"]) — bounded by AC-5
        ...

    @staticmethod
    def _valid_slack_claim(claim: Any) -> bool:
        """``channel == "slack"`` and ``channel_user_id == f"{team_id}:{slack_user_id}"`` with both parts non-empty."""
        # FILL IN
        ...
```

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY — call site)
```python
# occurrences: 1 (verify after TASK-5040: grep -c '        self._setup_connection_push(self.app)' packages/ai-parrot-server/src/parrot/manager/manager.py)
# AFTER — insert below `        self._setup_connection_push(self.app)` (added by TASK-5040 above `self._register_descriptor_oauth2_providers(self.app)`)
        # FEAT-777 M2: Slack account-link issuer + request-independent connection authorizer.
        self._setup_channel_links(self.app)
```

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY — method)
```python
# occurrences: 1 (verified: grep -c '    def _register_descriptor_oauth2_providers(self, app: web.Application) -> None:' packages/ai-parrot-server/src/parrot/manager/manager.py)
# BEFORE — insert above that def (verified: manager.py:2806; TASK-5040 inserts _setup_connection_push just above it too)
    def _setup_channel_links(self, app: web.Application) -> None:
        """Wire ``app["channel_link_issuer"]`` (when configured, D5) and ``app["connection_authorizer"]``."""
        from parrot.conf import CHANNEL_LINK_TTL_SECONDS, CONNECTIONS_LINK_BASE_URL

        if app.get("channel_link_issuer") is None:
            if CONNECTIONS_LINK_BASE_URL:
                from parrot.auth.channel_link import ChannelLinkIssuer

                app["channel_link_issuer"] = ChannelLinkIssuer(
                    app["redis"], base_url=CONNECTIONS_LINK_BASE_URL, ttl_seconds=CHANNEL_LINK_TTL_SECONDS
                )
            else:
                self.logger.warning("CONNECTIONS_LINK_BASE_URL is not set — Slack account linking is disabled (D5)")
        if app.get("connection_authorizer") is None:
            # FILL IN: build NavigatorConnectionAuthorizer exactly as TASK-5039 defines its constructor (do not invent
            #   arguments); failures are logged and leave the key unset so Slack commands fail closed — bounded by AC-14
            ...
```

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY — routes)
```python
# occurrences: 1 (verified: grep -c '        router.add_view("/api/v1/connections/{provider}/start", ConnectionsHandler)' packages/ai-parrot-server/src/parrot/manager/manager.py)
# AFTER — insert below that line (verified: manager.py:2490)
        # FEAT-777 M2: Slack account-link preview + explicit confirm (session principal only).
        router.add_view("/api/v1/channel-links/{nonce}", ChannelLinksHandler)
        router.add_view("/api/v1/channel-links/{nonce}/confirm", ChannelLinksHandler)
```
and add `from ..handlers.channel_links import ChannelLinksHandler` next to `from ..handlers.connections import ConnectionsHandler` (manager.py:41).

### `packages/ai-parrot-server/tests/unit/test_channel_links_handler.py` (CREATE)
```python
"""Tests for ChannelLinksHandler (FEAT-777 M2)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.handlers.channel_links import ChannelLinksHandler


def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


# FILL IN: _Request double (match_info={"nonce": ...}, path, app dict, session, async json()) following
#   packages/ai-parrot-server/tests/unit/test_connections_handler.py:13-42


@pytest.mark.asyncio
async def test_channel_link_preview_read_only() -> None:
    """Preview shows session account + Slack ids; repeated GET never consumes, never writes identity."""
    # FILL IN: issuer.peek called twice, consume never; IdentityMappingService never constructed; no-store header
    ...


@pytest.mark.asyncio
async def test_channel_link_confirm_uses_session_principal(monkeypatch) -> None:
    """confirm required before consume; body identity override → 400 without consume; 410 spent; 403 non-numeric session."""
    # FILL IN
    ...


@pytest.mark.asyncio
async def test_channel_link_confirm_conflict_and_db_failure(monkeypatch) -> None:
    """claim conflict → 409 with no owner details; claim raising → 500 and never linked:true."""
    # FILL IN
    ...


@pytest.mark.asyncio
async def test_channel_link_rejects_non_slack_claim(monkeypatch) -> None:
    # FILL IN: consumed claim with channel="telegram" or malformed "T:U" → 400, claim not called
    ...
```

### FILL IN checklist
- [ ] `_get_user_id` copy; preview build — bounded by AC-5.
- [ ] Confirm sequence and status codes — bounded by AC-5 and the spec's `ChannelLinksHandler.post` docstring.
- [ ] `_valid_slack_claim` — bounded by AC-6 ("T:U" everywhere).
- [ ] Authorizer construction — bounded by TASK-5039's signature, AC-14 (fail closed when absent).
- [ ] Four tests — bounded by spec §4 `test_channel_link_preview_read_only`, `test_channel_link_confirm_uses_session_principal`, `test_channel_link_db_failure`.

---

## Acceptance Criteria

- [ ] AC-5: GET never consumes or writes; POST requires session, numeric id, exactly `{"confirm": true}`, then consumes once and
  claims exclusively; 409 on conflict without owner details; 410 on spent/expired; DB failure never reports success.
- [ ] D5: without `CONNECTIONS_LINK_BASE_URL`, both routes return 503 and one warning is logged at setup.
- [ ] `app["connection_authorizer"]` is set when the PDP is available, unset (fail closed) otherwise.
- [ ] `ruff check` clean on touched files; existing manager-dependent tests pass.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_channel_links_handler.py -q`
- `pytest packages/ai-parrot-server/tests/unit/test_connections_handler.py -q`

---

## Test Specification

See the CREATE test block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** (§2 "Slack linking (M2, D2)", §3 Module 2 `ChannelLinksHandler`, AC-5, AC-14, §8 D5)
3. **Check dependencies** — TASK-5034, TASK-5035, TASK-5036, TASK-5039, TASK-5040 must be `"done"`
4. **Verify the Codebase Contract** before writing code (re-read TASK-5039's final constructor)
5. **Update status** → `"in-progress"` and commit only the index file
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit the code** — only the listed files
9. **Close the task** with `scripts/sdd/close_task.sh TASK-5041 connections-web-slack verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seats codex terra/sol/luna + native sonnet
**Date**: 2026-10-31
**Notes**: Implemented per task; merged and merge-tier validated (only red: 3 failures that also fail on origin/dev: test_o365_refresh x2, slack test_manager_payload_drives_identity_and_dm).

**Deviations from spec**: none | describe if any
