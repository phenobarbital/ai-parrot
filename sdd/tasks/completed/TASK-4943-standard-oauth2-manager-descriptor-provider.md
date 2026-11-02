# TASK-4943: StandardOAuth2Manager, DescriptorOAuth2Provider and register_descriptor_providers

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4939, TASK-4941
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (G3, AC-4). A new provider must be addable with a descriptor + navconfig secrets and no
subclass. `StandardOAuth2Manager` implements the RFC 6749 authorization-code exchange and refresh, PKCE per
descriptor, `extra_authorize_params`, a JSON-path identity probe, the descriptor's post-exchange hook (by name) and
`revoke_url`. `DescriptorOAuth2Provider` exposes it through the existing `OAuth2ProviderRegistry`.

---

## Scope

- Add to `descriptor.py`: `StandardOAuth2Manager(AbstractOAuth2Manager)`, `DescriptorOAuth2Provider(OAuth2Provider)`,
  `register_descriptor_providers(descriptors, *, app, credential_store, event_publisher)`.
- Secrets: `OAUTH2_<PROVIDER>_CLIENT_ID/_CLIENT_SECRET/_REDIRECT_URI` via `navconfig.config.get`; a descriptor whose
  client id is missing is skipped with a warning (not an error); confidential client without a secret → skip + warning.
- `_refresh_request`: `invalid_grant` → `InvalidGrantError`; 429/5xx/network → `RefreshTransientError`; other → `RuntimeError`.
- `toolkit_factory` returns `None` unless a factory callable was passed to the provider (no registry exists for it).
- Tests: `test_standard_manager_exchange_refresh_probe`, dummy provider end-to-end through the registry (AC-4),
  secrets-from-conf half of `test_descriptor_validation_and_secrets_from_conf`.

**NOT in scope**: the Jira descriptor/hook (TASK-4954); BotManager wiring (TASK-4957); exports in `oauth2/__init__.py` (TASK-4949).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/descriptor.py` | MODIFY | generic manager, provider, registration helper |
| `packages/ai-parrot/tests/unit/auth/test_standard_oauth2_manager.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from parrot.auth.oauth2_base import (AbstractOAuth2Manager, AbstractOAuth2TokenSet, CredentialStore,
                                     InvalidGrantError, RefreshTransientError)      # :89, :61 + TASK-4940
from parrot.auth.oauth2.registry import OAuth2Provider, register_oauth2_provider     # verified: registry.py:20, :126
from parrot.auth.oauth2.events import ConnectionEventPublisher                      # TASK-4938
from navconfig import config                                                        # verified: conf.py:6
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/oauth2/registry.py
class OAuth2Provider(ABC):                                     # :20
    provider_id / display_name / icon (class attrs); default_scopes: ClassVar[List[str]] (:39); pbac_action_namespace = "integration" (:40)
    @property @abstractmethod def manager(self) -> Any          # :44
    @abstractmethod def toolkit_factory(self, credential_resolver)   # :53
def register_oauth2_provider(provider: OAuth2Provider) -> None  # :126
# packages/ai-parrot/src/parrot/auth/oauth2/mcp_provider.py:36 — precedent of a provider whose toolkit_factory returns None
# AbstractOAuth2Manager (after TASK-4940/4941): provider_id is a ClassVar checked in __init__ (raise if empty) —
#   O365 (o365_oauth.py:84-95) sets per-instance authorization_url/token_url BEFORE super().__init__: copy that.
#   hooks: _exchange_code, _refresh_request, _discover_identity, _build_token_set, authorization_url_extra_params,
#   _post_exchange(token_response, token_set), _revoke_remote(token_set), _get_session(), setup()
# descriptor.py (TASK-4939): OAuth2ProviderDescriptor, RefreshPolicy, IdentityProbe, post_exchange_hooks
```

### Does NOT Exist
- ~~`ToolkitFactoryRegistry`~~ — does not exist anywhere in `packages/` (the spec mentions it; do not create a registry).
- ~~`StandardOAuth2Manager` / `DescriptorOAuth2Provider` / `register_descriptor_providers`~~ — created here.
- ~~descriptor client secrets~~ — navconfig only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/descriptor.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/auth/test_standard_oauth2_manager.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/registry.py#OAuth2Provider",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/registry.py#register_oauth2_provider",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_base.py#AbstractOAuth2Manager"
  ]
}
```

---

## Implementation Notes

- Instance attributes shadow the base ClassVars: set `self.provider_id`, `self.authorization_url`, `self.token_url`,
  `self.default_scopes`, `self.use_pkce = descriptor.pkce != "none"`, `self.require_client_secret =
  descriptor.client_type == "confidential"` BEFORE `super().__init__` (it validates `provider_id` and the secret).
- JSON path: dotted keys (`"account.id"`), list index allowed as an integer segment.
- Token set: `_build_token_set` maps `access_token`, `refresh_token`, `expires_at = now + expires_in`, `scopes`
  (space split), `granted_at`, `account_id/display_name/email` from the probe.

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Append the manager (block A) — *why*: generic RFC 6749 behaviour from data (G3).
2. Append provider + registration helper (block B) — *why*: registry integration without a subclass (AC-4).
3. Tests with an aiohttp test server playing the IdP — *why*: exchange/refresh/probe/revoke over real HTTP.

### `packages/ai-parrot/src/parrot/auth/oauth2/descriptor.py` (MODIFY — append after `load_provider_descriptors`)

Block A — manager:
```python
class StandardOAuth2Manager(AbstractOAuth2Manager):
    """Descriptor-driven RFC 6749 manager: endpoints, scopes, PKCE, extra params, probe, hook, revoke."""

    def __init__(self, descriptor: OAuth2ProviderDescriptor, *, client_id: str, client_secret: Optional[str],
                 redirect_uri: str, hooks: Optional[PostExchangeHookRegistry] = None, **manager_kwargs: Any) -> None:
        self.descriptor = descriptor
        self.provider_id = descriptor.provider_id
        self.authorization_url = descriptor.authorization_url
        self.token_url = descriptor.token_url
        self.default_scopes = list(descriptor.default_scopes)
        self.use_pkce = descriptor.pkce != "none"
        self.require_client_secret = descriptor.client_type == "confidential"
        self._hooks = hooks or post_exchange_hooks
        super().__init__(client_id, redirect_uri, client_secret=client_secret, **manager_kwargs)

    def authorization_url_extra_params(self) -> Dict[str, str]:
        return dict(self.descriptor.extra_authorize_params)

    async def _exchange_code(self, code: str, code_verifier: Optional[str]) -> Dict[str, Any]:
        # FILL IN: POST token_url form {grant_type=authorization_code, code, redirect_uri, client_id,
        #          client_secret (confidential only), code_verifier (when given)}; non-200 → ValueError(status only)
        raise NotImplementedError

    async def _refresh_request(self, refresh_token: str) -> Dict[str, Any]:
        # FILL IN: POST grant_type=refresh_token; invalid_grant → InvalidGrantError; 429/5xx/ClientError/timeout →
        #          RefreshTransientError; other → RuntimeError — bounded by AC-10 (no token text in messages)
        raise NotImplementedError

    async def _discover_identity(self, access_token: str) -> Dict[str, Any]:
        # FILL IN: no identity_probe → {}; GET probe.url with Bearer; extract account_id/display_name/email via
        #          _json_path(); missing account_id → ValueError naming the path
        raise NotImplementedError

    def _build_token_set(self, token_payload: Dict[str, Any], identity: Dict[str, Any]) -> AbstractOAuth2TokenSet:
        # FILL IN: build self.token_set_cls(...) per Implementation Notes
        raise NotImplementedError

    async def _post_exchange(self, token_response: Dict[str, Any],
                             token_set: AbstractOAuth2TokenSet) -> AbstractOAuth2TokenSet:
        if not self.descriptor.post_exchange:
            return token_set
        hook = self._hooks.get(self.descriptor.post_exchange)
        return await hook(self, token_response, token_set)

    async def _revoke_remote(self, token_set: AbstractOAuth2TokenSet) -> None:
        # FILL IN: revoke_url None → return; POST token=<refresh or access>, token_type_hint, client auth;
        #          non-2xx → logger.warning(status) — best effort, never raise
        return None


def _json_path(document: Any, path: Optional[str]) -> Any:
    """Resolve a dotted path (integer segments index lists); None when absent."""
    # FILL IN
    raise NotImplementedError
```

Block B — provider + registration:
```python
class DescriptorOAuth2Provider(OAuth2Provider):
    """Registry entry backed by a descriptor + StandardOAuth2Manager."""

    def __init__(self, descriptor: OAuth2ProviderDescriptor, manager: StandardOAuth2Manager,
                 toolkit_factory_fn: Optional[Callable[[Any], Any]] = None) -> None:
        self.provider_id = descriptor.provider_id
        self.display_name = descriptor.display_name
        self.icon = descriptor.icon
        self.default_scopes = list(descriptor.default_scopes)
        self.pbac_action_namespace = descriptor.pbac_action_namespace
        self._manager = manager
        self._toolkit_factory_fn = toolkit_factory_fn

    @property
    def manager(self) -> StandardOAuth2Manager:
        return self._manager

    def toolkit_factory(self, credential_resolver: Any) -> Any:
        """None unless a factory was supplied (MCP-like providers, mcp_provider.py:36)."""
        return self._toolkit_factory_fn(credential_resolver) if self._toolkit_factory_fn else None


def register_descriptor_providers(descriptors: Sequence[OAuth2ProviderDescriptor], *, app: Any,
                                  credential_store: Optional[CredentialStore],
                                  event_publisher: Optional[ConnectionEventPublisher]) -> List[DescriptorOAuth2Provider]:
    """Build managers from navconfig secrets, call manager.setup(), register providers; skip unconfigured ones."""
    # FILL IN: for each d: key = d.provider_id.upper(); client_id = config.get(f"OAUTH2_{key}_CLIENT_ID");
    #          secret / redirect likewise; missing id or redirect (or secret for confidential) → logger.warning, continue;
    #          manager = StandardOAuth2Manager(d, client_id=…, client_secret=…, redirect_uri=…, app=app,
    #          credential_store=credential_store, event_publisher=event_publisher); manager.setup();
    #          provider = DescriptorOAuth2Provider(d, manager); register_oauth2_provider(provider); collect
    raise NotImplementedError
```
**Why this shape**: constructor and hook names are the spec §3 M3 skeleton; `hooks` and `toolkit_factory_fn` are
injection points for tests and Jira. Setting instance attributes before `super().__init__` mirrors O365.

### FILL IN checklist
- [ ] `StandardOAuth2Manager._exchange_code/_refresh_request/_discover_identity/_build_token_set/_revoke_remote`
- [ ] `_json_path`
- [ ] `register_descriptor_providers` — navconfig secrets, skip rules
- [ ] imports in descriptor.py (`Callable`, manager/registry imports — keep oauth2_base import at module level only if no cycle; else local)
- [ ] `test_standard_oauth2_manager.py` — test bodies

---

## Acceptance Criteria

- [ ] AC-4: a dummy provider added only by a descriptor + navconfig secrets completes authorize → callback → get_valid_token through the registry (no subclass)
- [ ] PKCE on/off per descriptor; extra_authorize_params appear in the authorization URL
- [ ] Refresh classification matches AC-10; `revoke_url` is POSTed on revoke when set
- [ ] Client secrets are only read from `OAUTH2_<PROVIDER>_*`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/auth/test_standard_oauth2_manager.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/auth/test_standard_oauth2_manager.py
import pytest
# FILL IN: aiohttp.test_utils TestServer exposing /token, /me, /revoke; MemRedis/FakeCredentialStore from ._oauth2_fakes

@pytest.mark.asyncio
async def test_standard_manager_exchange_refresh_probe(): ...   # authorize URL has code_challenge iff pkce != none;
                                                               # callback stores account_id from probe path; refresh replaces token
@pytest.mark.asyncio
async def test_dummy_provider_end_to_end_via_registry(monkeypatch): ...  # OAUTH2_DUMMY_CLIENT_ID etc. via patched config.get;
                                                                         # register_descriptor_providers → OAuth2ProviderRegistry().get("dummy")
def test_unconfigured_descriptor_is_skipped(): ...
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

**Completed by**: sdd-worker orchestrator; seat gpt-5.6-sol (codex)
**Date**: 2026-10-30
**Notes**: Implemented per task; merged, engine lint clean. Merge-tier validation: only red is pre-existing test_invalid_state_returns_400 (issue:e7b7e5906b6e).
