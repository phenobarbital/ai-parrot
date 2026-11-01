# TASK-4954: JiraOAuthManager on StandardOAuth2Manager (+ descriptor, hook, legacy jira:oauth read)

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4943, TASK-4950
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (G3, AC-4, AC-13, AC-14, AC-20). `JiraOAuthManager` is a parallel implementation (no PKCE, own
nonce/lock keys, `jira:oauth:{channel}:{user_id}` keys, a `CredentialSink` written after Redis). It becomes a
`StandardOAuth2Manager` subclass driven by `JIRA_DESCRIPTOR`, with the `atlassian_accessible_resources` post-exchange
hook (cloud id, site, `/myself` identity) built from the TASK-4418 helpers. Its public API is preserved. During the
window it also migrates the legacy `jira:oauth:{channel}:{channel_user_id}` keys. The callback route is NOT switched
here (TASK-4958, after the notifier adapters are registered) — Jira's `setup()` keeps mounting
`setup_jira_oauth_routes` and also stores `app['oauth2_manager_jira']`.

---

## Scope

- `JiraTokenSet(AbstractOAuth2TokenSet)` with `cloud_id`, `site_url`, `available_sites`; keep `api_base_url`.
- `JIRA_DESCRIPTOR` (values from `build_authorization_url`: audience + prompt=consent; `pkce="none"`;
  `RefreshPolicy(rotating=True, sliding=True, refresh_lifetime_s=7776000)`; `post_exchange="atlassian_accessible_resources"`).
- Register the hook in `post_exchange_hooks` at import; it fills cloud_id/site_url/available_sites/account/display/email.
- `JiraOAuthManager(StandardOAuth2Manager)`: same constructor positional args; `credential_store` replaces
  `credential_sink`; `event_publisher`; `callback_path="/api/auth/jira/callback"`; `validate_token` kept;
  `_read_legacy_token` also reads `jira:oauth:{channel}:{channel_user_id}`; `_public_metadata` returns site_url/cloud_id;
  `setup()` keeps today's behaviour (app['jira_oauth_manager'] + startup/cleanup + `setup_jira_oauth_routes`) and also
  sets `app['oauth2_manager_jira']`.
- Delete `CredentialSink`, `_token_key`/`_read_token`/`_write_token` and the duplicated nonce/lock/refresh code.
- `integrations/manager.py`: `_build_jira_credential_sink` → `_build_credential_store` (returns
  `IdentityVaultCredentialStore` or `None`); both construction sites pass `credential_store=`.
- Update `test_jira_oauth_manager.py`; add `test_jira_manager_is_standard_subclass_public_api`,
  `test_jira_legacy_key_dual_read_bound_only`, descriptor value test (AC-20).

**NOT in scope**: callback alias + deleting `jira_oauth_callback` (TASK-4958); principal resolver/notifier registration (TASK-4955); toolkit cache (TASK-4959).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/jira_oauth.py` | MODIFY | re-base on StandardOAuth2Manager |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | credential_store at both construction sites |
| `packages/ai-parrot/tests/unit/test_jira_oauth_manager.py` | MODIFY | new base + legacy read |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from parrot.auth.oauth2.descriptor import (OAuth2ProviderDescriptor, RefreshPolicy, IdentityProbe,
                                           StandardOAuth2Manager, post_exchange_hooks)        # TASK-4939/4943
from parrot.auth.oauth2_base import AbstractOAuth2TokenSet, CredentialStore                   # :61 + TASK-4940
from parrot.auth.jira_oauth import (build_authorization_url, exchange_code, refresh_access_token,
                                    fetch_accessible_resources, fetch_myself)                 # verified: jira_oauth.py:102,133,163,191,214
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/jira_oauth.py
AUTHORIZATION_URL / TOKEN_URL / ACCESSIBLE_RESOURCES_URL                                   # :~44-50 module constants
_TOKEN_KEY_PREFIX = "jira:oauth"  # jira:oauth:{channel}:{user_id}                         # legacy layout
class JiraTokenSet(BaseModel):                                                             # :66 anchor — access_token, refresh_token,
    # expires_at, cloud_id, site_url, account_id, display_name, email, scopes, granted_at, last_refreshed_at, available_sites;
    # is_expired / api_base_url are @property
def build_authorization_url(client_id, redirect_uri, state, scopes=DEFAULT_SCOPES, authorization_url=AUTHORIZATION_URL) -> str   # :102
async def exchange_code(session, *, client_id, client_secret, code, redirect_uri, token_url=TOKEN_URL)                       # :133
async def refresh_access_token(session, *, client_id, client_secret, refresh_token, ...)                                     # :163
async def fetch_accessible_resources(session, access_token, url=ACCESSIBLE_RESOURCES_URL) -> List[Dict]                      # :191
async def fetch_myself(session, access_token, cloud_id) -> Dict[str, Any]                                                    # :214
class CredentialSink(Protocol)                                                             # :231 anchor (delete)
class JiraOAuthManager:                                                                    # :262 anchor
    def __init__(self, client_id, client_secret, redirect_uri, *, app=None, redis_url=None, redis_client=None,
                 scopes=None, http_session=None, credential_sink: Optional[CredentialSink] = None)   # :274-286 (:285 anchor)
    def setup(self) -> None        # :311 app["jira_oauth_manager"]=self (:339); on_startup/_on_cleanup; setup_jira_oauth_routes(app) (:344)
    async def validate_token(self, channel, user_id) -> Optional[JiraTokenSet]               # :621
# packages/ai-parrot-integrations/src/parrot/integrations/manager.py
def _build_jira_credential_sink(app: Any) -> Any:              # :81 anchor (lazy import of IdentityVaultCredentialSink :97-101)
                        credential_sink=_build_jira_credential_sink(app),   # :372 (MS Teams, under "MS Teams bot '%s': initialized
                                                                            #   JiraOAuthManager") and :931 (Slack) — occurrences: 2
```

### Does NOT Exist
- ~~`JiraOAuthManager(AbstractOAuth2Manager)`~~ today — a plain class; re-based here.
- ~~`CredentialSink`~~ — deleted here; ~~`IdentityVaultCredentialSink`~~ — gone since TASK-4950.
- ~~changing `JIRA_REDIRECT_URI`~~ — never; the Atlassian app's registered redirect is `/api/auth/jira/callback`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/jira_oauth.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/test_jira_oauth_manager.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/jira_oauth.py#JiraOAuthManager",
    "sym:packages/ai-parrot/src/parrot/auth/jira_oauth.py#JiraTokenSet",
    "sym:packages/ai-parrot/src/parrot/auth/jira_oauth.py#fetch_accessible_resources",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/manager.py#_build_jira_credential_sink"
  ]
}
```

---

## Implementation Notes

- Run `wikitoolkit symbols blast JiraOAuthManager` first; the public API used by channel commands
  (`create_authorization_url`, `handle_callback`, `get_valid_token`, `validate_token`, `is_connected`, `revoke`) must keep its names.
- Atlassian has no PKCE requirement → `pkce="none"`; scopes default from the current `DEFAULT_SCOPES`.
- Atlassian rotates refresh tokens (10-minute reuse window): durable-first persistence is mandatory (§7 R6).
- The Jira `JiraTokenSet` previously required `cloud_id`/`site_url`; give them `""` defaults so the base can build it
  before the hook runs.
- `integrations/manager.py`: rename only — `_build_credential_store(app)`; principal resolver / notifier registration is TASK-4955.

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Re-base `JiraTokenSet` and write `JIRA_DESCRIPTOR` + hook (block A) — *why*: G3 data-driven provider.
2. Rewrite `JiraOAuthManager` (block B) — *why*: one engine; keep API.
3. Switch the two construction sites (block C) — *why*: `credential_sink` no longer exists.
4. Update tests.

### `packages/ai-parrot/src/parrot/auth/jira_oauth.py` (MODIFY)

Block A:
```python
# occurrences: 1 (verified: grep -c 'class JiraTokenSet(BaseModel):' jira_oauth.py → :66)
class JiraTokenSet(AbstractOAuth2TokenSet):
    cloud_id: str = ""
    site_url: str = ""
    available_sites: List[Dict[str, Any]] = Field(default_factory=list)
    # KEEP the api_base_url property; drop fields now inherited and the is_expired override if equivalent
    #   (FILL IN: keep Jira's leeway if it differs from the base 60 s)

JIRA_DESCRIPTOR = OAuth2ProviderDescriptor(
    provider_id="jira", display_name="Jira", icon="mdi:jira",
    authorization_url=AUTHORIZATION_URL, token_url=TOKEN_URL, default_scopes=list(DEFAULT_SCOPES),
    client_type="confidential", pkce="none",
    refresh_policy=RefreshPolicy(rotating=True, sliding=True, refresh_lifetime_s=90 * 86400),
    extra_authorize_params={"audience": "api.atlassian.com", "prompt": "consent"},
    post_exchange="atlassian_accessible_resources",
)


async def _atlassian_accessible_resources(manager: Any, token_response: Dict[str, Any],
                                          token_set: AbstractOAuth2TokenSet) -> "JiraTokenSet":
    """Fill cloud/site/identity from accessible-resources + /myself (TASK-4418 helpers)."""
    # FILL IN: reuse the logic of today's handle_callback (:481-540): session = await manager._get_session();
    #          sites = await fetch_accessible_resources(session, token_set.access_token); pick the first site
    #          (same rule as today); me = await fetch_myself(...); return JiraTokenSet(**token_set.model_dump(),
    #          cloud_id=…, site_url=…, available_sites=sites, account_id=…, display_name=…, email=…)
    raise NotImplementedError


post_exchange_hooks.register("atlassian_accessible_resources", _atlassian_accessible_resources)
# FILL IN: verify build_authorization_url (:102-131) params match extra_authorize_params exactly
```

Block B:
```python
# occurrences: 1 each (verified: 'class CredentialSink(Protocol):' :231, 'class JiraOAuthManager:' :262,
#   '        credential_sink: Optional[CredentialSink] = None,' :285)
# DELETE CredentialSink (:231-259). REPLACE JiraOAuthManager WITH:
class JiraOAuthManager(StandardOAuth2Manager):
    """Atlassian 3LO on the generic engine. Public API preserved."""

    token_set_cls = JiraTokenSet

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, *, app: Any = None,
                 redis_url: Optional[str] = None, redis_client: Any = None, scopes: Optional[List[str]] = None,
                 http_session: Optional[aiohttp.ClientSession] = None,
                 credential_store: Optional["CredentialStore"] = None, event_publisher: Any = None,
                 callback_path: str = "/api/auth/jira/callback") -> None:
        super().__init__(JIRA_DESCRIPTOR, client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri,
                         app=app, redis_url=redis_url, redis_client=redis_client, scopes=scopes,
                         http_session=http_session, credential_store=credential_store,
                         event_publisher=event_publisher, callback_path=callback_path)

    def setup(self) -> None:
        # FILL IN: keep today's behaviour (:311-345): app["jira_oauth_manager"] = self, startup/cleanup signals,
        #          setup_jira_oauth_routes(app); ALSO app["oauth2_manager_jira"] = self; idempotent; do NOT call the
        #          base setup (it would mount a second GET on the same path)
        raise NotImplementedError

    async def validate_token(self, channel: str, user_id: str) -> Optional[JiraTokenSet]:
        # FILL IN: keep today's semantics (:621-690) on top of get_valid_token (+ /myself probe → revoke on 401)
        raise NotImplementedError

    async def _read_legacy_token(self, channel: str, channel_user_id: str, user_id: str) -> Optional[JiraTokenSet]:
        """Generic legacy layout first, then jira:oauth:{channel}:{channel_user_id} (same rewrite/delete rules)."""
        # FILL IN — bounded by AC-13
        raise NotImplementedError

    def _public_metadata(self, token_set: Any) -> Dict[str, Any]:
        return {"site_url": getattr(token_set, "site_url", ""), "cloud_id": getattr(token_set, "cloud_id", "")}
```
FILL IN: `_refresh_request` — Atlassian returns 400/403 `invalid_grant` for a dead token; reuse the standard mapping
unless today's `refresh_access_token` helper behaves differently (then wrap it and map its errors).

### `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _build_jira_credential_sink(app: Any) -> Any:' integrations/manager.py → :81)
def _build_credential_store(app: Any) -> Any:
    """IdentityVaultCredentialStore over app['authdb'], else None (manager falls back to the vault_utils store)."""
    # FILL IN: same shape as the old function (:94-107) importing IdentityVaultCredentialStore
# occurrences: 2 (verified: grep -c '                        credential_sink=_build_jira_credential_sink(app),' → :372, :931)
# FILL IN: disambiguate — replace at :372 (block that logs "MS Teams bot '%s': initialized JiraOAuthManager") and at
#          :931 (block that logs "Slack bot '%s': initialized JiraOAuthManager") with:
                        credential_store=_build_credential_store(app),
```

### FILL IN checklist
- [ ] `_atlassian_accessible_resources` from today's handle_callback logic
- [ ] `JiraOAuthManager.setup` / `validate_token` / `_read_legacy_token` / `_refresh_request` (if needed)
- [ ] delete `CredentialSink`, `_token_key`, `_read_token`, `_write_token`, duplicated refresh/nonce code
- [ ] `_build_credential_store` + two call sites
- [ ] tests (descriptor values AC-20, subclass/API, legacy dual read bound-only)

---

## Acceptance Criteria

- [ ] AC-4: `JiraOAuthManager` subclasses `StandardOAuth2Manager`; public method names unchanged
- [ ] AC-20: `JIRA_DESCRIPTOR.refresh_policy == RefreshPolicy(rotating=True, sliding=True, refresh_lifetime_s=7776000)`
- [ ] AC-13: for a bound telegram user `jira:oauth:telegram:<id>` is read once, rewritten under the principal and deleted; unbound → `None`
- [ ] AC-14 (part): `CredentialSink` is deleted; `/api/auth/jira/callback` still served
- [ ] `app['jira_oauth_manager']` and `app['oauth2_manager_jira']` both point at the manager

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_jira_oauth_manager.py -q`
- `pytest tests/unit/integrations/oauth2/test_jira_provider.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_jira_oauth_manager.py (add / rewrite)
def test_jira_manager_is_standard_subclass_public_api(): ...
def test_jira_descriptor_refresh_policy(): ...
@pytest.mark.asyncio
async def test_jira_legacy_key_dual_read_bound_only(): ...
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

**Completed by**: sdd-worker orchestrator; seat gpt-5.6-terra (codex), attempt 3; orchestrator restored removed module-level helpers (fix f37f40b6aa)
**Date**: 2026-10-30
**Notes**: Implemented per task; merged, engine lint clean. Merge-tier validation: expected red tests/integration/oauth2/test_e2e_web_connect.py::test_persist_credential_writes_integration_row (asserts removed row.channel; rewritten by TASK-4964) plus pre-existing test_invalid_state_returns_400 (issue:e7b7e5906b6e).
