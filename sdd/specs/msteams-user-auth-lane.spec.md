---
type: feature
base_branch: dev
projects: [ai-parrot-integrations, ai-parrot, ai-parrot-server]
tags: [msteams, authentication, identity, token-exchange]
---

# Feature Specification: MS Teams user authentication lane

**Feature ID**: FEAT-729
**Date**: 2026-10-22
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.3.0

> **Inputs:** no brainstorm or proposal exists for this slug (§9). The spec is
> seeded by a **working proof of concept built in-session on 2026-10-22**: the
> Azure→Navigator token exchange was driven end to end with a real delegated
> Graph token and returned `HTTP 200` plus a live Navigator session. Every
> claim below is runtime- or source-verified at the commit named in §6, never
> inferred. The PoC scripts and the successful run log are preserved under
> `sdd/state/FEAT-729/poc/`.

---

## 1. Motivation & Business Requirements

### Problem Statement

**An agent on MS Teams does not know who it is talking to.** The
`integrations/msteams/` lane never authenticates the speaking user. The
wrapper has no `UserContext`, never calls `AbstractBot.post_login` and never
clones per user; the only identity it forwards into the agent is the raw Teams
channel id, as `{"user_id": turn_context.activity.from_property.id}`
(`wrapper.py:460`, `:675`, `:1025`). There is no `/login` command — the
registered commands are jira, agent and knowledge_upload only. Consequently no
Teams conversation can carry a Navigator principal, and nothing downstream that
keys on one (RLS, PBAC, per-user credentials, dataset guards) can work from
Teams.

Telegram, by contrast, already has the whole stack: `TelegramUserSession`
(`telegram/auth.py:44`), `NavigatorAuthClient` (`:227`), an
`AbstractAuthStrategy` hierarchy with Basic / Azure / Google / OAuth2 /
Composite strategies, and a post-auth chain. MS Teams has none of it.

**The missing link is not identity — it is a user-bound credential.** Three
facts, all proven in the PoC:

**(a) The identity is already available, and already used.** A Teams activity
carries `from_property.aad_object_id` (the Entra `oid`), `from_property.id`,
`from_property.name` and `channel_data.tenant.id`; `TeamsInfo.get_member()`
returns a `TeamsChannelAccount` with `email` and `user_principal_name`. Both
paths are in production use today — `_get_user_id`
(`msteams/commands/jira_commands.py:116`) prefers `aad_object_id` and falls back
to `from_property.id`, and `TeamsKnowledgeUpload.resolve_email`
(`msteams/commands/knowledge_upload.py:115`) reads `email or
user_principal_name`. But this is an **assertion by Teams obtained with the
bot's own credentials**: good enough to attribute a message, not a
proof-of-possession that any other API will accept.

**(b) navigator-auth already accepts an external credential — and nothing
calls it.** `TokenExchangeAuth` (`navigator_auth/backends/exchange.py:31`,
FEAT-096) exchanges an already-issued provider bearer for a Navigator session
"as if Basic", with no password and no browser redirect. A repo-wide grep for
`TokenExchangeAuth` returns **zero** hits in `packages/` (§6 Does NOT Exist).
It is also **not enabled** on the running deployment: `GET
/api/v1/auth/methods` on the live service lists only `ADFSAuth`, `AzureAuth`,
`BasicAuth`, `NoAuth`, and a `POST /api/v1/login` with
`X-Auth-Method: TokenExchangeAuth` returns `401 Unacceptable Auth Method`
(§6 Measurement evidence).

**(c) The exchange works, and its output closes the loop.** Driven with a real
delegated Graph access token for `jlara@trocglobal.com` against an app with
`AzureAuth` + `TokenExchangeAuth` loaded, the exchange returned `HTTP 200` and a
session whose `provider_user_id` is `4e2aa0ea-56b8-49fe-85cf-05e97d479ba6` —
**the Entra `oid`, i.e. exactly the value `from_property.aad_object_id` yields
in Teams**. `resolve_user_id` (`parrot/auth/session_identity.py:90`) then
returned the canonical `"35"`. That identity equality is the whole bridge: the
channel hands us the `oid`, the exchange hands us a Navigator session keyed by
the same `oid`.

**Secondary problem, found while proving (c): the identity-mapping writes are
broken in all three integrations.** `IdentityMappingService`
(`ai-parrot-server/src/parrot/services/identity_mapping.py:76`) upserts with
`ON CONFLICT (user_id, auth_provider)` (`:26`), but **neither** the live
`auth.user_identities` table **nor** the canonical DDL
(`../navigator-auth/examples/sql/identity_vault_schema.sql:58-75`) carries a
*unique* index on that pair — only the non-unique `idx_user_identities_user`.
That is SQLSTATE 42P10 on every call. Its `SELECT` also names
`identity_id, display_name, email`, which the live table lacks entirely. All
four call sites wrap the call in `except Exception: logger.exception(...)` with
the comment *"identity write must not break browser flow"*
(`msteams/oauth_callback.py:246-263`, `slack/oauth_callback.py:230`,
`telegram/post_auth_jira.py:254` and `:271`), so the Jira 3LO flow reports
success to the user while persisting nothing.

### Goals

- **G1** — Obtain a **user-bound** delegated Graph credential for the speaking
  Teams user, through the Bot Framework Token Service the installed
  `BotFrameworkAdapter` already exposes.
- **G2** — Exchange that credential for a Navigator session via
  `TokenExchangeAuth`, and resolve the canonical Navigator user id with
  `resolve_user_id`.
- **G3** — Make the resolved principal reach the agent: build a `UserContext`
  and drive `AbstractBot.post_login` / `clone_for_user`, as the Telegram lane
  does, so per-user isolation and credential binding work from Teams.
- **G4** — Give the user explicit control: `/login`, `/logout` and `/whoami`
  commands, and an `OAuthCard` sign-in when no token is on file.
- **G5** — Replace `IdentityMappingService` with navigator-auth's
  `IdentityStore`, fixing the 42P10 defect for the existing msteams / slack /
  telegram Jira callers and getting ciphered token storage instead of cleartext
  JSONB.
- **G6** — Fail closed and legibly: an unauthenticated user gets a sign-in
  prompt, never a silently-degraded "anonymous" agent turn.

### Non-Goals (explicitly out of scope)

- **Implementing an OBO exchange by hand.** Not needed: the adapter's
  `exchange_token()` (`verified: botbuilder.core.BotFrameworkAdapter`, §6)
  performs the Teams SSO token exchange through the Token Service. The unused
  `obo_scopes` plumbing in `msagentsdk` (`msagentsdk/wrapper.py:140`) stays
  unused and untouched — removing it is separate work.
- **Wiring the `msagentsdk` lane.** It already fetches per-user tokens
  (`BFTokenServiceResolver._fetch_token`, `msagentsdk/auth.py:175`) and routes
  `signin/*` invokes. This feature targets the classic `msteams` lane, which has
  none of that; adopting the shared session + exchange client there is
  follow-up.
- **Reconciling the `auth.user_identities` base table.** That lands in
  navigator-auth FEAT-103 Module 0 (§7 External Dependencies). This spec
  consumes the fixed schema; it does not migrate it.
- **Enabling `TokenExchangeAuth` in production config.** An ops change
  (`AUTHENTICATION_BACKENDS`), documented in §7, not code in this repo.
- **Changing the Entra token lifetime or the session cap.** The Navigator
  session is capped to the external token's remaining life by
  `_cap_expiration`; a short token yields a short session, by design.
- Porting `/login` to Slack. The strategy is written channel-agnostically where
  cheap, but only Teams is wired here.

---

## 2. Architectural Design

### Overview

Three seams, each at the layer that owns it.

1. **Credential acquisition stays in the channel.** The Bot Framework Token
   Service is the only party that can hand us a user-bound token for a Teams
   user, and the installed `BotFrameworkAdapter` already speaks to it:
   `get_user_token`, `exchange_token`, `get_oauth_sign_in_link`,
   `get_token_status`, `sign_out_user`. `OAuthPrompt` is likewise already
   installed. So no new SDK and no hand-rolled OAuth: `MSTeamsAuthStrategy`
   asks the adapter, and emits an `OAuthCard` when the answer is "no token".
2. **The exchange is channel-agnostic, so it lives in core.**
   `parrot/auth/token_exchange.py` holds a `TokenExchangeClient` that knows one
   thing: `POST {auth_url}` with `X-Auth-Method: TokenExchangeAuth` and
   `{"provider", "token", "token_type", "id_token"?}`. Telegram and Slack can
   adopt it unchanged. It mirrors `NavigatorAuthClient.login`
   (`telegram/auth.py:249`) including its `NAVIGATOR_SSL_VERIFY` handling.
3. **The session mirrors Telegram's, because that shape is proven.**
   `MSTeamsUserSession` carries the Navigator identity plus the per-user
   isolation state (`tool_manager`, `user_agent`, `post_login_ran`) that
   `TelegramUserSession` already uses for the two agent-sharing modes.

Resolved design points, from the PoC rather than from preference:

- **Prefer `id_token` when the Token Service returns one.** With an access
  token alone, `AzureAuth._verify_access_token` (`azure.py:447`) checks only
  `aud` ∈ {`AZURE_ADFS_CLIENT_ID`, `https://graph.microsoft.com`,
  `00000003-0000-0000-c000-000000000000`}, `appid`/`azp` ∈
  `_AZURE_TRUSTED_APPIDS` (`azure.py:46`) and `exp` — and then **tolerates a
  failed signature check** (`azure.py:476-488`, warning only). Observed with a
  real Microsoft token: `JWT rejected: Signature verification failed` →
  tolerated → the Graph `/me` call was the only real gate. Sending the
  `id_token` gets full JWKS verification against `AZURE_ADFS_CLIENT_ID`.
- **`aad_object_id` is the session key, not `from_property.id`.** It equals the
  exchange's `provider_user_id`, so the same key addresses the user on both
  sides. Fall back to `from_property.id` only when `aad_object_id` is absent,
  exactly as `_get_user_id` already does.
- **A user missing from `auth.users` is a first-class outcome, not an error.**
  The exchange never provisions (decision D4, `exchange.py:171-183`): no row
  means `401` with `reason=user_not_found`. The user must see "your account is
  not provisioned in Navigator", not "login failed".
- **`IdentityStore` replaces `IdentityMappingService` rather than being wrapped
  around it.** `TokenExchangeAuth` itself writes through `IdentityStore`
  (`exchange.py:188`), so a second writer on one table invites drift; and the
  service's stated reason for raw SQL — *"the `UserIdentity` ORM model is not
  always importable from ai-parrot"* — is false in this venv, where the PoC
  imported `AuthHandler`, `IdentityStore` and `navigator_auth.conf` directly.

### Component Diagram

```
Teams activity (from_property.aad_object_id = Entra oid)
  │
  ├─ MSTeamsCommandRouter  "/login" | "/logout" | "/whoami"      [M4]
  │       │
  ▼       ▼
MSTeamsAuthStrategy                                              [M3]
  │  adapter.get_user_token(ctx, connection_name, magic_code)
  │  adapter.exchange_token(ctx, conn, user_id, TokenExchangeRequest)   ← Teams SSO
  │  adapter.get_oauth_sign_in_link(...) / OAuthCard                    ← no token yet
  │  on_invoke: signin/verifyState · signin/tokenExchange
  ▼
TokenExchangeClient.exchange(provider="azure", token, id_token)   [M2]
  │  POST /api/v1/login   X-Auth-Method: TokenExchangeAuth
  ▼
navigator-auth  TokenExchangeAuth → AzureAuth.verify_external_token
  │               → Graph /me → IdentityStore.find_user_by_provider_account
  │               → BasicAuth.open_session (capped to token exp)
  ▼
MSTeamsUserSession{nav_user_id, nav_session_token, …}             [M1]
  │  resolve_user_id(request, session) → canonical nav id
  ▼
UserContext(channel="msteams", user_id=nav_user_id, email, session_id)
  │
  ▼
AbstractBot.post_login(ctx) / clone_for_user(ctx)                 [M5]
```

### Integration Points

| Touch point | Existing symbol | Verified at | Change |
|---|---|---|---|
| Command routing | `MSTeamsCommandRouter.register` | `msteams/commands/__init__.py:56` | register `/login`, `/logout`, `/whoami` |
| Turn handling | `MSTeamsAgentWrapper.on_message_activity` | `msteams/wrapper.py:554` | resolve session before dispatch |
| Authorization | `MSTeamsAgentWrapper._is_authorized` | `msteams/wrapper.py:311` | unchanged; runs before auth |
| Per-user agent | `AbstractBot.post_login` / `clone_for_user` | `bots/abstract.py:4561` / `:4583` | called with the new `UserContext` |
| Identity snapshot | `UserContext` | `auth/context.py:39` | `channel="msteams"` |
| Canonical id | `resolve_user_id` | `auth/session_identity.py:90` | reused as-is |
| Jira 3LO persistence | `handle_msteams_jira_callback` | `msteams/oauth_callback.py:173` | swap service for `IdentityStore` |
| Config | `MSTeamsAgentConfig` | `msteams/models.py:16` | add auth fields |

### Data Models

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py  (new)
@dataclass
class MSTeamsUserSession:
    """Cached Navigator identity for one Teams user.

    Keyed by ``aad_object_id`` when present, else ``from_property.id`` —
    the same precedence as _get_user_id (verified: jira_commands.py:116).
    """
    teams_user_id: str
    aad_object_id: Optional[str] = None
    tenant_id: Optional[str] = None
    display_name: Optional[str] = None
    upn: Optional[str] = None
    # Populated by the exchange:
    nav_user_id: Optional[str] = None
    nav_session_token: Optional[str] = None
    nav_email: Optional[str] = None
    authenticated: bool = False
    authenticated_at: Optional[datetime] = None
    external_expires_at: Optional[datetime] = None
    provider_user_id: Optional[str] = None
    # Per-user isolation, process-local, excluded from repr
    # (pattern verified: telegram/auth.py:44 TelegramUserSession).
    tool_manager: Optional[Any] = field(default=None, repr=False)
    user_agent: Optional[Any] = field(default=None, repr=False)
    post_login_ran: bool = field(default=False, repr=False)
```

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/auth/token_exchange.py  (new)
class TokenExchangeResult(BaseModel):
    """Outcome of one TokenExchangeAuth call."""
    ok: bool
    nav_user_id: Optional[str]
    nav_session_token: Optional[str]
    email: Optional[str]
    provider_user_id: Optional[str]
    external_expires_at: Optional[datetime]
    reason: Optional[str]   # "user_not_found" | "invalid_token" | "backend_not_loaded" | …

class TokenExchangeClient:
    """Exchange a provider bearer for a Navigator session (FEAT-096)."""
    def __init__(self, auth_url: str, timeout: int = 15) -> None: ...
    async def exchange(
        self,
        *,
        provider: str,
        token: str,
        token_type: str = "Bearer",
        id_token: Optional[str] = None,
    ) -> TokenExchangeResult:
        """POST the bearer to navigator-auth and return the session.

        Sends ``X-Auth-Method: TokenExchangeAuth`` with
        ``{"provider", "token", "token_type", "id_token"?}``.
        Maps 401 ``user_not_found`` to a distinct ``reason`` so callers can
        tell "not provisioned" from "bad token" — the exchange never
        provisions a user (verified: exchange.py:171-183).
        """
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: `MSTeamsUserSession` + store | yes | dataclass fields fixed in §2 Data Models; mirror `telegram/auth.py:44` | — |
| M2: `TokenExchangeClient` | yes | signatures in §2; headers/body fixed; mirror `telegram/auth.py:249` | — |
| M3: `MSTeamsAuthStrategy` | no | which adapter call wins per channel state (SSO vs OAuthCard) is a design call | invoke-routing order |
| M4: commands | yes | router API verified `commands/__init__.py:56`; card shape mirrors `_connect_jira_card` | — |
| M5: wrapper wiring | no | where in `on_message_activity` to gate, and fail-closed semantics | turn-flow decision |
| M6: `IdentityStore` adoption | no | four call sites with differing payloads; semantic change one→many per provider | caller-by-caller review |
| M7: tests | yes | fixtures and table fixed in §4 | — |

### Module 1: Teams user session
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py` (new)
- **Responsibility**: the `MSTeamsUserSession` dataclass of §2 plus an in-process
  store keyed by `(agent_name, user_key)`, where `user_key` is
  `aad_object_id or from_property.id`. Holds the per-user isolation slots so a
  `singleton_agent=True` deployment cannot leak credential state across users.
- **Depends on**: nothing in this spec.
- **Interface Skeleton**:
  ```python
  # msteams/auth.py  (new)
  def user_key(turn_context: TurnContext) -> str:
      """Return aad_object_id, else from_property.id.

      Same precedence as _get_user_id  # verified: msteams/commands/jira_commands.py:116
      """

  class MSTeamsSessionStore:
      """Process-local sessions for one agent's Teams users."""
      def get_or_create(self, turn_context: TurnContext) -> MSTeamsUserSession: ...
      def clear(self, key: str) -> None:
          """Drop the session (logout); never raises on a missing key."""
      def is_expired(self, session: MSTeamsUserSession) -> bool:
          """True when external_expires_at has passed."""
  ```

### Module 2: Navigator token-exchange client
- **Path**: `packages/ai-parrot/src/parrot/auth/token_exchange.py` (new)
- **Responsibility**: the single caller of `TokenExchangeAuth`. Channel-agnostic
  and in core so Telegram/Slack can adopt it. Honours `NAVIGATOR_SSL_VERIFY`
  the way `NavigatorAuthClient` does (`telegram/auth.py:240-247`). Uses
  `aiohttp`, never `requests`/`httpx`.
- **Depends on**: nothing in this spec.
- **Interface Skeleton**: as §2 New Public Interfaces.

### Module 3: MS Teams auth strategy
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py`
- **Responsibility**: acquire a user-bound Graph credential and drive the
  exchange. Order: a cached unexpired session wins; else
  `adapter.get_user_token`; else, on a `signin/tokenExchange` invoke,
  `adapter.exchange_token`; else emit an `OAuthCard` / sign-in link and return
  "needs auth". Then call M2 and populate the M1 session.
- **Depends on**: M1, M2.
- **Interface Skeleton**:
  ```python
  # msteams/auth.py
  class MSTeamsAuthStrategy:
      """Bot Framework Token Service → Navigator session."""
      def __init__(self, config: MSTeamsAgentConfig, store: MSTeamsSessionStore,
                   exchange: TokenExchangeClient) -> None: ...

      async def ensure_authenticated(self, turn_context: TurnContext) -> MSTeamsUserSession:
          """Return an authenticated session, or one with authenticated=False.

          Never raises for an unauthenticated user: the caller decides whether
          to prompt. Emits no card itself.
          """

      async def fetch_provider_token(self, turn_context: TurnContext) -> Optional[TokenResponse]:
          """adapter.get_user_token(context, connection_name, magic_code=None).

          # verified signature: BotFrameworkAdapter.get_user_token(
          #   self, context, connection_name: str, magic_code: str = None,
          #   oauth_app_credentials: AppCredentials = None) -> TokenResponse
          """

      async def exchange_sso_token(self, turn_context: TurnContext,
                                   exchange_request: TokenExchangeRequest) -> Optional[TokenResponse]:
          """adapter.exchange_token(ctx, connection_name, user_id, exchange_request).

          The Teams SSO path; replaces a hand-written OBO.
          # verified: BotFrameworkAdapter.exchange_token(self, turn_context,
          #   connection_name: str, user_id: str, exchange_request) -> TokenResponse
          """

      async def send_signin_card(self, turn_context: TurnContext) -> None:
          """OAuthCard via adapter.get_oauth_sign_in_link(...)."""
  ```

### Module 4: `/login`, `/logout`, `/whoami` commands
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/auth_commands.py` (new)
- **Responsibility**: user-facing control, registered on the existing router.
  `/whoami` reports the Navigator id, email and session expiry — the PoC's
  `whoami` probe, surfaced in Teams. Distinguish `user_not_found` ("not
  provisioned in Navigator") from a bad token in the reply text.
- **Depends on**: M3.
- **Interface Skeleton**:
  ```python
  # msteams/commands/auth_commands.py  (new)
  def register_auth_commands(router: "MSTeamsCommandRouter",
                             strategy: "MSTeamsAuthStrategy") -> None:
      """Register /login, /logout, /whoami.

      # verified: MSTeamsCommandRouter.register  msteams/commands/__init__.py:56
      # pattern:  register_jira_commands          msteams/commands/jira_commands.py:300
      """
  ```

### Module 5: Wrapper wiring — `UserContext` and `post_login`
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py`,
  `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py`
- **Responsibility**: in `on_message_activity`, after `_is_authorized`, resolve
  the session through M3; build a `UserContext(channel="msteams", …)`; call
  `post_login` once per session (`post_login_ran` guard) and `clone_for_user`
  for the non-singleton mode; replace the three `{"user_id": …}` context dicts
  with the Navigator id when authenticated. Add the auth fields to
  `MSTeamsAgentConfig` (`oauth_connection_name`, `auth_required`,
  `navigator_auth_url`, `prefer_id_token`).
- **Depends on**: M1, M3.
- **Interface Skeleton**:
  ```python
  # msteams/wrapper.py  (modifies msteams/wrapper.py:554)
  async def on_message_activity(self, turn_context: TurnContext):
      """Handle incoming messages including voice notes.

      Adds, after the _is_authorized gate (verified: wrapper.py:311):
      session = await self._auth.ensure_authenticated(turn_context)
      when config.auth_required and not session.authenticated → sign-in card, return
      """

  # msteams/models.py  (modifies msteams/models.py:16)
  class MSTeamsAgentConfig:
      oauth_connection_name: Optional[str] = None  # Azure Bot OAuth connection
      auth_required: bool = False                  # fail closed when True (G6)
      navigator_auth_url: Optional[str] = None
      prefer_id_token: bool = True                 # strong JWKS path (§2)
  ```

### Module 6: Retire `IdentityMappingService` for `IdentityStore`
- **Path**: `packages/ai-parrot-server/src/parrot/services/identity_mapping.py`,
  `packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py`,
  `.../slack/oauth_callback.py`, `.../telegram/post_auth_jira.py`,
  `.../telegram/wrapper.py`
- **Responsibility**: route the four `upsert_identity` call sites through
  `IdentityStore` and delete the broken raw SQL. Each call site currently
  swallows the 42P10 in `except Exception: logger.exception(...)`, so the fix is
  only observable with a test that asserts the row lands.
- **Depends on**: navigator-auth FEAT-103 Module 0 for the reconciled table
  (§7). Independent of M1-M5.
- **Caller-by-caller decisions required** (why this is not delegation-eligible):
  the service's one-row-per-`(user, provider)` assumption becomes
  one-row-per-`provider_user_id` under `IdentityStore`, and
  `msteams/oauth_callback.py:250` currently passes
  `auth_data={"aad_object_id": nav_user_id}` — conflating the Navigator id with
  the Entra `oid`. Each site needs its payload re-derived, not mechanically
  translated.
- **Interface Skeleton**:
  ```python
  # services/identity_mapping.py  (modifies services/identity_mapping.py:76)
  class IdentityMappingService:
      """Thin adapter over navigator-auth's IdentityStore.

      The raw-SQL upsert is removed: its ON CONFLICT (user_id, auth_provider)
      has no matching unique index in either schema (42P10) — see §1.
      # verified: IdentityStore.save_linked_identity  navigator_auth/identity/store.py:112
      # verified: IdentityStore.get_by_provider        navigator_auth/identity/store.py:222
      """
      def __init__(self, db_pool: Any) -> None: ...
      async def upsert_identity(self, *, nav_user_id: str, auth_provider: str,
                                auth_data: dict, display_name: Optional[str] = None,
                                email: Optional[str] = None) -> None:
          """Kept signature-compatible so the four call sites need no rewrite."""
  ```

### Module 7: Tests
- **Path**: `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_lane.py` (new),
  `packages/ai-parrot/tests/unit/test_token_exchange_client.py` (new),
  `packages/ai-parrot/tests/unit/test_identity_mapping.py` (extend)
- **Responsibility**: §4.
- **Depends on**: M1-M6.

---

## 4. Test Specification

### Unit Tests

| Test | Asserts |
|---|---|
| `test_user_key_prefers_aad_object_id` | `user_key()` returns `aad_object_id`; falls back to `from_property.id` when absent |
| `test_exchange_sends_token_exchange_header` | the POST carries `X-Auth-Method: TokenExchangeAuth` and the four body keys |
| `test_exchange_maps_user_not_found` | a 401 whose body/log says `user_not_found` yields `reason="user_not_found"`, not `invalid_token` |
| `test_exchange_maps_unacceptable_auth_method` | the live-deployment failure (`401 Unacceptable Auth Method`) maps to `reason="backend_not_loaded"` |
| `test_exchange_prefers_id_token` | with `prefer_id_token=True` and an id_token present, `id_token` is in the body |
| `test_session_expires_with_external_token` | `is_expired()` follows `external_expires_at`, not wall-clock session age |
| `test_ensure_authenticated_returns_unauthenticated` | no token on file ⇒ `authenticated=False`, no exception, no card sent by the strategy |
| `test_post_login_runs_once` | two turns for one user call `post_login` once (`post_login_ran` guard) |
| `test_auth_required_fails_closed` | `auth_required=True` + unauthenticated ⇒ sign-in card, agent never invoked (G6) |
| `test_identity_store_row_lands` | `upsert_identity` writes a readable row via `IdentityStore` — the assertion the old `except Exception` hid |

### Integration Tests

| Test | Asserts |
|---|---|
| `test_login_command_end_to_end` | `/login` → token fetched from a fake adapter → exchange → session authenticated → `/whoami` reports the nav id |
| `test_signin_token_exchange_invoke` | a `signin/tokenExchange` invoke routes to `exchange_token` and completes the session |
| `test_jira_callback_persists_identity` | `handle_msteams_jira_callback` leaves a real row (regression for the swallowed 42P10) |

### Validation Contract

tests:
- packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_session_store.py
- packages/ai-parrot/tests/unit/test_token_exchange_client.py
- packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_strategy.py
- packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_commands.py
- packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_gate.py
- packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_lane.py
- packages/ai-parrot/tests/unit/test_identity_mapping.py
- packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_oauth_callback.py
- packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_jira_commands.py
- packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_authorization.py
markers: none

> One test file per task — `check_task_graph`'s `file-overlap` is an error, so
> two tasks may never declare the same file. `test_msteams_auth_lane.py` holds
> the three integration tests only; each module's unit tests live beside it in
> the per-module file above.

### Test Data / Fixtures

```python
# Reuse the PoC's synthetic activity verbatim — it is already proven to drive
# the real _get_user_id and resolve_email (sdd/state/FEAT-729/poc/).
TEAMS_OID = "7c8f1d2e-3b4a-5c6d-7e8f-9a0b1c2d3e4f"
TENANT_ID = "11112222-3333-4444-5555-666677778888"

@pytest.fixture
def teams_activity() -> Activity:
    """Activity with aad_object_id, tenant and a Teams-scoped from id."""

@pytest.fixture
def fake_adapter():
    """Stubs get_user_token / exchange_token / get_oauth_sign_in_link.

    Signatures must match BotFrameworkAdapter exactly (§6) or the test
    passes against a shape the real adapter does not have.
    """

@pytest.fixture
def exchange_response_200() -> dict:
    """The PoC's real 200 body, redacted: user_id 35, auth_origin azure,
    provider_user_id == TEAMS_OID (the identity equality of §1 (c))."""
```

No `real_llm` test is listed. No live Azure credential is required: the
exchange is stubbed at the `aiohttp` boundary in unit tests, and the one real
end-to-end run is recorded evidence in `sdd/state/FEAT-729/poc/`, not a test.

---

## 5. Acceptance Criteria

- [ ] A Teams user who runs `/login`, signs in through the `OAuthCard`, and
      returns, ends with `MSTeamsUserSession.authenticated=True` and a
      `nav_user_id` equal to `resolve_user_id`'s value for that account (G1, G2)
- [ ] `/whoami` reports the Navigator user id, email and session expiry (G4)
- [ ] The exchange request carries `X-Auth-Method: TokenExchangeAuth` and sends
      `id_token` whenever the Token Service returned one (G2, §2)
- [ ] With `auth_required=True`, an unauthenticated turn sends a sign-in card
      and never reaches the agent; with `auth_required=False` the turn proceeds
      unauthenticated exactly as today (G6)
- [ ] `AbstractBot.post_login` runs exactly once per authenticated session and
      receives a `UserContext` with `channel="msteams"`, the Navigator
      `user_id`, and the email (G3)
- [ ] A user absent from `auth.users` gets the "not provisioned" message, not a
      generic failure — asserted on `reason="user_not_found"` (G2, §2)
- [ ] `upsert_identity` writes a row that can be read back via `IdentityStore`
      for all four existing call sites; the old raw-SQL upsert is gone (G5)
- [ ] `pytest` over the §4 Validation Contract passes
- [ ] `ruff check` clean on every touched file; no `requests`/`httpx` import
      introduced (TID251)

---

## 6. Codebase Contract

> Verified against `dev` @ `37dc1da44` on 2026-10-22. navigator-auth symbols
> are from **`navigator_auth 0.28.7` installed from PyPI into `.venv`** — the
> package is **not** an editable install of `../navigator-auth`, so changes in
> that working tree do not reach this venv until a release (§7).

### Measurement evidence (2026-10-22, runtime)

The successful exchange, with secrets redacted
(`sdd/state/FEAT-729/poc/exchange_run.transcript.md`):

```
POST /api/v1/login   X-Auth-Method: TokenExchangeAuth   → HTTP 200
session: user_id=35  username=jlara@trocglobal.com  email=jlara@trocglobal.com
         auth_method=basic  auth_origin=azure
         provider_user_id=4e2aa0ea-56b8-49fe-85cf-05e97d479ba6   ← the Entra oid
GET /poc/whoami (Bearer <session token>) → {"nav_user_id": "35", ...}
TokenExchange: success provider=azure user_id=35 cap=89
```

Three secondary observations from the same run, each shaping §2:

```
azure: JWT rejected: Signature verification failed
azure: access-token signature not independently verifiable
       (weaker path, appid/aud already matched): bad_signature
  → tolerated by design (azure.py:476-488); Graph /me is the real gate
cap=89  → the session was capped to the token's 89 remaining seconds
TokenExchange: vault write failed user_id=35:
  column "identity_id" does not exist     → navigator-auth FEAT-103 Module 0
```

The live deployment lacks the backend entirely:

```
GET  /api/v1/auth/methods  → {ADFSAuth, AzureAuth, BasicAuth, NoAuth}
POST /api/v1/login  X-Auth-Method: TokenExchangeAuth
     → 401 {"reason": "Unacceptable Auth Method: TokenExchangeAuth"}
```

Rejection matrix for `AzureAuth._verify_access_token`, all four executed:

| Token | Outcome |
|---|---|
| Teams SSO only (`aud: api://…/botid-…`) | `InvalidAuth(wrong_audience)` |
| Graph token, `appid` not in `_AZURE_TRUSTED_APPIDS` | `InvalidAuth(wrong_audience)` |
| Graph token, trusted appid, expired | `InvalidAuth(expired)` |
| Graph token, trusted appid, live | passes → Graph `/me` |

### Verified Imports

```python
from botbuilder.core import BotFrameworkAdapter, TurnContext          # installed
from botbuilder.core.teams import TeamsInfo                            # verified: msteams/commands/knowledge_upload.py:12
from botbuilder.schema.teams import TeamsChannelAccount                # installed
from botbuilder.dialogs.prompts import OAuthPrompt, OAuthPromptSettings  # installed
from botframework.connector.token_api.models import TokenExchangeRequest  # installed
from parrot.auth.context import UserContext                            # verified: parrot/auth/context.py:39
from parrot.auth.session_identity import resolve_user_id, resolve_session_user  # verified: :90, :56
from parrot.integrations.msteams.commands import MSTeamsCommandRouter  # verified: msteams/commands/__init__.py
from navigator_auth.identity.store import IdentityStore                # verified: navigator_auth/identity/store.py:49
```

### Existing Class Signatures

```python
# botbuilder.core.BotFrameworkAdapter  (installed; signatures read via inspect)
async def get_user_token(self, context: TurnContext, connection_name: str,
                         magic_code: str = None,
                         oauth_app_credentials: AppCredentials = None) -> TokenResponse
async def exchange_token(self, turn_context: TurnContext, connection_name: str,
                         user_id: str,
                         exchange_request: TokenExchangeRequest) -> TokenResponse
async def get_oauth_sign_in_link(self, context: TurnContext, connection_name: str,
                                 final_redirect: str = None,
                                 oauth_app_credentials: AppCredentials = None) -> str
async def get_token_status(self, context: TurnContext, connection_name: str = None,
                           user_id: str = None, include_filter: str = None,
                           oauth_app_credentials: AppCredentials = None) -> List[TokenStatus]
async def sign_out_user(...)
# also present: exchange_token_from_credentials, get_aad_tokens,
#   get_sign_in_resource, get_sign_in_resource_from_user[_and_credentials]

class OAuthPromptSettings:
    def __init__(self, connection_name: str, title: str, text: str = None,
                 timeout: int = None, oauth_app_credentials: AppCredentials = None,
                 end_on_invalid_message: bool = False)

# botbuilder.schema.ChannelAccount attributes: id, name, aad_object_id, role, properties
# botbuilder.schema.teams.TeamsChannelAccount attributes: id, name, given_name,
#   surname, email, user_principal_name, aad_object_id, tenant_id, user_role

# packages/ai-parrot-integrations/.../msteams/commands/jira_commands.py
def _get_user_id(turn_context: "TurnContext") -> str:  # line 116 — prefers aad_object_id

# packages/ai-parrot-integrations/.../msteams/commands/knowledge_upload.py
class TeamsKnowledgeUpload:                                      # line 59
    async def resolve_email(self, turn_context: TurnContext) -> Optional[str]:  # line 115

# packages/ai-parrot-integrations/.../msteams/commands/__init__.py
class MSTeamsCommandRouter:
    def register(self, command: str, handler: Callable) -> None:            # line 56
    async def try_dispatch(self, text: str, turn_context) -> bool:          # line 74

# packages/ai-parrot-integrations/.../msteams/wrapper.py
class MSTeamsAgentWrapper(ActivityHandler, MessageHandler):                 # line 94
    def _is_authorized(self, conversation_id: str, user_id: str) -> bool:   # line 311
    async def on_message_activity(self, turn_context: TurnContext):         # line 554

# packages/ai-parrot-integrations/.../telegram/auth.py   (the pattern to mirror)
class TelegramUserSession:                                                  # line 44
    def set_authenticated(self, nav_user_id, session_token, display_name, email)  # line 121
class NavigatorAuthClient:                                                  # line 227
    async def login(self, username: str, password: str) -> Optional[Dict]:  # line 249

# packages/ai-parrot/src/parrot/auth/context.py
@dataclass(frozen=True)
class UserContext:                                                          # line 39
    channel: str; user_id: str; display_name: Optional[str] = None
    email: Optional[str] = None; session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

# packages/ai-parrot/src/parrot/auth/session_identity.py
def resolve_session_user(request: Any) -> Any | None:                       # line 56
def resolve_user_id(request: Any, session: Any = None) -> str | None:       # line 90

# packages/ai-parrot/src/parrot/bots/abstract.py
async def post_login(...)                                                   # line 4561
def clone_for_user(...)                                                     # line 4583

# packages/ai-parrot-server/src/parrot/services/identity_mapping.py
class IdentityMappingService:                                               # line 76
    async def upsert_identity(self, ...)                                    # line 99
_UPSERT_SQL  # line 26 — "ON CONFLICT (user_id, auth_provider)"  ← 42P10, see §1

# .venv navigator_auth 0.28.7
class TokenExchangeAuth(BasicAuth):            # backends/exchange.py:31
@dataclass
class ExchangeRequest:                         # backends/exchange.py:22
    provider: str; token: str; token_type: str = "Bearer"; id_token: Optional[str] = None
async def verify_external_token(self, token, token_type="Bearer", id_token=None)  # backends/azure.py:490
async def _verify_access_token(self, access_token: str) -> dict                   # backends/azure.py:447
_AZURE_TRUSTED_APPIDS = frozenset({AZURE_ADFS_CLIENT_ID, *AZURE_TRUSTED_APPIDS})  # backends/azure.py:46
class IdentityStore:                                                              # identity/store.py:49
    async def save_linked_identity(...)                                           # identity/store.py:112
    async def get_by_provider(...)                                                # identity/store.py:222
    async def find_user_by_provider_account(...)                                  # identity/store.py:333
class UserIdentity(Model):                                                        # models.py:77
AUTHENTICATION_BACKENDS = tuple(...)                                              # conf.py:190
TOKEN_EXCHANGE_PROVIDERS = [...]   # default "azure,google,github"                # conf.py:570
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `MSTeamsAuthStrategy.fetch_provider_token` | `BotFrameworkAdapter.get_user_token()` | method call | installed signature, §6 |
| `MSTeamsAuthStrategy.exchange_sso_token` | `BotFrameworkAdapter.exchange_token()` | method call | installed signature, §6 |
| `TokenExchangeClient.exchange` | `TokenExchangeAuth.authenticate` | `POST /api/v1/login` | `backends/exchange.py:125` |
| `register_auth_commands` | `MSTeamsCommandRouter.register()` | method call | `msteams/commands/__init__.py:56` |
| wrapper auth gate | `MSTeamsAgentWrapper._is_authorized()` | runs after it | `msteams/wrapper.py:311` |
| `UserContext` build | `AbstractBot.post_login()` | method call | `bots/abstract.py:4561` |
| `IdentityMappingService.upsert_identity` | `IdentityStore.save_linked_identity()` | method call | `identity/store.py:112` |

### Does NOT Exist (Anti-Hallucination)

Each line below was confirmed to return **zero** non-test matches on
`dev @ 37dc1da44`:

- ~~`OAuthPrompt` used anywhere under `integrations/msteams/`~~ — 0 hits. It is
  installed in `botbuilder.dialogs.prompts`, just never used here.
- ~~`get_user_token` called anywhere under `integrations/msteams/`~~ — 0 hits
  (only `msagentsdk/auth.py:175` has it, a different lane).
- ~~`signin/tokenExchange` handled under `integrations/msteams/`~~ — 0 hits
  (only `msagentsdk/agent.py:240-242`).
- ~~`acquire_token_on_behalf_of` anywhere in `integrations/`~~ — 0 hits. **There
  is no OBO implementation**; `obo_scopes` is configured and stored but never
  read.
- ~~a `/login` command registered under `integrations/msteams/`~~ — 0 hits.
- ~~`MSTeamsUserSession`~~ — does not exist anywhere in `packages/`.
- ~~any caller of `TokenExchangeAuth`~~ — 0 hits in `packages/`. This feature
  writes the first one.
- ~~`X-Auth-Method: TokenExchange…` sent anywhere~~ — 0 hits.
- ~~`MSTeamsAgentWrapper.post_login` / `.clone_for_user` / any `UserContext`
  use in `msteams/`~~ — 0 hits; the lane is identity-blind today.
- ~~a unique index on `auth.user_identities (user_id, auth_provider)`~~ — absent
  from the live table **and** from the canonical DDL. Do not write an upsert
  that targets that pair.

Note: `packages/ai-parrot-integrations/build/lib/` holds a **stale duplicate**
of these modules. It is not the source tree; never edit or cite it.

### Edit Sites (Blueprint Anchors)

> Verified against `dev` @ `37dc1da44`. `/sdd-task` MUST re-run `grep -c` per row.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/auth_commands.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/auth/token_exchange.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | `    async def on_message_activity(self, turn_context: TurnContext):` | `wrapper.py:554` | 2 — line 718 is a commented-out `# async def on_message_activity(...)`; attach to the **uncommented** definition at 554 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` | MODIFY | `class MSTeamsAgentConfig` | `models.py:16` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py` | MODIFY | `    def register(self, command: str, handler: Callable) -> None:` | `commands/__init__.py:56` | 1 |
| `packages/ai-parrot-server/src/parrot/services/identity_mapping.py` | MODIFY | `class IdentityMappingService:` | `identity_mapping.py:76` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py` | MODIFY | `            await identity_service.upsert_identity(` | `oauth_callback.py:246` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py` | MODIFY | `            await identity_service.upsert_identity(` | `slack/oauth_callback.py:230` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py` | MODIFY | `            await self._identity.upsert_identity(` | `post_auth_jira.py:254` | 2 — also at 271; quote the enclosing method to disambiguate |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `                identity_service = IdentityMappingService(db_pool)` | `telegram/wrapper.py:601` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Mirror `telegram/auth.py` for the session and the HTTP client, including the
  `NAVIGATOR_SSL_VERIFY` handling (`telegram/auth.py:240-247`) and the
  `repr=False` on isolation slots so logs never dump agent internals.
- `aiohttp` only. `ruff` rule TID251 fails the task on `requests`/`httpx`.
- Google-style docstrings, strict type hints, 120 columns, `self.logger` never
  `print` (`.claude/rules/codebase-conventions.md`).
- Adaptive Cards go through `parrot.outputs.cards`; follow `_connect_jira_card`
  (`msteams/commands/jira_commands.py:39`) and use
  `DEFAULT_ADAPTIVE_CARD_VERSION`.
- Never log a token, not even truncated. The PoC redacts to
  `<redactado len=N>`; do the same.

### Known Risks / Gotchas

- **The one unproven link.** The PoC substituted a token from the Navigator
  Azure login for one from a Teams OAuth connection. What remains unverified is
  that the Azure Bot OAuth connection returns a token with a Graph `aud` and a
  trusted `appid`. Good sign: the token we exchanged had
  `appid == AZURE_ADFS_CLIENT_ID`, so configuring the connection on **that same
  app registration** needs no `AZURE_TRUSTED_APPIDS` change. The first task
  must verify this against a real connection before the rest is built on it.
- **Short sessions are expected.** `cap=89` was observed. A short-lived Entra
  access token yields a short Navigator session; `is_expired()` must drive
  re-acquisition, and the UX must not read as a bug. navigator-auth FEAT-103 G4
  (`get_live_provider_token`) is the upstream fix.
- **The weak verification path is load-bearing.** Real Graph access tokens fail
  independent signature verification and navigator-auth tolerates it. Sending
  `id_token` is the only way to get real cryptographic verification — hence
  `prefer_id_token=True` by default.
- **`user_not_found` is the most likely production failure.** The exchange never
  provisions. Any Teams user absent from `auth.users` fails no matter how valid
  the token.
- **Do not add a unique index** on `(user_id, auth_provider)` to make the old
  upsert work: it would forbid a user holding two accounts on one provider,
  which the canonical schema deliberately allows.
- **Stale `build/lib/` tree** shadows these modules in greps.

### External Dependencies

| Dependency | Version | Why | Status |
|---|---|---|---|
| `navigator-auth` | **≥ 0.28.8** | `TokenExchangeAuth` + the reconciled `auth.user_identities` from FEAT-103 Module 0 | **blocking** — `.venv` has 0.28.7 from PyPI, *not* editable from `../navigator-auth`; needs a release |
| `botbuilder-core` / `-dialogs` / `botframework-connector` | installed | adapter token API, `OAuthPrompt`, `TokenExchangeRequest` | ready, no change |
| `aiohttp` | installed | the exchange POST | ready |

**Ops prerequisites (not code in this repo):**

1. `AUTHENTICATION_BACKENDS` must gain
   `navigator_auth.backends.exchange.TokenExchangeAuth`. It belongs there, **not**
   in `AUTHORIZATION_BACKENDS` — the latter holds `BaseAuthzHandler` host/IP
   bypass backends (`allow_hosts`, `allowed_ips`, `azure_service_tags`,
   `powerbi`, `useragent`), which authorize a request *instead of*
   authenticating it.
2. An Azure Bot **OAuth connection** scoped to Graph, named in
   `MSTeamsAgentConfig.oauth_connection_name`.
3. `AZURE_TRUSTED_APPIDS` must list the bot's app id **only if** the connection
   uses a different app registration than `AZURE_ADFS_CLIENT_ID`.

**Cross-repo dependency:** navigator-auth FEAT-103
(`../navigator-auth/sdd/specs/external-provider-token-capture.spec.md`). Its
Module 0 was added on 2026-10-22 precisely because this PoC proved
`IdentityStore.save_linked_identity` cannot write on the current schema. M6
cannot be verified until that ships and is released.

---

## 8. Open Questions

- [ ] **Q1** — Does the Azure Bot OAuth connection return a token whose `aud` is
      Graph and whose `appid` is trusted? The single unproven link (§7). Decide
      whether to reuse `AZURE_ADFS_CLIENT_ID` for the connection (no config
      change) or register the bot separately (needs `AZURE_TRUSTED_APPIDS`).
      — *Owner: Jesus Lara*
- [x] **Q2** — Default for `auth_required`. — *Resolved 2026-10-23 by the
      user*: **`False`** — auth is opt-in. Every existing Teams deployment keeps
      behaving exactly as today after the upgrade, and a deployment that wants
      the gate sets it explicitly. The residual risk is accepted: a deployment
      that *should* gate stays open until someone sets the flag. → M5,
      `test_auth_required_fails_closed` asserts both directions.
- [x] **Q3** — Where does the Navigator session live? — *Resolved 2026-10-23
      by the user*: **a shared store, so it survives worker restarts**.

      **The premise of this question was wrong and is corrected here.**
      Telegram's session is *not* Redis-backed: `TelegramUserSession` is a plain
      dataclass held in an in-process dict (`telegram/wrapper.py:177`), and
      `telegram/auth.py:78` documents the three isolation slots as *"Kept
      process-local (no Redis serialization)"* because `tool_manager` and
      `user_agent` are live objects that cannot be serialized. So there is no
      "like Telegram" Redis pattern to mirror.

      **Resolution — hybrid, satisfying the intent without breaking that
      constraint:** the serializable auth fields persist through the existing
      injectable store of `IntegrationStateManager`
      (`integrations/core/state.py:61`, `set/get/delete(expire=)`, default
      `InMemoryStateStore`), while `tool_manager`, `user_agent` and
      `post_login_ran` stay process-local exactly as Telegram's do. TTL is
      derived from `external_expires_at` — never hard-coded, which is the defect
      the ledger already records against `AudioSessionStore`
      (`issue:d92b765f8c4d`). Accepted cost: the Navigator session token is at
      rest in the shared store for the token's remaining life (`cap=89` in the
      PoC, so typically minutes). → M1.
- [ ] **Q4** — M6 changes `IdentityMappingService` semantics from one row per
      `(user, provider)` to one per `provider_user_id`. Does any consumer rely
      on the old uniqueness? `telegram/post_auth_jira.py` has two call sites to
      check. — *Owner: Jesus Lara*
- [ ] **Q5** — Does production's `auth.user_identities` already carry
      `identity_id`? Only the dev database was inspected. If production is
      canonical, FEAT-103 Module 0 is a dev-only repair and M6 unblocks sooner.
      — *Owner: Jesus Lara*
- [x] **Which lane: classic `msteams` or `msagentsdk`?** — *Resolved
      2026-10-22 by verification, not preference*: the classic lane, because the
      installed `BotFrameworkAdapter` already exposes `get_user_token`,
      `exchange_token`, `get_oauth_sign_in_link`, `get_token_status` and
      `sign_out_user`, and `OAuthPrompt` is installed. No new SDK, and no
      hand-written OBO. → §2 item 1, M3, Non-Goals.
- [x] **`IdentityStore` or rewrite `IdentityMappingService`'s SQL?** —
      *Resolved 2026-10-22*: `IdentityStore`. The service's `ON CONFLICT` target
      has no matching unique index in **either** schema (42P10), `TokenExchangeAuth`
      already writes through `IdentityStore`, and that store ciphers tokens
      instead of storing cleartext JSONB. → G5, M6, §1.
- [x] **One spec or two (Teams lane vs `IdentityStore` migration)?** —
      *Resolved 2026-10-22 by the user*: one spec. The migration is small and
      the Teams lane is its first real consumer. → M6 in this spec.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `n/a` · Status: skipped (no exploration
> document exists for this slug — the spec was seeded from an in-session proof
> of concept, so §3b's precondition of an `accepted` brainstorm/proposal was
> never met) · Transcript: none

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

In place of the codex seat, the design rests on executed verification: the
rejection matrix of §6 was produced by running all four token shapes through
the real verifier, the successful exchange is a recorded `HTTP 200`, and every
"Does NOT Exist" entry is a zero-match grep rather than an assumption. An
adversarial review before implementation should target Q1 — the one link the
PoC could not exercise.

---

## Worktree Strategy

- **Isolation**: one feature worktree, `feat-FEAT-729-msteams-user-auth-lane`,
  from `origin/dev`. The `sdd-coder` engine gives each task its own
  sub-worktree inside it.
- **Module dependency graph**:
  - M3 → M1 (constructs `MSTeamsUserSession`, uses `MSTeamsSessionStore`)
  - M3 → M2 (calls `TokenExchangeClient.exchange`)
  - M4 → M3 (commands call `ensure_authenticated`)
  - M5 → M1, M3 (builds `UserContext` from the session)
  - M6 → none in this spec (blocked externally by FEAT-103 Module 0)
  - M7 → M1-M6
  - **M1, M2 and M6 have no edges between them and are expected to run
    concurrently.**
- **Shared files**: `msteams/auth.py` is written by M1 and extended by M3 — those
  two tasks serialize. `services/identity_mapping.py` and the four call sites
  belong to M6 alone.
- **Exclusive resources**: none. No migration, no lockfile change, no extension
  rebuild.
- **Cross-feature dependencies**: navigator-auth FEAT-103 must be merged **and
  released as 0.28.8** before M6's acceptance criterion can be verified. M1-M5
  do not depend on it.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-22 | Jesus Lara | Initial draft, seeded by the in-session PoC: identity extraction (layers 1-2) and a live Azure→Navigator exchange returning HTTP 200 (layer 3) |
| 0.2 | 2026-10-23 | Claude | Approved for decomposition. Q2 resolved (`auth_required=False`, opt-in) and Q3 resolved (shared store for the serializable fields only) — Q3's premise corrected: Telegram's session is process-local, not Redis-backed, so M1 mirrors `IntegrationStateManager` instead. §4 Validation Contract split one test file per task to satisfy `check_task_graph`'s `file-overlap`. Corrected the preserved PoC log's path (`.log` is gitignored; it is committed as `.transcript.md`) |
