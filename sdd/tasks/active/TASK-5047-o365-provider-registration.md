# TASK-5047: Register O365 as a connection provider; WorkIQ reads the shared O365 record

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5041, TASK-5046
**Assigned-to**: unassigned

---

## Context

Spec §2 "O365 consolidation (M3, D3)" and §3 Module 3 (`_register_oauth2_providers`); AC-8.
Two consumers still bypass the single O365 record:

1. **The panel never sees O365.** `O365OAuth2Provider` is registered nowhere (docstring example only,
   `o365_provider.py:6-14`). This task builds one `O365OAuthManager` per app when `O365_CLIENT_ID` is set and
   registers the provider.
   **Correction to the spec skeleton**: spec §3 M3 places this inside `_register_oauth2_providers` (an
   `on_startup` callback). That cannot work: `AbstractOAuth2Manager.setup()` mounts the callback route and appends
   `on_startup`/`on_cleanup` signals (`oauth2_base.py:276-304`), and aiohttp freezes the router and signals before
   startup callbacks run. The repo already solved this for descriptor providers — they are wired synchronously in
   `BotManager.setup()` "before aiohttp freezes the router" (`manager.py:2396-2400`). Do the same.
2. **WorkIQ OBO reads `VaultTokenSync` `o365:*`** for its source Entra token (`workiq_provider.py:140-142`). Once
   device code stops writing that key (TASK-5046) and 3LO never wrote it, WorkIQ would always say "sign-in required",
   and AC-8 forbids the `o365` vault read. WorkIQ must take the Entra token from
   `O365OAuthManager.get_valid_token(...)` for the resolved principal. Its own `workiq:*` OBO cache stays in
   `VaultTokenSync` (spec Non-Goals: work.iq keys unchanged).

---

## Scope

- Add `BotManager._register_o365_oauth2_provider(app)` (sync) and call it in `setup()` right after
  `self._register_descriptor_oauth2_providers(self.app)`; idempotent via an app flag.
- Reuse `app["oauth2_manager_o365"]` when another component already built one; otherwise construct
  `O365OAuthManager(client_id=O365_CLIENT_ID, client_secret=O365_CLIENT_SECRET, redirect_uri=O365_REDIRECT_URI,
  tenant_id=O365_TENANT_ID or "common", app=app, credential_store=IdentityVaultCredentialStore(authdb) | None,
  event_publisher=app.get("connection_event_publisher"))`, call `.setup()`, and `register_oauth2_provider(O365OAuth2Provider(manager=…))`.
- `WorkIQOBOCredentialResolver.resolve`: replace the `o365:*` vault read with principal resolution +
  `self._o365_manager.get_valid_token(...)`.
- Tests: new registration test; update the WorkIQ vertical test and remove TASK-5046's `xfail` in the CLI e2e test.

**NOT in scope**: the device-code resolver (TASK-5046), the `/enable` route (TASK-5048), the msagentsdk O365 manager
built in `parrot/integrations/manager.py:880-903` (it already reuses an existing `oauth2_manager_o365` slot).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | setup-time O365 manager + provider registration |
| `packages/ai-parrot/src/parrot/auth/oauth2/workiq_provider.py` | MODIFY | Entra source token from the shared O365 record |
| `packages/ai-parrot-server/tests/unit/test_o365_provider_registration.py` | CREATE | registration tests |
| `packages/ai-parrot-server/tests/integration/test_a2a_workiq_vertical.py` | MODIFY | seed the manager, not `o365:*` |
| `packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py` | MODIFY | un-xfail the WorkIQ consumption test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.conf import O365_CLIENT_ID, O365_CLIENT_SECRET, O365_TENANT_ID, O365_REDIRECT_URI  # verified: conf.py:618-625
from parrot.auth.o365_oauth import O365OAuthManager                                              # verified: o365_oauth.py:60
from parrot.auth.oauth2.o365_provider import O365OAuth2Provider                                  # verified: o365_provider.py:32
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry, register_oauth2_provider         # verified: registry.py:69, :126
from parrot.services.identity_credential_sink import IdentityVaultCredentialStore                # verified: identity_credential_sink.py:55
from parrot.auth.principal import resolve_principal                                              # verified: principal.py:73
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/manager/manager.py
#   setup(): self._register_descriptor_oauth2_providers(self.app)   # :2400 (sync, app still mutable)
#            self.app.on_startup.append(self._register_oauth2_providers)   # :2401
def _register_descriptor_oauth2_providers(self, app) -> None   # :2806 — pattern: lazy imports, app.get("authdb"),
#   IdentityVaultCredentialStore(authdb) if authdb else None, event_publisher=app.get("connection_event_publisher"),
#   app["_descriptor_oauth2_providers_registered"] flag, broad except + self.logger.exception
async def _register_oauth2_providers(self, app) -> None        # :2831 (on_startup; Jira + principal resolver)

# packages/ai-parrot/src/parrot/auth/oauth2_base.py
AbstractOAuth2Manager.__init__(client_id, redirect_uri, *, client_secret=None, app=None, redis_url=None, redis_client=None,
    scopes=None, http_session=None, credential_store=None, event_publisher=None, callback_path=None)   # :224
def setup(self) -> None   # :276 — app[f"oauth2_manager_{provider_id}"] = self; appends signals; mounts callback route
#   raises RuntimeError if the slot holds a different instance (:291-295)
async def get_valid_token(self, channel, user_id, *, channel_user_id=None)   # :642

# packages/ai-parrot/src/parrot/auth/o365_oauth.py
O365OAuthManager.__init__(client_id, client_secret, redirect_uri, *, tenant_id="common", **kwargs)   # :78
# packages/ai-parrot/src/parrot/auth/oauth2/o365_provider.py
class O365OAuth2Provider(OAuth2Provider): provider_id = "o365"; def __init__(self, manager)   # :32, :60

# packages/ai-parrot/src/parrot/auth/oauth2/workiq_provider.py
_O365_VAULT_PREFIX: str = "o365"   # :63 — remove (no longer read)
class WorkIQOBOCredentialResolver:
    def __init__(self, o365_interface, o365_oauth_manager, vault_token_sync, workiq_scope=WORKIQ_SCOPE)   # :95 (unchanged)
    async def resolve(self, channel, user_id) -> Optional[str]   # :107; Entra read :139-149; OBO :152-155
```

### Does NOT Exist
- ~~O365 provider registration anywhere in `packages/*/src`~~ — only the `o365_provider.py` docstring.
- ~~Calling `manager.setup()` from an `on_startup` callback~~ — router/signals are frozen by then; never do it.
- ~~`app["connection_event_publisher"]` guaranteed at `setup()` time~~ — it is created lazily by
  `parrot/integrations/manager.py:146-158`. See the FILL IN below.
- ~~A `channel == "a2a:copilot"` branch in `IdentityPrincipalResolver`~~ — it matches `"a2a"` exactly (`identity_principal.py:40`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/manager/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/auth/oauth2/workiq_provider.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/unit/test_o365_provider_registration.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/integration/test_a2a_workiq_vertical.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager._register_descriptor_oauth2_providers",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.setup",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_base.py#AbstractOAuth2Manager.setup",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_base.py#AbstractOAuth2Manager.get_valid_token",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/o365_provider.py#O365OAuth2Provider",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/registry.py#register_oauth2_provider",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/workiq_provider.py#WorkIQOBOCredentialResolver.resolve",
    "sym:packages/ai-parrot/src/parrot/auth/principal.py#resolve_principal"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `_register_o365_oauth2_provider` next to `_register_descriptor_oauth2_providers` — *why*: same mutability constraint, same failure policy (log, never break startup).
2. Call it in `setup()` after the descriptor call — *why*: router and signals must still be mutable.
3. Rewrite WorkIQ step 2 — *why*: AC-8 (no `o365` vault read) and one Entra sign-in covers both.
4. Tests; remove TASK-5046's `xfail`.

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY — call site)
```python
# occurrences: 1 (verified: grep -c '        self._register_descriptor_oauth2_providers(self.app)' packages/ai-parrot-server/src/parrot/manager/manager.py)
# AFTER — insert below `        self._register_descriptor_oauth2_providers(self.app)` (verified: manager.py:2400)
        self._register_o365_oauth2_provider(self.app)
```

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY — new method)
```python
# occurrences: 1 (verified: grep -c '    async def _register_oauth2_providers(self, app: web.Application) -> None:' …manager.py)
# BEFORE — insert above `    async def _register_oauth2_providers(self, app: web.Application) -> None:` (verified: manager.py:2831)
    def _register_o365_oauth2_provider(self, app: web.Application) -> None:
        """Wire the single O365 manager and register ``O365OAuth2Provider`` while the app is mutable (FEAT-777 M3)."""
        from parrot.conf import O365_CLIENT_ID, O365_CLIENT_SECRET, O365_REDIRECT_URI, O365_TENANT_ID

        if not O365_CLIENT_ID or app.get("_o365_oauth2_provider_registered"):
            return
        try:
            from parrot.auth.o365_oauth import O365OAuthManager
            from parrot.auth.oauth2.o365_provider import O365OAuth2Provider
            from parrot.auth.oauth2.registry import register_oauth2_provider
            from parrot.services.identity_credential_sink import IdentityVaultCredentialStore

            manager = app.get(f"oauth2_manager_{O365OAuthManager.provider_id}")
            if manager is None:
                authdb = app.get("authdb")
                manager = O365OAuthManager(
                    O365_CLIENT_ID,
                    O365_CLIENT_SECRET,
                    O365_REDIRECT_URI,
                    tenant_id=O365_TENANT_ID or "common",
                    app=app,
                    credential_store=IdentityVaultCredentialStore(authdb) if authdb is not None else None,
                    event_publisher=app.get("connection_event_publisher"),
                )
                manager.setup()
            # FILL IN: if the manager has no publisher (app["connection_event_publisher"] absent at setup time),
            #          attach it in _register_oauth2_providers (on_startup) once the integrations manager created it —
            #          verify how the Jira manager receives its publisher first; bounded by AC-3 (SSE sees o365 events)
            register_oauth2_provider(O365OAuth2Provider(manager=manager))
            app["_o365_oauth2_provider_registered"] = True
            self.logger.info("Registered O365OAuth2Provider with the global OAuth2ProviderRegistry")
        except Exception:  # noqa: BLE001 — a misconfigured O365 app must not break startup
            self.logger.exception("Failed to register the O365 OAuth2 provider")
```
**Why**: `O365_CLIENT_SECRET` is required by `O365OAuthManager.require_client_secret`; a missing secret raises
`ValueError` here and is logged, mirroring the descriptor path.

### `packages/ai-parrot/src/parrot/auth/oauth2/workiq_provider.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        entra_tokens: Optional\[Dict\[str, Any\]\] = await self._vault.read_tokens(' …workiq_provider.py)
# REPLACE step 2 (verified: workiq_provider.py:139-149) with:
        # 2. Source Entra token from the single principal-keyed O365 record (FEAT-777 M3, AC-8).
        principal = await resolve_principal(self._principal_channel(channel), user_id)
        if principal is None or self._o365_manager is None:
            logger.debug("WorkIQOBOCredentialResolver: no principal/manager for user=%s; Entra sign-in required", user_id)
            return None
        entra = await self._o365_manager.get_valid_token(channel, principal.user_id)
        if entra is None:
            logger.debug("WorkIQOBOCredentialResolver: no Entra connection for user=%s; sign-in required", user_id)
            return None
        entra_access_token = entra.access_token
# and in step 3 use `user_assertion=entra_access_token` instead of `entra_tokens["access_token"]`.

    @staticmethod
    def _principal_channel(channel: str) -> str:
        """Map a qualified A2A channel (``"a2a:copilot"``) to the resolver's base channel."""
        # FILL IN: return channel.split(":", 1)[0] — bounded by identity_principal.py:40 exact-match on "a2a"
```
Add `from parrot.auth.principal import resolve_principal` to the imports (:45 block) and delete `_O365_VAULT_PREFIX` (:63).
Update the module docstring lines :14-23 ("stored in vault as `o365:access_token`") accordingly.

### `packages/ai-parrot-server/tests/unit/test_o365_provider_registration.py` (CREATE)
```python
"""FEAT-777 M3: O365 provider registration at BotManager setup time."""
from unittest.mock import Mock

from aiohttp import web

from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.manager.manager import BotManager


def _manager() -> BotManager:
    manager = object.__new__(BotManager)   # pattern: tests/unit/test_register_oauth2_providers.py:18
    manager.logger = Mock()
    return manager


def test_o365_provider_registered_when_configured(monkeypatch):
    """O365_CLIENT_ID set → registry.get('o365') is the provider; the app slot holds the manager; idempotent."""
    # FILL IN: monkeypatch parrot.conf.O365_CLIENT_ID/SECRET/REDIRECT_URI/TENANT_ID; app = web.Application(); app["redis"]=Mock();
    #          OAuth2ProviderRegistry._reset() before and after; call twice; assert one registration


def test_o365_provider_absent_when_unconfigured(monkeypatch):
    """O365_CLIENT_ID unset → nothing registered, no route mounted."""


def test_o365_provider_reuses_existing_manager(monkeypatch):
    """A pre-existing app['oauth2_manager_o365'] is reused, not replaced (no RuntimeError)."""
```

### Other test edits
```python
# packages/ai-parrot-server/tests/integration/test_a2a_workiq_vertical.py
# FILL IN: FakeVaultTokenSync.grant_entra (:70-72) → seed the FakeO365OAuthManager (:78) with get_valid_token returning an
#          object with .access_token; register a fake principal resolver (set_principal_resolver; reset after);
#          test_workiq_no_entra_token_suspends must still suspend when the manager returns None
# packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py
# FILL IN: remove the xfail added by TASK-5046 from test_devicecode_token_consumable_by_workiq_obo; WorkIQ reads the
#          device-code grant through FakeO365OAuthManager.get_valid_token
```

### FILL IN checklist
- [ ] publisher attachment when absent at setup time — bounded by AC-3 / spec §2 M1
- [ ] `_principal_channel` — bounded by `identity_principal.py:40`
- [ ] three registration tests — bounded by spec §4 `test_o365_provider_registered_when_configured`
- [ ] WorkIQ vertical + CLI e2e test updates — bounded by AC-8

---

## Acceptance Criteria

- [ ] With `O365_CLIENT_ID` set, `OAuth2ProviderRegistry().get("o365")` returns an `O365OAuth2Provider`; unset → `None` (AC-8).
- [ ] `manager.setup()` is never called from an `on_startup` callback.
- [ ] `grep -rn '_O365_VAULT_PREFIX' packages/ai-parrot/src/parrot/auth/oauth2/workiq_provider.py` returns nothing.
- [ ] WorkIQ OBO works from a device-code grant and from a 3LO grant (same record).
- [ ] `ruff check` clean on `manager.py` and `workiq_provider.py`.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_o365_provider_registration.py -q`
- `pytest packages/ai-parrot-server/tests/unit/test_register_oauth2_providers.py -q`
- `pytest packages/ai-parrot-server/tests/integration/test_a2a_workiq_vertical.py -q`
- `pytest packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py -q`
- `pytest packages/ai-parrot/tests/unit/test_resolver_strategies.py -q`

---

## Test Specification

| Test | Must assert |
|---|---|
| `test_o365_provider_registered_when_configured` | provider registered once; `app["oauth2_manager_o365"]` set |
| `test_o365_provider_absent_when_unconfigured` | registry has no `o365` |
| `test_o365_provider_reuses_existing_manager` | existing manager reused; no exception |
| `test_workiq_obo_exchange_success` (updated) | OBO uses the manager's Entra token |

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/connections-web-slack.json`
4. **Verify the Codebase Contract** before writing ANY code (`manager.py` line numbers move after TASK-5040/TASK-5041)
5. **Update status** in the per-spec index → `"in-progress"` and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit the code** — stage only the files listed above
9. **Close the task** with `scripts/sdd/close_task.sh TASK-5047 connections-web-slack verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: Record the setup-time (not on_startup) registration as a deviation from spec §3 M3's skeleton, and the
WorkIQ change (not named in the spec, required by AC-8).

**Deviations from spec**: setup-time registration; WorkIQ Entra source moved to the shared record.
