# Delegated OAuth2 connections on the web channel — deployment recipe and live harness

Companion to [connections.md](connections.md). That guide describes the model
(principals, Identity Vault, PBAC, SSE). This page is the **operational**
side, written from the first live end-to-end run of FEAT-773 (core),
FEAT-774 (CLI/MCP), FEAT-775 (Teams), FEAT-776 (Telegram) and FEAT-777
(web + Slack) on 2026-11-02:

1. how to stand up an `ai-parrot-server` deployment where a web user connects
   Jira and Office 365 from the AgentChat UI and an agent uses both as that user;
2. the reference harness that does exactly that
   (`phenobarbital/parrot-external-auth`, private);
3. the gaps the run exposed and the ledger issues that track them.

---

## 1. Moving parts

```
browser (AgentChat / Account › Connections)
  │  GET  /api/v1/connections                     list for the session principal
  │  POST /api/v1/connections/{provider}/start    {return_origin} → {auth_url, state}
  │  GET  /api/v1/connections/events              SSE connection.* (Redis pub/sub)
  ▼
IntegrationsService ── PBAC (web path = URI check, see §6) ── OAuth2ProviderRegistry
  │                                                               ├─ jira  → JiraOAuthManager   (/api/auth/jira/callback)
  │                                                               └─ o365  → O365OAuthManager   (/api/auth/oauth2/o365/callback)
  ▼ consent at IdP → callback → handle_callback → CredentialStore.save (durable) → Redis oauth2:{p}:{user_id}
ConnectionEventPublisher → ChannelNotifier(web = SSE push) + AuditLedger
  ▼
agent turn: bot.ask() sets client._permission_context → ToolManager.execute_tool(_permission_context=…)
           → JiraToolkit/Office365Toolkit._pre_execute → resolve_principal → OAuthCredentialResolver.resolve
           → token | AuthorizationRequired → AuthRequiredPayload → UI Connect pill (retry_safe from the turn tracker)
```

Persistence involved in one connection:

| Store | What | Config |
|---|---|---|
| Postgres `auth.user_identities` (Identity Vault) | durable grant, AES-GCM with `VAULT_MASTER_KEY_v{N}` / `VAULT_ACTIVE_KEY_ID` | navigator-auth `authdb` pool: `DBHOST/DBUSER/DBPWD/DBNAME` |
| Redis db 4 | hot cache `oauth2:{provider}:{user_id}`, refresh lock, state nonce | `OAUTH2_REDIS_URL`, `JIRA_OAUTH_REDIS_URL` |
| Redis db 1 | shared `app['redis']`, SSE pub/sub `parrot:connections:user:{user_id}` | `REDIS_HOST/PORT/DB` |
| DocumentDB (Mongo) `users_integrations` | status rows the UI lists | `DOCUMENTDB_*` |
| Postgres `auth.users`, `auth.vw_users` | BasicAuth login, principal | same `authdb` |

---

## 2. Bootstrap for an external project

`ai-parrot-server` does not ship a `run.py`; the host project owns the
aiohttp bootstrap (navigator `Application`). Minimal, working shape:

```python
# run.py
from navigator import Application
from app import Main

def build_application() -> Application:
    return Application(Main, enable_jinja2=True)

def create_app():                      # gunicorn factory
    return build_application().setup_app()

if __name__ == "__main__":
    build_application().run()          # APP_HOST / APP_PORT from navconfig
```

```python
# app.py (order matters — see §4)
class Main(AppHandler):
    enable_pgpool = True

    def configure(self):
        super().configure()
        app = self.app
        vault_store = LazyIdentityVaultCredentialStore(app)          # §4.1

        O365OAuthManager(O365_CLIENT_ID, O365_CLIENT_SECRET, O365_REDIRECT_URI,
                         tenant_id=O365_TENANT_ID or "common", app=app,
                         redis_url=OAUTH2_REDIS_URL, credential_store=vault_store).setup()

        self.bot_manager = BotManager(enable_database_bots=False)
        self.bot_manager.setup(app)                                   # redis, SSE push, routes, UI, PBAC

        JiraOAuthManager(JIRA_CLIENT_ID, JIRA_CLIENT_SECRET, JIRA_REDIRECT_URI, app=app,
                         credential_store=vault_store,
                         event_publisher=app.get("connection_event_publisher")).setup()

        auth = AuthHandler()                                          # BasicAuth + sessions + authdb
        auth.setup(app)
        setup_pbac(app, policy_dir=PARROT_PBAC_POLICY_DIR)            # idempotent
```

Project layout navconfig expects: `env/<ENV>/.env` (+ `ENV=dev`), `etc/config.ini`
(`CONFIG_FILE`), `settings/settings.py` with
`AUTHENTICATION_BACKENDS = ("navigator_auth.backends.BasicAuth",)` (navigator-auth
star-imports it last, so it wins), `policies/*.yaml`, `agents/*.py` (`AGENTS_DIR`,
loaded by `registry.load_modules()` when `ENABLE_REGISTRY_BOTS` is on).

The admin UI needs no flag: `BotManager.setup()` calls `setup_admin_ui()` and
serves `parrot/server/ui/dist/` from the installed distribution (`make build-server-ui`
in the ai-parrot checkout; editable installs pick it up directly).

### Agent

Build the delegated toolkits in `post_configure()` — that is where `self.app` is
attached (same pattern as `bots/jira_specialist.py`):

```python
@register_agent(name="external_auth", at_startup=True)
class ExternalAuthAgent(Agent):
    agent_id = "external_auth"

    async def post_configure(self):
        await super().post_configure()
        jira = self.app.get("jira_oauth_manager")
        if jira and self.tool_manager.find_registered_toolkit(JiraToolkit) is None:
            self._register(JiraToolkit(auth_type="oauth2_3lo",
                                       credential_resolver=OAuthCredentialResolver(jira)))
        o365 = self.app.get("oauth2_manager_o365")
        if o365 and self.tool_manager.find_registered_toolkit(Office365Toolkit) is None:
            self._register(Office365Toolkit(credential_resolver=OAuthCredentialResolver(o365),
                                            tenant_id=getattr(o365, "tenant_id", "common")))
        self.sync_tools(self._llm)
```

`_register` = `tool_manager.register_toolkit()` + append to `self.tools` without
duplicate names (`self.tools` may not exist yet when `agent_tools()` returned `[]`).

---

## 3. Environment keys

| Group | Keys |
|---|---|
| Server | `APP_HOST`, `APP_PORT`, `HOSTS` (include the public tunnel host), `ENABLE_DATABASE_BOTS=false`, `ENABLE_CREWS=false`, `ENABLE_JOBS=false` |
| navigator-auth | `DBENGINE DBUSER DBPWD DBHOST DBPORT DBNAME`, `AUTH_CREDENTIALS_REQUIRED AUTH_TOKEN_ISSUER AUTH_SECRET_KEY AUTH_USER_MAPPING AUTH_DB_SCHEMA AUTH_USERS_TABLE AUTH_USERS_VIEW AUTH_USER_MODEL`, `SESSION_STORAGE=redis SESSION_PREFIX SESSION_DB`, `REDIS_HOST REDIS_PORT REDIS_DB` |
| Identity Vault | `VAULT_MASTER_KEY_v1` (base64, 32 bytes), `VAULT_ACTIVE_KEY_ID=1` |
| Connections | `OAUTH2_REDIS_URL`, `JIRA_OAUTH_REDIS_URL`, `WEB_OAUTH_ALLOWED_ORIGINS` (comma list; `return_origin` must match or `/start` is 400), `OAUTH2_LEGACY_KEYS_UNTIL`, `PARROT_PBAC_POLICY_DIR=policies` |
| Jira 3LO | `JIRA_CLIENT_ID JIRA_CLIENT_SECRET JIRA_REDIRECT_URI` (+ `JIRA_AUTH_TYPE=oauth2_3lo`, `JIRA_PROJECT`) — read by the host `app.py`, **not** by the server (§6, issue `9b625450ce4a`) |
| Office 365 | `O365_CLIENT_ID O365_CLIENT_SECRET O365_TENANT_ID O365_REDIRECT_URI` (default `http://localhost:5000/api/auth/oauth2/o365/callback`) |
| DocumentDB | `DOCUMENTDB_HOSTNAME DOCUMENTDB_PORT DOCUMENTDB_USERNAME DOCUMENTDB_PASSWORD DOCUMENTDB_DBNAME DOCUMENTDB_USE_SSL DOCUMENTDB_AUTH_SOURCE` |

IdP side: the Atlassian 3LO app's callback must equal `JIRA_REDIRECT_URI`; the
Entra app must list `O365_REDIRECT_URI` as a *Web* redirect with the delegated
Graph permissions in `Office365Toolkit._OAUTH_SCOPES` plus `offline_access`.

---

## 4. Wiring rules learned the hard way

### 4.1 Bind the Identity Vault lazily

`AbstractOAuth2Manager.__init__` freezes `self._store = credential_store or
VaultUtilsCredentialStore()`. navigator-auth publishes `app["authdb"]` only from
its `on_startup` signal, so anything built in `configure()` sees `authdb is None`.
Pass a store that resolves the pool on first use:

```python
class LazyIdentityVaultCredentialStore:          # satisfies parrot.auth.oauth2_base.CredentialStore
    def __init__(self, app, pool_key="authdb"): ...
    def _resolve(self):
        pool = self._app.get(self._pool_key)
        if pool is None:
            raise CredentialPersistenceError("Identity Vault unavailable: app['authdb'] is not bound")
        self._delegate = self._delegate or IdentityVaultCredentialStore(pool)
        return self._delegate
    async def load(self, user_id, provider): return await self._resolve().load(user_id, provider)
    async def save(self, user_id, provider, payload, *, minted, principal, state_payload): ...
    async def delete(self, user_id, provider): ...
```

Raising (fail closed) is deliberate: a silent fallback is exactly the upstream bug.

### 4.2 Build O365 *before* `BotManager.setup()`

`BotManager._register_o365_oauth2_provider` reuses an existing
`app['oauth2_manager_o365']`; if absent it builds one with
`credential_store=None`. Pre-building it is the only way to give it the vault store.
`_register_oauth2_providers` (startup) attaches the connection event publisher later.

### 4.3 Build Jira *after* `BotManager.setup()`

`JiraOAuthManager` needs `app['redis']` (published by `BotManager`) and should
receive `event_publisher=app['connection_event_publisher']` explicitly — the startup
hook only registers `JiraOAuth2Provider` when `app['jira_oauth_manager']` exists; it
does not wire the publisher.

### 4.4 Permission context is the identity carrier

`AbstractBot.ask()` sets `client._permission_context`; `AbstractClient` forwards it
to `ToolManager.execute_tool(permission_context=…)`, which injects
`_permission_context` into the toolkit's `_pre_execute`. `credential_channel_user_id()`
turns it into the lookup id (Teams uses `channel_user_id`, everyone else `user_id`).
A toolkit called outside that path raises `AuthorizationRequired("Permission
context is required…")` — that is correct fail-closed behaviour, not a bug.

### 4.5 Same origin for UI and callback

`web_oauth_success.html` posts `{type:"ai-parrot-oauth-callback", …}` to
`return_origin`; `ui/src/lib/oauth/popup.ts` drops any message whose
`event.origin !== window.location.origin`. Browse the UI through the same host the
IdP redirects to (the tunnel), or the popup result is ignored and only the SSE
refresh updates the panel (`IntegrationsMenu` refreshes only on toggle).

---

## 5. Reference harness

Repository: `git@github.com:phenobarbital/parrot-external-auth.git` (private),
local checkout `~/proyectos/parrot/parrot-external-auth`.

| Path | Role |
|---|---|
| `run.py`, `app.py` | the bootstrap of §2, plus `GET /e2e/wiring` (secret-free diagnostic: providers, store class per manager, `authdb`, `abac`, SSE push, redirect URIs, allowed origins) |
| `vault_store.py` | `LazyIdentityVaultCredentialStore` (§4.1) |
| `agents/external_auth_agent.py` | agent `external_auth` — 41 Jira tools + 6 O365 tools, model `EXTERNAL_AUTH_MODEL` |
| `policies/` | `defaults.yaml`, `connections.yaml` (+ `integration:use`), `superusers.yaml` |
| `tests/test_wiring.py` | offline: lazy store contract, policy files |
| `tests/live/test_live_connections.py` | `PARROT_LIVE_E2E=1`: login → list → `/start` (auth_url with `state`) → unlisted origin → 400 → SSE handshake → chat turn yields `auth_required` or delegated data |
| `scripts/evidence.py` | vault rows / Redis keys / `users_integrations` for one user, tokens redacted |
| `docs/E2E_WALKTHROUGH.md` | the 10-step manual script (login, menu, pill, Jira consent, auto-retry, Account › Connections, O365, restart survival, disconnect, manual retry) |

Run: `make infra` (docker `docker_postgres_1`, `docker_redis_1`, `documentdb`) →
`make tunnel` (`ngrok http --url=<host> 5055`) → `make run` → browse
`https://<tunnel-host>/login` → `make test-live` → `make evidence USER_ID=<id>`.

Startup state verified on 2026-11-02: `providers: ['jira','o365']`, both managers
on `LazyIdentityVaultCredentialStore`, `authdb/abac/connection_push: true`,
`/api/v1/connections` → 401 without a session, agent wired with both toolkits.
The browser consent steps were not yet executed (need the tunnel + IdP consent).

What each walkthrough step proves:

| Step | Evidence |
|---|---|
| Connect pill on a Jira question | `auth_required` envelope / `\x00` trailer with `provider`, `retry_safe`, `turn_id` |
| Jira consent | `auth.user_identities` row (`auth_provider=jira`, `key_version` = active key), `oauth2:jira:<id>` in Redis db 4, `users_integrations` row, SSE `connection.completed` |
| Restart after `DEL oauth2:jira:<id>` | answer without re-consent → Identity Vault is the durable owner |
| Disconnect | vault row disabled/removed, Redis key gone, SSE `connection.revoked`, pill returns |
| Action-before-Jira message | `retry_safe=false` → manual **Retry** with the repeat warning |

---

## 6. Gaps found (ledger)

| Issue | Severity | Summary |
|---|---|---|
| `issue:4137bc2e311f` | major, bug | Identity Vault store never bound upstream — managers freeze `_store` before `app['authdb']` exists (`BotManager._register_o365_oauth2_provider`, root `app.py` Jira). Workaround §4.1. |
| `issue:9b625450ce4a` | major, feature_gap | Jira provider never registered for web; only Slack/Teams bot configs or `OAUTH2_PROVIDERS_FILE` (generic manager, no toolkit factory). `JIRA_CLIENT_ID/_SECRET/_REDIRECT_URI` exist in `parrot.conf` but nothing reads them. |
| `issue:b7af2560406f` | major, bug | `AgentTalk._configure_tool_manager` passes no `user_id`/`agent_id`, so `UserObjectsHandler._hydrate_oauth_toolkits` never runs; agents must wire toolkits themselves. |

Observed but not yet filed:

* Web-path PBAC is a URI check: `IntegrationsService._check_pbac` calls
  `abac.is_allowed(request, {...})` with no resource, so `policies/connections.yaml`
  (`integration:*`) governs only Slack/Teams/CLI/Telegram; `allow_uri_authenticated`
  admits the web. `integration:use` is missing from the shipped `connections.yaml`.
* `IntegrationsMenu` ignores its `agent_id` prop and lists the user's connections
  (`GET /api/v1/connections`); `/api/v1/agents/integrations/{agent_id}` also ignores
  the id server-side. "Which integrations does *this* agent expose" is not modelled.
* `Connections.svelte` calls `connectionsStore.stop()` on destroy, which may leave
  AgentChat without the SSE reader after visiting Account › Connections (unverified).
* Local `navigator.ai_bots` lacking `enable_suggestions` logs an ERROR at agent
  startup; harmless for Python-defined agents.

---

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `/api/v1/connections/{p}/start` → 400 `invalid_origin` | `return_origin` not in `WEB_OAUTH_ALLOWED_ORIGINS` |
| `/api/v1/connections/events` → 503 | `app['connection_push']` missing: Redis unreachable at `BotManager._setup_connection_push` |
| Every connect → 403 | no `app['abac']` (policy dir missing / navigator-auth ABAC import failed) → fail closed |
| Popup closes but the menu still says *Not connected* | origin mismatch (§4.5); check `GET /api/v1/connections` after a manual refresh |
| Tool returns "Permission context is required" | call did not go through `bot.ask()` → `ToolManager.execute_tool` (§4.4) |
| Grant saved but `auth.user_identities` empty | manager on `VaultUtilsCredentialStore` (issue `4137bc2e311f`); check `GET /e2e/wiring` |
| `uv sync` fails: "Multiple top-level packages discovered" | flat app layout; set `[tool.uv] package = false` |
