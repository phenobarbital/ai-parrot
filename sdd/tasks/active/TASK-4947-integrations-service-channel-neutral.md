# TASK-4947: Channel-neutral IntegrationsService + generic callback persistence + agent-scoped handler compatibility

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4946, TASK-4954
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (G2, G7, S4, S5, U2, AC-3, AC-8, AC-19). `IntegrationsService` hard-codes `channel = _WEB_CHANNEL`,
reads per-agent enablement rows and has no PBAC on connect/disconnect. It becomes principal-level: `channel` is a
parameter, `list_for_principal` lists every provider for the principal, connect/disconnect evaluate PBAC
`integration:connect` / `integration:disconnect` with the requested scopes (fail closed without a PDP),
`confirm_enable` is removed, and token status is read from the durable owner for **every** provider. The generic
callback persists a `users_integrations` row for every channel (not only web) and maps
`CredentialPersistenceError` to the error page. The agent-scoped handler keeps its routes; `/enable` becomes a
compatibility no-op (S5).

---

## Scope

- `service.py`: `list_for_principal(user_id, request=None)`; `list_for_user(user_id, agent_id, request=None)` = alias;
  `start_connect(user_id, provider_id, return_origin=None, *, channel="web", principal=None, scopes=None, request=None,
  extra_state=None)` (PBAC `integration:connect` with ctx provider + scopes; origin allowlist only for web; build a web
  `Principal` when none is given); `status(user_id, provider_id, request=None)`; `disconnect(user_id, provider_id,
  request=None)` (PBAC `integration:disconnect` → `manager.revoke(channel="web", user_id)` → `delete_users_integration`);
  `persist_credential(user_id, provider_id, token_set, *, channel, canonical_identity=None)` merging `channels`,
  bumping `updated_at`, keeping the first `connected_at`; remove `confirm_enable`, `_IDENTITY_OWNED_PROVIDERS` and every
  `user_agent_toolkits` call; `_check_pbac(request, action, provider_id=None, scopes=None)`.
- `oauth2_routes.py`: persist for every channel using `state_payload["nav_user_id"]`; `CredentialPersistenceError`
  → error page (500), web branch keeps the postMessage template.
- `handlers/integrations.py`: `_post_connect` → new `start_connect` signature; `_post_enable` → returns
  `svc.status(...)` without writing; `delete` → `svc.disconnect(user_id, provider, request=self.request)`.
- Tests: `test_service_pbac_on_connect_and_disconnect`, `test_service_list_for_principal_cross_channel`,
  `test_descriptor_updated_at_bumps_on_reconnect`, `test_confirm_enable_removed_enable_route_noop`; update the four existing service/status test files.

**NOT in scope**: `/api/v1/connections` handler and hydration (TASK-4948); deleting the toolkit repository functions/models (TASK-4949); Jira alias route (TASK-4958).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/service.py` | MODIFY | channel-neutral service |
| `packages/ai-parrot/src/parrot/auth/oauth2_routes.py` | MODIFY | persist every channel; durable failure page |
| `packages/ai-parrot-server/src/parrot/handlers/integrations.py` | MODIFY | new signatures; /enable no-op |
| `packages/ai-parrot/src/parrot/auth/routes.py` | MODIFY | one call site: persist_credential new signature (rest is TASK-4958) |
| `tests/unit/integrations/oauth2/test_service.py` | MODIFY | new API |
| `packages/ai-parrot/tests/unit/test_oauth2_service_token_status.py` | MODIFY | status via durable owner for all |
| `packages/ai-parrot/tests/auth/test_integrations_status.py` | MODIFY | drop user_agent_toolkit mocks |
| `tests/unit/integrations/oauth2/test_handler.py` | MODIFY | enable no-op + new connect signature |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from parrot.auth.principal import Principal                                     # TASK-4937
from parrot.auth.oauth2_base import CredentialPersistenceError                  # TASK-4940
from parrot.auth.oauth2.persistence import (delete_users_integration, get_users_integration,
                                            list_users_integrations, upsert_users_integration)   # :89, :67, TASK-4946, :42
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry                  # verified: registry.py:69
from parrot.auth.oauth2 import _WEB_CHANNEL                                     # verified: service.py:26
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/oauth2/service.py
_IDENTITY_OWNED_PROVIDERS = frozenset({"jira"})                                    # :53 (remove)
class IntegrationsService:                                                         # :74
    async def list_for_user(self, user_id, agent_id, request=None)                 # :90  PBAC integration:list (:115); list_user_agent_toolkits (:127)
    def _vault_sync(self, request) (:155) / _identity_store(self, request) (:177)
    async def _identity_token_status(self, user_id, provider_id, request) -> str   # :202
    async def _token_status(self, user_id, provider_id, request) -> str            # :250 (:267 identity-owned branch)
    async def start_connect(self, user_id, agent_id, provider_id, return_origin)   # :291 anchor
    async def confirm_enable(self, user_id, agent_id, provider_id)                 # :346 anchor (remove)
    async def disconnect(self, user_id, agent_id, provider_id)                     # :406 anchor (agent_id unused)
    async def persist_credential(self, user_id, provider_id, token_set)            # :440 anchor; channel=_WEB_CHANNEL
    async def _check_pbac(self, request, action, provider_id=None) -> bool         # :490 fail closed; ctx {"action","provider"}; abac.is_allowed
# packages/ai-parrot/src/parrot/auth/oauth2_routes.py
async def _handle_web_callback(request, provider_id, token_set, state_payload)     # :123; svc.persist_credential(user_id, provider, token_set) :173 anchor
def make_oauth2_callback(provider_id)                                              # :200; `channel = state_payload.get("channel", "web")` :264 anchor
# packages/ai-parrot/src/parrot/auth/routes.py
        await svc.persist_credential(user_id, provider, token_set)                 # :141 (legacy Jira web callback)
# packages/ai-parrot-server/src/parrot/handlers/integrations.py
class IntegrationsHandler(BaseView)                                                # :34 (@is_authenticated @user_session)
    async def _get_user_id(self) -> str | None                                     # :43
    async def _post_connect(self) -> web.Response                                  # :109 anchor; svc.start_connect(user_id, agent_id, provider, return_origin) :152
    async def _post_enable(self) -> web.Response                                   # :163; `descriptor = await svc.confirm_enable(user_id, agent_id, provider)` :178 anchor
    async def delete(self) -> web.Response                                         # :193; svc.disconnect(user_id, agent_id, provider)
```

### Does NOT Exist
- ~~`IntegrationsService.list_for_principal` / `status`~~ — new here.
- ~~`IntegrationsService.confirm_enable`~~ — removed here (hard cut, spec §7).
- ~~a parrot-side PBAC policy store / tenant allowlist~~ — policies live in the navigator-auth PDP only (§8).
- ~~`start_connect(channel=…)` today~~ — channel is hard-coded `_WEB_CHANNEL` (service.py:328-338).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/service.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2_routes.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/integrations.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/auth/routes.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/unit/integrations/oauth2/test_service.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/test_oauth2_service_token_status.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/auth/test_integrations_status.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/unit/integrations/oauth2/test_handler.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/service.py#IntegrationsService",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/service.py#IntegrationsService._check_pbac",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_routes.py#make_oauth2_callback",
    "sym:packages/ai-parrot-server/src/parrot/handlers/integrations.py#IntegrationsHandler"
  ]
}
```

---

## Implementation Notes

- PBAC: `ctx = {"action": action, "provider": provider_id, "scopes": scopes or provider.default_scopes}`; `request=None`
  → deny (unchanged rule). Connect denial → `PermissionError` (handler maps to 403) and **no** OAuth state written.
- Status for every provider: Identity Vault when the server store is available (`_identity_token_status`), else
  `manager.is_connected("web", user_id)`; keep the existing helpers, drop only the `_IDENTITY_OWNED_PROVIDERS` gate.
- `persist_credential`: read the existing row → merge `channels` (set union, stable order), `connected_at` from the
  old row when the account is unchanged, else now (replace-on-reconnect), `updated_at=now` always.
- Callback: `user_id = state_payload.get("nav_user_id")`; the manager already rejected payloads without it (TASK-4940).

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Rework the service (block A) — *why*: G2/G7/S4/U2.
2. Rework the callback persistence (block B) — *why*: rows for every channel; S2 error page.
3. Adapt the agent-scoped handler (block C) — *why*: S5 compatibility while the UI still calls `/enable`.
4. Update the four existing test files + new tests.

### `packages/ai-parrot/src/parrot/auth/oauth2/service.py` (MODIFY)
```python
# occurrences: 1 each (verified: '_IDENTITY_OWNED_PROVIDERS = frozenset({"jira"})' :53, '    async def start_connect(' :291,
#   '    async def confirm_enable(' :346, '    async def disconnect(' :406, '    async def persist_credential(' :440)
# DELETE _IDENTITY_OWNED_PROVIDERS (:53) and confirm_enable (:346-404); drop the user_agent_toolkits imports (:34-42).
    async def list_for_principal(self, user_id: str, request: Any = None) -> List[IntegrationDescriptor]:
        """PBAC integration:list; one descriptor per registered provider (status/account/channels/updated_at)."""
        # FILL IN: reuse list_for_user's PBAC + per-provider loop, but rows = {r.provider: r for r in
        #          await list_users_integrations(user_id)}; no enabled_on_agent
        raise NotImplementedError

    async def list_for_user(self, user_id: str, agent_id: str, request: Any = None) -> List[IntegrationDescriptor]:
        """Alias kept for the agent-scoped routes (agent_id ignored, U2)."""
        return await self.list_for_principal(user_id, request=request)

    async def start_connect(self, user_id: str, provider_id: str, return_origin: Optional[str] = None, *,
                            channel: str = _WEB_CHANNEL, principal: Optional[Principal] = None,
                            scopes: Optional[List[str]] = None, request: Any = None,
                            extra_state: Optional[Dict[str, Any]] = None) -> ConnectInitResponse:
        """PBAC integration:connect (fail closed) → origin check (web only) → create_authorization_url(principal=)."""
        # FILL IN: provider lookup (ValueError unknown); if not await self._check_pbac(request, "integration:connect",
        #          provider_id, scopes) → raise PermissionError; web → origin allowlist; principal default
        #          Principal(user_id=user_id, channel=channel, channel_user_id=user_id) for web, else required (ValueError);
        #          state = {"channel", "provider_id", "return_origin", **(extra_state or {})};
        #          auth_url, nonce = await provider.manager.create_authorization_url(channel, user_id, state, principal=principal)
        raise NotImplementedError

    async def status(self, user_id: str, provider_id: str, request: Any = None) -> IntegrationDescriptor:
        # FILL IN: single-provider variant of list_for_principal (no PBAC list check needed beyond integration:list)
        raise NotImplementedError

    async def disconnect(self, user_id: str, provider_id: str, request: Any = None) -> DisconnectResponse:
        # FILL IN: PBAC integration:disconnect → PermissionError; await provider.manager.revoke(_WEB_CHANNEL, user_id);
        #          await delete_users_integration(user_id, provider_id)
        raise NotImplementedError

    async def persist_credential(self, user_id: str, provider_id: str, token_set: Any, *, channel: str,
                                 canonical_identity: Optional[str] = None) -> UsersIntegrationRow:
        # FILL IN: merge with the existing row per Implementation Notes; status="active"; updated_at=now
        raise NotImplementedError
# _check_pbac: add `scopes: Optional[List[str]] = None` param and put it in ctx when given.
```

### `packages/ai-parrot/src/parrot/auth/oauth2_routes.py` (MODIFY)
```python
# occurrences: 1 (verified: '        await svc.persist_credential(user_id, provider, token_set)' :173)
#   → svc.persist_credential(nav_user_id, provider, token_set, channel="web",
#                            canonical_identity=state_payload.get("canonical_identity"))  (nav_user_id from state)
# occurrences: 1 (verified: '        channel = state_payload.get("channel", "web")' :264)
# REPLACE the non-web tail (:264-280) WITH:
        channel = state_payload.get("channel", "web")
        if channel == "web":
            return await _handle_web_callback(request, provider_id, token_set, state_payload)
        try:
            await IntegrationsService().persist_credential(
                state_payload["nav_user_id"], provider_id, token_set, channel=channel,
                canonical_identity=state_payload.get("canonical_identity"))
        except Exception:  # noqa: BLE001 - metadata row only; the grant itself is already durable
            logger.exception("users_integrations upsert failed for provider=%s channel=%s", provider_id, channel)
        # KEEP the _GENERIC_SUCCESS_HTML response.
# AND in the handle_callback try-block (:225-236) add, before `except ValueError`:
#       except CredentialPersistenceError: → logger.error(...); return _error_response(
#           "Your account could not be saved. Please try again.", status=500)
```

### `packages/ai-parrot/src/parrot/auth/routes.py` (MODIFY — one line only)
```python
# occurrences: 1 (verified: grep -c '        await svc.persist_credential(user_id, provider, token_set)' routes.py → :141)
        await svc.persist_credential(state_payload.get("nav_user_id") or user_id, provider, token_set, channel="web")
```
**Why**: the legacy Jira web callback still calls the old signature; it is deleted by TASK-4958, but must not break before then.

### `packages/ai-parrot-server/src/parrot/handlers/integrations.py` (MODIFY)
```python
# occurrences: 1 (verified: '            descriptor = await svc.confirm_enable(user_id, agent_id, provider)' :178)
            descriptor = await svc.status(user_id, provider, request=self.request)   # S5 compatibility no-op
# occurrences: 1 (verified: '    async def _post_connect(self) -> web.Response:' :109)
#   :152 → resp = await svc.start_connect(user_id, provider, return_origin, request=self.request)
#          except PermissionError → 403 json {"error": "forbidden"}
# delete(): resp = await svc.disconnect(user_id, provider, request=self.request); PermissionError → 403
```

### FILL IN checklist
- [ ] `service.py` five methods + `_check_pbac(scopes)` + import cleanup; bounded by AC-3/AC-8/AC-19
- [ ] `oauth2_routes.py` web + non-web persistence and the `CredentialPersistenceError` branch; bounded by AC-5
- [ ] `handlers/integrations.py` three call sites + 403 mapping; update module docstring line 10
- [ ] four existing test files updated; four new tests in `tests/unit/integrations/oauth2/test_service.py`

---

## Acceptance Criteria

- [ ] AC-8: missing PDP or denial on connect/disconnect → no OAuth state, no deletion; scopes reach the PDP context
- [ ] AC-3: a row persisted with `channel='telegram'` is listed by `list_for_principal` for the same principal
- [ ] AC-19: `updated_at` bumps on first connect, replace-on-reconnect and status change; `connected_at` keeps first-connect time for the same account
- [ ] `/enable` returns the descriptor and writes nothing (S5); `confirm_enable` no longer exists
- [ ] A `CredentialPersistenceError` in the callback renders an error page and no success

---

## Validation Commands

- `pytest tests/unit/integrations/oauth2/test_service.py -q`
- `pytest tests/unit/integrations/oauth2/test_handler.py -q`
- `pytest packages/ai-parrot/tests/unit/test_oauth2_service_token_status.py -q`
- `pytest packages/ai-parrot/tests/auth/test_integrations_status.py -q`
- `pytest packages/ai-parrot-server/tests/unit/test_a2a_resume_trigger.py -q`

---

## Test Specification

```python
# tests/unit/integrations/oauth2/test_service.py (add)
@pytest.mark.asyncio
async def test_service_pbac_on_connect_and_disconnect(): ...       # abac None / deny → PermissionError, manager untouched
@pytest.mark.asyncio
async def test_service_list_for_principal_cross_channel(): ...     # persist_credential(channel="telegram") → listed, channels==["telegram"]
@pytest.mark.asyncio
async def test_descriptor_updated_at_bumps_on_reconnect(): ...     # same account → connected_at stable, updated_at moves
@pytest.mark.asyncio
async def test_confirm_enable_removed_enable_route_noop(): ...     # not hasattr(IntegrationsService, "confirm_enable")
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
