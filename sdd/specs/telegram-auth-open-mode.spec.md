---
type: feature
base_branch: dev
projects: [ai-parrot-integrations]
tags: [telegram, authentication, oauth2, browser, webview]
docs:
  policy: required
  pages: [wiki/integrations/telegram-auth-open-mode.md]
  api_modules: [parrot.integrations.telegram.browser_login]
---

# Feature Specification: Telegram Auth Open Mode (webview | browser)

**Feature ID**: FEAT-854
**Date**: 2026-11-09
**Author**: Jesus Lara
**Status**: approved
**Target version**: 2.2.0

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Every Telegram authentication strategy (`basic`, `azure`, `google`, `oauth2`, composite)
opens its login/authorization page through a `KeyboardButton(web_app=WebAppInfo(...))`,
which Telegram Desktop renders in its embedded WebKitGTK webview, and returns the result
through `Telegram.WebApp.sendData()` → `message.web_app_data`. On Linux desktops running
Wayland (e.g. Elementary OS), WebKitGTK crashes or renders blank, making the authorization
flow impossible to complete — users must authenticate on a smartphone first and only then
use Telegram on the PC. The webview is also a hard blocker for WebAuthn/PassKey (embedded
webviews cannot complete platform-authenticator ceremonies), which navigator-auth already
supports.

### Goals

- Add `auth_open_mode: webview | browser` to `TelegramAgentConfig` (default `webview`,
  preserving today's behavior byte-for-byte when unset).
- In `browser` mode, every auth strategy presents the login/authorize URL as an
  `InlineKeyboardButton(url=...)` that opens in the **system browser**.
- Move the auth return channel server-side for browser mode: callbacks/completions are
  consumed by aiohttp endpoints that correlate the CSRF `state` with the Telegram chat,
  complete the strategy callback, and notify the user with a proactive `bot.send_message`
  — no `sendData()` involved.
- All strategies supported in v1: `basic`, `azure`, `google`, `oauth2`, and
  `CompositeAuthStrategy` (user decision, 2026-11-09).
- The browser flow ends on a success page with a `https://t.me/<bot_username>` deep link
  back to the chat.

### Non-Goals (explicitly out of scope)

- PassKey/WebAuthn login via navigator-auth — explicit follow-up feature enabled by this
  one (browser mode is its prerequisite), not implemented here.
- OAuth2 authentication for MCP tools of agents exposed via ai-parrot-integrations —
  second follow-up enabled by the same server-side completion machinery.
- Changing the `/connect` post-auth connection lane (FEAT-776) — it already uses inline
  URL buttons + server callbacks and stays as-is.
- Multi-process (multi-worker gunicorn) state sharing — browser-mode state registry is
  in-process, matching the existing `OAuth2AuthStrategy._pending_states` constraint.
- Other chat platforms (Teams, Slack, WhatsApp).

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:834192f4b2bec0f9656c313c05a6a75264c42ba54baddc59b8c62de6ab2a5990 evaluation_digest=sha256:445602128db2eb2135c6ee054793c3da5a0d485cf40f667d09f796dbef7bbf13 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

Browser mode replaces the **presentation** (WebApp button → inline URL button) and the
**return channel** (client-side `sendData()` → server-side completion) while keeping the
strategy contract (`handle_callback(data, session) -> bool`) untouched.

Two existing mechanisms are generalized rather than invented:

1. The `/connect` post-auth lane (FEAT-776) already proves the browser pattern:
   `InlineKeyboardButton(url=...)` at `wrapper.py:2699`, a server callback, and proactive
   `bot.send_message(chat_id=...)` at `wrapper.py:2723`. Browser-mode login applies the
   same shape to the primary login.
2. The telegram OAuth2/combined callback endpoints already receive `code`/`state`
   server-side (`oauth2_callback.py`, `combined_callback.py`) — today they re-package the
   result into `sendData()` HTML; in browser mode they consume it in place.

**Flow (browser mode):**

1. `/login` → `handle_login` generates `state` as `"browser." + secrets.token_urlsafe(32)`
   in browser mode (the dot cannot occur in legacy `token_urlsafe` states), registers
   `state → (telegram_id, chat_id, bot_id)` in the new `BrowserLoginRegistry` (stored on
   `app["telegram_browser_login"]`), and sends an inline keyboard whose button URL opens
   in the system browser.
   - `oauth2`: the button URL is the provider authorization URL (PKCE, unchanged).
   - `basic` / `azure` / `google` / composite: the button URL is the existing login page
     with extra query params `return_mode=browser&state=<state>&complete_url=<abs URL>`.
2. The user authenticates in the system browser.
   - `oauth2`: the provider redirects to the existing `/oauth2/callback` endpoint. The
     handler recognizes the `browser.` prefix before any legacy response handling,
     consumes the registry entry, and delegates exactly once to `_complete_auth_payload`.
     That helper alone invokes the strategy to exchange the code and fetch userinfo.
     Unknown, expired, or consumed browser states return HTTP 410 without `sendData()`.
     Only unprefixed states use legacy HTML (webview flow unchanged); the prefix is a
     routing discriminator, never authentication evidence.
   - page-based strategies: the login page detects `return_mode=browser` and **POSTs**
     the exact same JSON payload it would have passed to `sendData()` to the new
     `POST /api/auth/telegram/browser-complete` endpoint (plus the `state`). Azure and
     multi-login SSO redirect builders preserve all three browser parameters across
     the Navigator round trip. The JSON is untrusted input, not proof of identity.
3. The completion endpoint calls the wrapper's new transport-agnostic
   `_complete_auth_payload(data, telegram_id=..., chat_id=..., browser_entry=entry)`.
   For page-based browser logins it verifies the token through the server-owned
   verifier described below and builds a candidate from the returned identity; it
   never authenticates through the trusting legacy Basic/Azure/Google callbacks.
   For OAuth2 it invokes the existing strategy callback exactly once. Both paths then
   share persistence, initialization, and the pending combined/post-auth lane, without
   a `Message` dependency. Only the webview adapter omits `browser_entry`.
4. The user gets a proactive `bot.send_message` confirmation in the chat and a success
   page in the browser with the deep link back.

`auth_open_mode: webview` (default) changes nothing: reply-keyboard WebApp buttons,
`sendData()`, `handle_web_app_data` — all byte-for-byte current behavior.

### Browser identity verification boundary

State correlates a login with a Telegram user; it does **not** authenticate that user's
Navigator identity. `BasicAuthStrategy.handle_callback` trusts `data.user_id`, while
Azure/Google callbacks decode JWT payloads without signature verification. Neither
those callbacks nor the existing `validate_token` checks constitute browser verification.

- M2 defines a new async `BrowserIdentityVerifier.verify(token, *, auth_method, bot_id,
  tenant_id) -> VerifiedBrowserIdentity` contract and a Pydantic v2 result containing
  `user_id`, `display_name`, and `email`. Rejection raises a typed verification error.
  No caller-supplied identity fields are passed to the verifier or used as authority.
- The host wires real verifiers before wrapper startup under
  `app["telegram_browser_identity_verifiers"][bot_id][auth_method]`. Each verifier is
  bound to a server-configured issuer, audience/application, and tenant. JWT adapters
  verify signatures using trusted keys and an explicit algorithm allowlist, expiry,
  issuer and audience; opaque-token adapters use an authoritative authenticated
  issuer lookup/introspection and derive identity from that response. Neither URLs,
  key locations, algorithms, nor tenant selection may come from the browser payload.
- This is a **new integration contract**, not an existing Navigator API. Do not assume
  a token-verification endpoint exists at `auth_url`. Implementation must supply and
  wire a concrete adapter for the deployment's issuer using existing dependencies,
  with contract tests against that verifier. A mock-only adapter or a nonempty-token
  check does not satisfy this feature. Browser startup fails clearly when any enabled
  basic/azure/google method (including composite members) lacks a verifier. OAuth2
  continues to authenticate through its server-side code exchange and userinfo flow.
- M4 selects only a configured method: infer the sole method when absent for legacy
  basic payloads; require an explicit enabled `auth_method` for composites. Empty
  tokens, invalid credentials, mismatched client identity fields, or verifier failures
  fail closed before session mutation, principal linking, or post-auth actions. If
  supplied, `user_id`, `display_name`, and `email` must match verified values; otherwise
  reject them. Build the candidate exclusively from verified values and the verified
  token, recording `metadata["auth_method"]` for composite dispatch.
- Invalid credentials return HTTP 401; unavailable verifier/backend returns HTTP 503.
  Both consume the login attempt and require a fresh `/login`; neither falls back to
  legacy callbacks or returns tokens. Any pending secondary authorization still gates
  promotion/persistence according to the existing coordinator contract.

### Component Diagram

```
                       ┌─────────────────────────┐
 /login ──────────────▶│ wrapper.handle_login    │
                       │  state = token_urlsafe  │
                       └───────┬─────────────────┘
               webview         │         browser
        ┌──────────────────────┴──────────────────────────┐
        ▼                                                  ▼
 ReplyKeyboardMarkup                         InlineKeyboardMarkup(url=…)
 KeyboardButton(web_app=…)                   + BrowserLoginRegistry.register(state)
        │                                                  │
        ▼                                                  ▼
 Telegram webview (WebKitGTK)                system browser
        │ sendData()                                       │
        ▼                                 ┌────────────────┴────────────────┐
 handle_web_app_data                      ▼                                 ▼
        │                     GET /oauth2/callback          POST /api/auth/telegram/
        │                     (oauth2: code+state)              browser-complete
        │                                 │                 (basic/azure/google payload)
        └──────────┐                      └────────┬────────────────┘
                   ▼                               ▼
        wrapper._complete_auth_payload(data, telegram_id, chat_id)
                   │
                   ├─ verified browser identity OR one OAuth2/legacy callback
                   ├─ _persist_principal_link / _initialize_user_context
                   └─ bot.send_message(chat_id, "✅ Authenticated…")
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `TelegramAgentConfig` (`models.py`) | extends | new `auth_open_mode` + formalized `public_base_url` fields |
| `AbstractAuthStrategy.build_login_keyboard` | modifies | return type widens to `Union[ReplyKeyboardMarkup, InlineKeyboardMarkup]`; strategies read `config.auth_open_mode` |
| `TelegramAgentWrapper.handle_login` | modifies | registers browser state; sends inline keyboard in browser mode |
| `TelegramAgentWrapper.handle_web_app_data` | refactors | success path extracted into `_complete_auth_payload` (webview path delegates to it) |
| `oauth2_callback.oauth2_callback_handler` | modifies | registry-aware browser branch before legacy sendData rendering |
| `combined_callback.setup_combined_auth_routes` call site (`orchestrator.py:359-369`) | extends | mounts `setup_browser_auth_routes(app)` with the same graceful-degrade pattern |
| `static/login.html`, `static/azure_login.html`, `static/login_multi.html` | modifies | dual-mode: `return_mode=browser` → POST to completion endpoint instead of `sendData()` |
| `PendingLoginCoordinator` / post-auth actions | uses | combined flow started from `_complete_auth_payload` with explicit `chat_id` (no `Message`) |

### Data Models

```python
# parrot/integrations/telegram/browser_login.py (new)
@dataclass
class BrowserLoginEntry:
    state: str
    telegram_id: int
    chat_id: int
    bot_id: str
    bot_username: Optional[str]
    created_at: float  # time.monotonic()
```

### New Public Interfaces

```python
# parrot/integrations/telegram/browser_login.py
class BrowserLoginRegistry:
    """In-process, TTL-bound registry mapping CSRF state → Telegram chat."""
    def register(self, entry: BrowserLoginEntry) -> None: ...
    def consume(self, state: str) -> Optional[BrowserLoginEntry]: ...
    def peek(self, state: str) -> Optional[BrowserLoginEntry]: ...

def setup_browser_auth_routes(app: web.Application) -> None: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Config fields | yes | field names, default, `__post_init__` validation pattern fixed below | — |
| M2: BrowserLoginRegistry and verification contract | yes | TTL registry, browser-state discriminator, verifier protocol/result and app registration contract fixed in §2 | — |
| M3: Strategy keyboards | yes | per-strategy branch on `config.auth_open_mode`; exact URLs/params fixed below | — |
| M4: Wrapper refactor | no | — | extraction of `_complete_auth_payload` from `handle_web_app_data`/`_handle_combined_auth` needs judgment about the combined/post-auth path |
| M5: Server endpoints and verifier wiring | no | endpoint contracts fixed below | concrete deployment issuer adapter must be verified against its real backend; no existing Navigator verification endpoint is assumed |
| M6: Login pages dual-mode | yes | JS contract fixed: same payload as `sendData()`, POSTed with `state` | — |
| M7: Wiki page | yes | content outline in §10 | — |

### Module 1: Config fields (`auth_open_mode`, `public_base_url`)
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py`
- **Responsibility**: Config surface + validation.
- **Depends on**: nothing.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py:89
  @dataclass
  class TelegramAgentConfig:  # verified: models.py (dataclass, fields at 65-110)
      # Auth presentation mode (FEAT-854): "webview" (default, WebApp button +
      # sendData) or "browser" (inline URL button + server-side completion).
      auth_open_mode: str = "webview"
      # Public base URL of the parrot server, used to build absolute callback /
      # completion URLs in browser mode. Formalizes the getattr() access that
      # wrapper.py:2685 already performs.
      public_base_url: Optional[str] = None

  # __post_init__ (verified: models.py:166) additionally:
  #   raises ValueError when auth_open_mode not in {"webview", "browser"}
  #   raises ValueError when auth_open_mode == "browser" and not public_base_url
  ```

### Module 2: Browser login registry, verification contract + result pages
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/browser_login.py` (new)
- **Responsibility**: `BrowserLoginEntry` + `BrowserLoginRegistry` (register/consume/peek,
  TTL sweep reusing the 600 s policy of `_STATE_TTL_SECONDS`, auth.py:1058); browser
  success/error HTML templates with `https://t.me/<bot_username>` deep link; app-key
  accessor `get_or_create_browser_login_registry(app)` mirroring
  `get_or_create_telegram_notifier` (connection_notifier.py:227). Also owns the
  `BrowserIdentityVerifier` protocol, `VerifiedBrowserIdentity` Pydantic result and
  typed rejection/unavailable errors specified in §2. Host verifier adapters and their
  startup wiring are required integration work in M5, not provided by legacy strategies.
- **Depends on**: nothing (M4/M5 consume it).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/telegram/browser_login.py (new)
  BROWSER_LOGIN_APP_KEY = "telegram_browser_login"
  BROWSER_STATE_PREFIX = "browser."
  _REGISTRY_TTL_SECONDS = 600  # same policy as auth.py:1058

  @dataclass
  class BrowserLoginEntry:
      """One pending browser-mode login, keyed by CSRF state."""
      state: str
      telegram_id: int
      chat_id: int
      bot_id: str
      bot_username: Optional[str]
      created_at: float

  class BrowserLoginRegistry:
      """In-process, TTL-bound state → chat correlation for browser-mode logins."""
      def register(self, entry: BrowserLoginEntry) -> None:
          """Store a pending login; sweeps expired entries first."""
      def consume(self, state: str) -> Optional[BrowserLoginEntry]:
          """Pop and return the entry (single-use); None if unknown/expired."""
      def peek(self, state: str) -> Optional[BrowserLoginEntry]:
          """Non-destructive lookup; never use a miss to select legacy routing."""

  def get_or_create_browser_login_registry(app: "web.Application") -> BrowserLoginRegistry:
      """Return the app-scoped registry, creating it under BROWSER_LOGIN_APP_KEY."""

  def render_browser_success(bot_username: Optional[str], display_name: str) -> str:
      """HTML success page with a t.me deep link back to the chat."""

  def render_browser_error(message: str) -> str:
      """HTML error page (no auth data echoed back)."""
  ```

  `register` accepts only states generated with `BROWSER_STATE_PREFIX` plus
  `secrets.token_urlsafe(32)` (32 bytes of entropy). `consume` performs TTL validation and removal synchronously, before
  any await, so concurrent callbacks cannot both authenticate. A missing browser entry
  is always rejected, including after sweep/restart; the prefix survives without
  tombstones. Unknown unprefixed states retain the legacy GET behavior only. POST
  completion never supports legacy routing. No identity is trusted from the prefix.

### Module 3: Browser-mode keyboards in auth strategies
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py`
- **Responsibility**: Each `build_login_keyboard` branches on
  `getattr(config, "auth_open_mode", "webview")`. Browser branch returns
  `InlineKeyboardMarkup` with `InlineKeyboardButton(text=..., url=...)`:
  - `BasicAuthStrategy` (auth.py:406): login page URL + `return_mode=browser&state=…&complete_url=…`
  - `AzureAuthStrategy` (auth.py:569) / `GoogleAuthStrategy` (auth.py:846): same params on their login pages
  - `OAuth2AuthStrategy` (auth.py:1192): the raw authorize URL (provider redirects server-side; no page params needed)
  - `CompositeAuthStrategy` (auth.py:1500): `login_multi.html` + the same browser params
- **Depends on**: Module 1.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py:322
  class AbstractAuthStrategy(ABC):  # verified: auth.py:302
      @abstractmethod
      async def build_login_keyboard(
          self,
          config: Any,
          state: str,
          *,
          next_auth_url: Optional[str] = None,
          next_auth_required: bool = False,
      ) -> Union[ReplyKeyboardMarkup, InlineKeyboardMarkup]:
          """Return the login keyboard.

          webview mode: ReplyKeyboardMarkup with a WebApp button (unchanged).
          browser mode: InlineKeyboardMarkup with a plain-URL button that opens
          the system browser (FEAT-854).
          """

  def _browser_keyboard(text: str, url: str) -> InlineKeyboardMarkup:
      """Module-level helper shared by all strategies' browser branch."""
  ```

### Module 4: Wrapper — state registration + transport-agnostic completion
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py`
- **Responsibility**:
  1. `handle_login` (wrapper.py:2485): when browser mode, register the state in the
     registry (with `chat_id`, `telegram_id`, cached `bot_username`) before sending the
     keyboard; use `browser.` plus `secrets.token_urlsafe(32)` and pass that exact value
     unchanged to the OAuth2 PKCE store/authorize URL, including composite OAuth2.
     Adjust prompt copy ("the link opens in your browser").
  2. Extract the success path of `handle_web_app_data` (wrapper.py:2583) and
     `_handle_combined_auth` into `_complete_auth_payload`, callable without a `Message`;
     `handle_web_app_data` becomes a thin webview adapter over it (behavior preserved,
     including `ReplyKeyboardRemove` on the webview path only).
  3. Expose `wrapper` lookup for the endpoints: wrappers self-register in an app-scoped
     map `app["telegram_wrappers"][bot_id]` (pattern: `app.get("telegram_connection_notifier")`,
     wrapper.py:2717).
  4. Browser startup validates the shared app and all required verifier registrations
     (§2). `_complete_auth_payload` owns the only primary-auth execution: verified
     candidate construction for browser basic/azure/google, one strategy callback for
     OAuth2, or the unchanged legacy callback for the webview adapter. Endpoints must
     not call `handle_callback`, `_consume_state`, `exchange_code`, or `fetch_userinfo`.
     The new registry state and the strategy's PKCE state are separate stores, each
     consumed exactly once by its owner. Failure never retries a consumed code.
- **Depends on**: Modules 1, 2.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:2583
  class TelegramAgentWrapper:
      async def _complete_auth_payload(
          self,
          data: Dict[str, Any],
          *,
          telegram_id: int,
          chat_id: int,
          notify: bool = True,
          browser_entry: Optional[BrowserLoginEntry] = None,
      ) -> bool:
          """Run the primary auth callback and post-success pipeline.

          Transport-agnostic core shared by handle_web_app_data (webview) and the
          browser completion endpoints. Returns True on authenticated session.
          Sends the ✅/❌ chat notification via self.bot.send_message when notify.
          Routes combined/post_auth_actions payloads through the pending-attempt
          lane with explicit chat ids (no Message object).
          browser_entry is server-owned correlation context, never read from JSON.
          When present, enforce the verification boundary in §2 before promotion.
          All browser HTTP adapters must supply it and use its Telegram/chat ids.
          """
  ```

### Module 5: Server-side completion endpoints
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/oauth2_callback.py`
  (browser branch) + `browser_login.py` (new POST handler, verifier adapters + route setup) +
  `packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py` (mount).
- **Responsibility**:
  1. `oauth2_callback_handler` (oauth2_callback.py:138): classify `state` by the
     `browser.` prefix before provider-error/missing-code rendering or legacy HTML.
     For a browser state, atomically `consume` the entry; a miss returns HTTP 410
     browser error HTML without `sendData`, session mutation, or strategy invocation.
     On a hit, resolve the wrapper and pass `{auth_method: "oauth2", code, state}` to
     `_complete_auth_payload(..., browser_entry=entry)` exactly once, with the entry's
     Telegram/chat ids. This also supports composite strategy dispatch. Do not invoke
     strategy methods in this endpoint. Valid browser-state provider errors or missing
     codes consume the attempt and return HTTP 400 browser error HTML; they do not
     enter legacy handling. Only unprefixed states retain legacy behavior unchanged.
  2. New `browser_complete_handler` (`POST /api/auth/telegram/browser-complete`): JSON
     body = the exact payload the login pages pass to `sendData()` today, plus `state`.
     Validate JSON object and string state → consume browser state → resolve wrapper
     → `_complete_auth_payload(..., browser_entry=entry)`, using only entry-owned ids.
     Enforce the §2 verification boundary before any mutation. Responds JSON
     `{ok, redirect_url}` on success; the page renders the server-derived deep link.
     Never honor browser-supplied `browser_entry`, bot/chat ids, or a verification flag.
  3. `setup_browser_auth_routes(app)` registers the POST route; mounted in
     `orchestrator.py` beside `setup_combined_auth_routes(app)` (orchestrator.py:369)
     with the same try/except ImportError degrade.
  4. Wire concrete issuer verifier adapters through the §2 app registration contract
     before wrappers start; browser bots requiring unavailable verification fail
     startup. Document deployment wiring and test real verification behavior (including
     forged credentials). Do not invent an existing Navigator verification route.
- **Depends on**: Modules 2, 4.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/telegram/browser_login.py
  BROWSER_COMPLETE_PATH = "/api/auth/telegram/browser-complete"

  async def browser_complete_handler(request: web.Request) -> web.Response:
      """Consume a browser-mode login payload POSTed by a login page.

      400 on malformed JSON / missing state; 410 on unknown or expired state;
      401 on rejected credentials/identity mismatch; 503 on verifier unavailability;
      200 {ok: true, redirect_url: "https://t.me/<bot>"} on success.
      Never echoes tokens back in the response body.
      """

  def setup_browser_auth_routes(app: web.Application) -> None:
      """Register BROWSER_COMPLETE_PATH on the aiohttp app (idempotent)."""

  # modifies packages/ai-parrot-integrations/src/parrot/integrations/telegram/oauth2_callback.py:138
  async def oauth2_callback_handler(request: web.Request) -> web.Response:
      """Existing handler; gains the registry-aware browser branch (FEAT-854)."""
  ```

### Module 6: Dual-mode login pages
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/static/login.html`,
  `static/azure_login.html`, `static/login_multi.html`
- **Responsibility**: When the query string carries `return_mode=browser`, the page —
  after its existing auth logic produces the payload it would `sendData()` — instead
  POSTs `{...payload, state}` to `complete_url` and renders success (with
  `redirect_url` deep link) or error. The `sendData()` path is untouched only when no
  browser context is present (including retained attempt context after SSO).
- **Redirect continuity**: update the explicit `preserveParams` allowlists in
  `azure_login.html` (current lines 247–257) and `login_multi.html` (552–570), not just
  their `sendData` call sites. Preserve `return_mode=browser`, the exact original
  `state`, and `complete_url` in Navigator's `redirect_uri` for both Azure and Google.
  Navigator's internal OAuth state remains separate. Return-page initialization must
  recover this context before handling `?token=`; missing/invalid browser context must
  show an error and must never fall back to `sendData`. A `browser.` state or retained
  browser attempt marker with missing mode also fails closed. Preserve legacy behavior
  only for pages genuinely opened without browser context.
- **Completion destination**: `complete_url` is generated from the server's
  `public_base_url` and constant path. The deployed page validates it against a
  server-provided allowed completion origin/path before sending credentials; query
  parameters alone cannot establish that allowlist. Preserve it unchanged across SSO
  redirects. Never POST credentials to an arbitrary query-supplied URL.
- **Depends on**: Module 5 (endpoint contract).
- **Interface Skeleton**: *(JS contract, not Python)*
  ```javascript
  // shared snippet added to the three pages
  // completeLogin(payload): browser context → validate mode/state/destination,
  // then POST JSON {…payload, state}; incomplete browser context → show error.
  // Only genuine legacy context → Telegram.WebApp.sendData(JSON.stringify(payload)).
  ```

### Module 7: Documentation
- **Path**: `wiki/integrations/telegram-auth-open-mode.md` (new)
- **Responsibility**: Configuration reference (`auth_open_mode`, `public_base_url`),
  flow diagrams for both modes, verifier registration/issuer requirements and startup
  errors, browser-state routing, SSO parameter continuity, Wayland/WebKitGTK context,
  PassKey/MCP follow-up notes.
- **Depends on**: Modules 1–6.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_config_auth_open_mode_default_webview` | M1 | Unset field → `"webview"`, legacy behavior |
| `test_config_auth_open_mode_invalid_raises` | M1 | `auth_open_mode="popup"` → ValueError |
| `test_config_browser_requires_public_base_url` | M1 | browser without `public_base_url` → ValueError |
| `test_registry_register_consume_single_use` | M2 | `consume` pops; second call returns None |
| `test_registry_ttl_expiry` | M2 | entries older than TTL are not returned |
| `test_basic_keyboard_browser_mode_inline_url` | M3 | InlineKeyboardMarkup + `return_mode=browser&state=` params |
| `test_oauth2_keyboard_browser_mode_authorize_url` | M3 | inline button URL == authorize URL with PKCE |
| `test_all_strategies_webview_mode_unchanged` | M3 | default mode still returns ReplyKeyboardMarkup+WebAppInfo |
| `test_complete_auth_payload_success_notifies_chat` | M4 | strategy mock → bot.send_message called with chat_id |
| `test_handle_web_app_data_delegates_to_complete` | M4 | webview path behavior preserved |
| `test_oauth2_callback_browser_branch` | M5 | registered state → server-side completion + success HTML (no sendData script) |
| `test_oauth2_callback_legacy_branch_unchanged` | M5 | unknown **unprefixed** state → legacy sendData HTML (existing contract) |
| `test_browser_complete_handler_unknown_state_410` | M5 | expired/unknown state → 410, no session created |
| `test_browser_complete_handler_success` | M5 | valid payload → 200 + redirect_url, session authenticated |
| `test_browser_startup_requires_verifiers` | M4/M5 | Missing verifier for any enabled basic/azure/google member fails startup; OAuth2-only needs none |
| `test_browser_basic_rejects_forged_identity` | M4/M5 | Valid login state plus arbitrary user_id and empty/fake token → 401; no callback, mutation, link, or post-auth action |
| `test_browser_sso_rejects_invalid_tokens` | M4/M5 | Azure/Google: unsigned or tampered JWT, expired token, wrong issuer/audience/tenant → 401; no session/link mutation |
| `test_browser_identity_uses_verified_claims` | M4/M5 | Candidate derives solely from verifier; conflicting client identity rejected; composite selects only enabled method |
| `test_browser_verifier_unavailable_fails_closed` | M4/M5 | Backend failure → 503; consumed state cannot retry; legacy callbacks never invoked |
| `test_oauth2_browser_replay_expiry_410` | M2/M5 | Consumed, expired, swept, restart-lost and unknown prefixed states → GET 410; no sendData, strategy invocation or mutation |
| `test_oauth2_browser_callback_exactly_once` | M4/M5 | Single and composite OAuth2: callback, PKCE consume, exchange and userinfo each invoked once; persistence/initialization once on success |
| `test_oauth2_browser_concurrent_callbacks` | M2/M5 | Two callbacks for one state → one completion and one 410; one exchange total |
| `test_oauth2_browser_error_no_legacy_fallback` | M5 | Prefixed state plus provider error/missing code uses browser error response; no sendData or strategy call |

### Integration Tests

| Test | Description |
|---|---|
| `test_browser_mode_full_flow_oauth2` | `/login` → registry entry → simulated provider redirect → authenticated session + proactive message |
| `test_browser_mode_full_flow_basic` | `/login` → POST to browser-complete with basic payload → authenticated session |
| `test_browser_mode_combined_post_auth` | browser primary + post_auth_actions → pending attempt lane engages with explicit chat_id |
| `test_browser_mode_sso_redirect_round_trip` | Execute Azure and multi-login page JS for Azure/Google: parse generated redirect_uri, simulate Navigator token return and verify exact browser state/completion URL preserved, one POST, zero sendData calls |
| `test_browser_mode_sso_context_failure` | Remove/corrupt browser return context or tamper completion origin; page reports error, sends no credential POST and never falls back to sendData |
| `test_browser_mode_real_verifier_contract` | Concrete deployment verifier accepts issuer-produced credentials, rejects forged/wrong-context ones, and returns authoritative identity; do not substitute a mock for this contract test |

### Validation Contract

tests:
- packages/ai-parrot-integrations/tests/integrations/telegram/test_auth_strategies.py
- packages/ai-parrot-integrations/tests/integrations/telegram/test_oauth2_integration.py
- packages/ai-parrot-integrations/tests/integrations/telegram/test_azure_integration.py
- packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login.py
- packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_identity_verification.py
- packages/ai-parrot-integrations/tests/integrations/telegram/test_login_pages_browser_mode.py
markers: none

The two browser test files are new M2/M4/M5 deliverables. M6 additionally supplies an
executable page round-trip check using the repository's existing browser/JS test
tooling (`test_login_pages_browser_mode.py`, Python Playwright + headless Chromium,
pattern of `tests/voice/test_voice_demo_broadcast_browser.py`); source-string
assertions alone are insufficient. Record its command and
evidence with the task. The concrete verifier and page checks are required completion
evidence even where an issuer/browser fixture is unavailable locally; do not silently
skip them and declare the feature complete. No new dependencies are authorized here.

### Test Data / Fixtures

```python
@pytest.fixture
def browser_config():
    """TelegramAgentConfig with auth_open_mode='browser' and public_base_url set."""
    return TelegramAgentConfig(
        name="t", chatbot_id="c", auth_method="oauth2",
        oauth2_client_id="id", oauth2_client_secret="sec",
        oauth2_redirect_uri="https://parrot.example/oauth2/callback",
        auth_open_mode="browser", public_base_url="https://parrot.example",
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] With `auth_open_mode` unset or `webview`, every strategy returns today's
      `ReplyKeyboardMarkup`/`WebAppInfo` keyboard and `handle_web_app_data` behavior is
      unchanged (regression suite green without modification of existing assertions).
- [ ] With `auth_open_mode: browser`, `/login` sends an `InlineKeyboardMarkup` whose
      button carries a plain `url` (no `web_app`) for all five strategies.
- [ ] An oauth2 browser login completes end-to-end with **no** `sendData()` involvement:
      provider redirect → server-side code exchange → authenticated
      `TelegramUserSession` → proactive `bot.send_message` confirmation.
- [ ] A basic/azure/google browser login completes via
      `POST /api/auth/telegram/browser-complete` with the page's legacy payload + state.
- [ ] Browser page payloads authenticate only after server-side issuer verification;
      identity is derived from verified results, not JSON fields or unverified JWT
      claims. Forged/mismatched credentials yield 401, verifier failure yields 503,
      and neither mutates sessions/links nor starts post-auth actions. All enabled
      page-based methods have concrete verifiers wired before startup.
- [ ] Azure/Google (including composite) preserve `return_mode`, `state`, and the
      validated `complete_url` across the actual Navigator redirect round trip;
      missing browser context fails closed with no sendData fallback.
- [ ] Browser-mode `state` is single-use and TTL-bound (600 s); replay or expiry yields
      HTTP 410 and no session mutation on **both GET OAuth callback and POST completion**.
      The `browser.` prefix remains recognizable after consumption, sweep, or restart;
      only unprefixed GET states retain the legacy response.
- [ ] `_complete_auth_payload` exclusively owns primary authentication: OAuth2 callback,
      PKCE consumption, code exchange, and userinfo occur exactly once per successful
      single/composite login; duplicate/concurrent callbacks perform no second exchange.
- [ ] `auth_open_mode: browser` without `public_base_url` fails at config load with a
      clear ValueError.
- [ ] Browser success page contains the `https://t.me/<bot_username>` deep link.
- [ ] Validation-contract test files pass
      (`PYTHONPATH=packages/ai-parrot-integrations/src pytest <contract files>`).
- [ ] Documentation page declared in §10 exists (`parrot sdd techwiki check`).
- [ ] No breaking changes to existing public API (webview default preserved).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against dev @ `77f8c54f58` (2026-11-09). Paths relative to repo root;
> `telegram/` = `packages/ai-parrot-integrations/src/parrot/integrations/telegram/`.

### Verified Imports

```python
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo  # verified: telegram/auth.py:25-29
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove  # verified: telegram/wrapper.py:33-36 (same aiogram.types block)
from aiohttp import web  # verified: telegram/oauth2_callback.py:10
from parrot.integrations.telegram.oauth2_callback import _ERROR_HTML_TEMPLATE, _json_escape  # verified: telegram/combined_callback.py:23-26
from parrot.integrations.core.auth.oauth2_providers import get_provider, OAuth2ProviderConfig  # verified: telegram/auth.py:33
```

### Existing Class Signatures

```python
# telegram/auth.py
_STATE_TTL_SECONDS = 600  # line 1058

class AbstractAuthStrategy(ABC):  # line 302
    name: str = "abstract"  # line 318
    supports_post_auth_chain: bool = False  # line 319
    @abstractmethod
    async def build_login_keyboard(self, config: Any, state: str, *,
        next_auth_url: Optional[str] = None,
        next_auth_required: bool = False) -> ReplyKeyboardMarkup:  # line 322
    async def handle_callback(self, data: Dict[str, Any],
        session: TelegramUserSession) -> bool:  # line 347 (abstract)
    async def validate_token(self, session: TelegramUserSession) -> bool:  # line 364

class BasicAuthStrategy(AbstractAuthStrategy):   # line 380 — build_login_keyboard: 406 (WebAppInfo at 452)
class AzureAuthStrategy(AbstractAuthStrategy):   # line 531 — build_login_keyboard: 569 (WebAppInfo at 613)
class GoogleAuthStrategy(AbstractAuthStrategy):  # line 798 — build_login_keyboard: 846 (WebAppInfo at 887)

class OAuth2AuthStrategy(AbstractAuthStrategy):  # line 1061
    def __init__(self, config: Any) -> None:  # line 1076; reads config.oauth2_redirect_uri (line 1082)
    def _generate_pkce() -> Tuple[str, str]:  # line 1110 (staticmethod)
    def _store_state(self, state: str, code_verifier: str) -> None:  # line 1125
    def _consume_state(self, state: str) -> Optional[str]:  # line 1130
    def build_authorize_url(self, state: str) -> str:  # line 1154
    async def build_login_keyboard(...)  # line 1192 (WebAppInfo at 1238)
    async def handle_callback(self, data, session) -> bool:  # line 1245
    async def exchange_code(...)  # line 1352
    async def fetch_userinfo(...)  # line 1398

class CompositeAuthStrategy(AbstractAuthStrategy):  # line 1439 — build_login_keyboard: 1500 (WebAppInfo at 1558)

# telegram/models.py
@dataclass
class TelegramAgentConfig:
    auth_url: Optional[str] = None          # line 83
    login_page_url: Optional[str] = None    # line 84
    auth_method: str = "basic"              # line 89
    auth_methods: List[str]                 # line 92
    oauth2_redirect_uri: Optional[str] = None  # line 98
    post_auth_actions: List[PostAuthAction]    # line 106
    def __post_init__(self): ...            # line 166 (validates auth_methods at 184-187)

# telegram/wrapper.py
class TelegramAgentWrapper:
    # router registration for web_app_data: line 321
    async def handle_login(self, message: Message) -> None:  # line 2485
    #   state = secrets.token_urlsafe(32)  → line 2510
    #   keyboard = await self._auth_strategy.build_login_keyboard(self.config, state)  → line 2513
    async def handle_web_app_data(self, message: Message) -> None:  # line 2583
    async def _handle_combined_auth(self, message, data, session) -> None:  # line 2627
    async def _start_login_attempt(self, message, candidate) -> None:  # line 2653
    async def _finalize_login_attempt(self, attempt) -> None:  # ~line 2707
    #   self._user_sessions[attempt.telegram_id] = candidate  → line 2716
    #   notifier = self.app.get("telegram_connection_notifier")  → line 2717
    #   await self.bot.send_message(chat_id=attempt.chat_id, ...)  → line 2723
    # inline url button precedent: InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=..., url=url)]])  → lines 2698-2700
    # browser-callback base URL precedent: getattr(self.config, "public_base_url", "")  → line 2685

# telegram/oauth2_callback.py
async def oauth2_callback_handler(request: web.Request) -> web.Response:  # line 138
def setup_oauth2_routes(app: web.Application, path: str = "/oauth2/callback") -> None:  # line 195

# telegram/combined_callback.py
COMBINED_CALLBACK_PATH = "/api/auth/telegram/combined-callback"  # line 31
# route mount: app.router.add_get(path, combined_auth_callback_handler)  → line 186

# telegram/connection_notifier.py
class TelegramConnectionNotifier:  # line 21
    async def notify(self, event: ConnectionEvent, state_payload: Dict[str, Any]) -> None:  # line 181
def get_or_create_telegram_notifier(...)  # line 227

# telegram/post_auth_connection.py
class PendingLoginAttempt:  # line 25
class ConnectionPostAuthProvider:  # line 47
    async def build_auth_url(self, session: Any, config: Any, callback_base_url: str) -> str:  # line 66
class PendingLoginCoordinator:  # line 137

# packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py
# combined-auth mount with ImportError degrade: lines 359-369 (setup_combined_auth_routes(app) at 369)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `BrowserLoginRegistry` | aiohttp app state | `app["telegram_browser_login"]` (pattern: `app.get("telegram_connection_notifier")`) | `telegram/wrapper.py:2717` |
| M3 browser keyboards | `InlineKeyboardMarkup` precedent | same construction as /connect buttons | `telegram/wrapper.py:2698-2700` |
| M4 `_complete_auth_payload` | `self._auth_strategy.handle_callback(data, session)` | once for OAuth2/webview only; browser page methods use verified candidates (§2) | `telegram/wrapper.py:2609` |
| M4 proactive notify | `self.bot.send_message(chat_id=...)` | method call | `telegram/wrapper.py:2723` |
| M5 oauth2 browser branch | M4 completion helper → `OAuth2AuthStrategy.handle_callback` | one delegation with auth_method+code+state; no direct strategy call in M5 | `telegram/auth.py:1245` |
| M5 route mount | orchestrator combined-auth mount block | `setup_browser_auth_routes(app)` beside line 369 | `orchestrator.py:359-369` |
| M6 pages | `Telegram.WebApp.sendData` legacy path | preserved only when no browser attempt context exists | `telegram/static/*.html` (all three contain sendData) |

### Does NOT Exist (Anti-Hallucination)

- ~~`TelegramAgentConfig.public_base_url`~~ — **not a declared field** today; only read
  via `getattr(self.config, "public_base_url", "")` (wrapper.py:2685). M1 formalizes it.
- ~~`TelegramAgentConfig.auth_open_mode`~~ — does not exist yet (M1 creates it).
- ~~`parrot/integrations/telegram/browser_login.py`~~ — does not exist (M2 creates it).
- ~~`TelegramAgentWrapper._complete_auth_payload`~~ — does not exist (M4 extracts it).
- ~~`app["telegram_wrappers"]`~~ — no such app-scoped wrapper map exists yet (M4 adds
  it); the only precedent app keys are `telegram_connection_notifier` and the manager's.
- ~~Browser identity verification via existing `validate_token`~~ — not a verified
  identity lookup. Basic callback trusts submitted identity; Azure/Google decode JWT
  claims without signature checks. `BrowserIdentityVerifier`, its Pydantic result,
  concrete issuer adapters and `telegram_browser_identity_verifiers` app map are new
  contracts in this feature, not pre-existing APIs. Task decomposition must identify
  the concrete deployed issuer's verification contract; no guessed Navigator route.
- ~~Redis-backed state for primary oauth2 login~~ — `_pending_states` is an in-memory
  dict (auth.py:1125); only the FEAT-108 Jira combined flow uses Redis, via
  `JiraOAuthManager`, not available for generic strategies.
- ~~`setup_oauth2_routes` mounted by the server~~ — `telegram/oauth2_callback.py:195`'s
  setup has **no in-repo caller** (the `manager.py:902` call is a different
  `parrot.auth.oauth2_routes` module); deployments mount it themselves. The browser
  branch must therefore live in the handler, not assume a specific mount path.
- ~~`AbstractAuthStrategy.build_login_keyboard(open_mode=...)` kwarg~~ — mode is read
  from `config`, not passed as a new parameter (decided here; do not invent the kwarg).

### Edit Sites (Blueprint Anchors)

Verified against: `77f8c54f58`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `telegram/models.py` | MODIFY | `auth_method: str = "basic"` | `models.py:89` | 1 |
| `telegram/browser_login.py` | CREATE | — | — | — |
| `telegram/auth.py` | MODIFY | `    ) -> ReplyKeyboardMarkup:` (abstract `build_login_keyboard` return, preceded by `next_auth_required: bool = False,`) | `auth.py:329` | 6 — disambiguate per strategy by enclosing `async def build_login_keyboard` + class |
| `telegram/wrapper.py` | MODIFY | `        keyboard = await self._auth_strategy.build_login_keyboard(self.config, state)` | `wrapper.py:2513` | 1 |
| `telegram/wrapper.py` | MODIFY | `    async def handle_web_app_data(self, message: Message) -> None:` | `wrapper.py:2583` | 1 |
| `telegram/oauth2_callback.py` | MODIFY | `async def oauth2_callback_handler(request: web.Request) -> web.Response:` | `oauth2_callback.py:138` | 1 |
| `packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py` | MODIFY | `                setup_combined_auth_routes(app)` | `orchestrator.py:369` | 1 |
| `telegram/static/login.html` | MODIFY | `(sendData call site — locate `Telegram.WebApp.sendData` in file)` | `static/login.html` | (unverified — check before use) |
| `telegram/static/azure_login.html` | MODIFY | `(sendData call site)` | `static/azure_login.html` | (unverified — check before use) |
| `telegram/static/login_multi.html` | MODIFY | `(sendData call site)` | `static/login_multi.html` | (unverified — check before use) |
| `wiki/integrations/telegram-auth-open-mode.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- aiohttp only (never requests/httpx); handlers follow `oauth2_callback.py`'s
  escape-everything discipline (`html_mod.escape`, `_json_escape`) — browser pages must
  never echo tokens or unescaped user input.
- Logging via module logger (`navconfig.logging`), pattern of `oauth2_callback.py:13`.
- App-scoped singletons via `get_or_create_*` accessor, pattern of
  `connection_notifier.py:227`.
- The browser branch in `oauth2_callback_handler` must be **additive**: unknown
  unprefixed state → byte-identical legacy response; unknown `browser.` state → 410.
  Registry misses must never decide the presentation mode. Prefix classification is
  performed before legacy error rendering, while registry membership authenticates
  the correlation and the verifier/provider authenticates identity.
- `bot_username` for the deep link: cache `(await self.bot.get_me()).username` once in
  the wrapper at startup/first login; store it in the registry entry.

### Known Risks / Gotchas

- **Single-process constraint**: registry and `_pending_states` are in-memory; with
  multiple gunicorn workers the HTTP callback can land in a process that doesn't hold
  the state. Same pre-existing constraint as the webview oauth2 flow; documented in §10,
  escalated as §8 Q1 for a Redis follow-up.
- **The callback endpoints and the bot wrapper must share the aiohttp app**. The
  orchestrator mount (orchestrator.py:359-369) guarantees this for managed deployments;
  standalone bots without the HTTP app cannot use browser mode → config validation
  should warn/fail loudly at startup, not at login time.
- **Inline vs reply keyboard UX**: browser mode can't use `ReplyKeyboardRemove` (nothing
  to remove) and the inline button stays in history; the success notification should
  edit or ignore it, never crash on it.
- **Combined flow (`post_auth_actions`)**: `_handle_combined_auth` builds a candidate
  session and enters the `PendingLoginCoordinator` lane; `_complete_auth_payload` must
  preserve that path with explicit `chat_id` (the secondary /connect buttons are already
  inline-URL based, so they work in the system browser naturally).
- **Open-redirect surface**: `complete_url`/`redirect_url` must be server-derived
  (`public_base_url` + constant paths), never taken from client input.
- **Login pages are also served by Navigator deployments** — the dual-mode JS must not
  break pages opened without the new query params (old servers, old links).
- **Worktree testing**: `PYTHONPATH=packages/ai-parrot-integrations/src` (absolute in
  worktrees) — see `.claude/rules/codebase-conventions.md`.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| (none new) | — | aiogram + aiohttp already in ai-parrot-integrations |

---

## Decisions

```yaml
schema_version: 1
document_id: telegram-auth-open-mode
entries:
  - id: open-mode-config-driven
    statement: Auth presentation mode is read from TelegramAgentConfig.auth_open_mode (default "webview"); strategies must not accept a per-call open-mode parameter.
    relation: constrains
    about: [integrations]
    targets: [file:packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py]
    contradicts: []
    supersedes: []
    rationale: "One switch per bot keeps the strategy interface stable and the webview default byte-compatible."
    rejected_alternatives: ["new open_mode kwarg on build_login_keyboard", "global env toggle"]
  - id: browser-return-channel-server-side
    statement: In browser mode the auth result is consumed server-side (state-correlated aiohttp endpoints + proactive bot.send_message); Telegram.WebApp.sendData must not be part of the browser path.
    relation: requires
    about: [integrations]
    targets: [file:packages/ai-parrot-integrations/src/parrot/integrations/telegram/oauth2_callback.py]
    contradicts: []
    supersedes: []
    rationale: "sendData only exists inside the Telegram webview; the system browser has no channel back to the bot other than the server."
    rejected_alternatives: ["t.me deep-link start-payload return (64-char limit, no tokens)"]
```

## Decision Waivers

<!-- none -->

## Consequences

<!-- decision-audit: input_digest=sha256:834192f4b2bec0f9656c313c05a6a75264c42ba54baddc59b8c62de6ab2a5990 evaluation_digest=sha256:445602128db2eb2135c6ee054793c3da5a0d485cf40f667d09f796dbef7bbf13 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- none

Coverage:
- Subsystems: integrations
- Unmapped tags: authentication, browser, oauth2, telegram, webview
- Targets resolved: 2/2
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "integrations"
    ],
    "targets_resolved": 2,
    "targets_total": 2,
    "unmapped_tags": [
      "authentication",
      "browser",
      "oauth2",
      "telegram",
      "webview"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:445602128db2eb2135c6ee054793c3da5a0d485cf40f667d09f796dbef7bbf13",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:834192f4b2bec0f9656c313c05a6a75264c42ba54baddc59b8c62de6ab2a5990",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:4352b858aea606efbb0f6d4f9638d97a0c15e4e91b4b487403798cc58f5674e5",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [ ] Q1: Should browser-mode state move to Redis (shared with the FEAT-108 pattern) to
      support multi-worker deployments, or is single-process documented-and-accepted for
      v1? — *Owner: Jesus Lara* (v1 ships in-process; this decides the follow-up): multi-worker deployments
- [ ] Q2: Should the inline login button message be edited/deleted after successful
      browser login (requires storing `message_id` in the registry entry)? — *Owner:
      implementation* (nice-to-have; decide at task time)
- [x] Scope of strategies in v1 — *Resolved by user, 2026-11-09*: all strategies
      (`basic`, `azure`, `google`, `oauth2`, composite), including the server-side
      completion endpoint and dual-mode login pages.
- [x] Default mode — *Resolved by user, 2026-11-09*: `webview` remains the default;
      `browser` is opt-in per agent config.
- [x] PassKey and MCP-tools auth — *Resolved by user, 2026-11-09*: follow-ups enabled by
      this feature, explicitly out of scope here (§1 Non-Goals).

---

## 9. Design Research Cross-Check

> Status: skipped (no accepted exploration document — spec scaffolded directly from an
> interactive request; §3b preconditions not met)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/integrations/telegram-auth-open-mode.md` — create: configuration reference
    (`auth_open_mode`, `public_base_url`), both flow diagrams, Wayland/WebKitGTK
    motivation, single-process constraint, verifier adapter wiring and issuer contract,
    browser-state replay routing, SSO return-context preservation, PassKey/MCP-tools
    follow-up pointers.
- **API modules**:
  - `parrot.integrations.telegram.browser_login`

---

## Worktree Strategy

- **Isolation**: one feature worktree (`feat-FEAT-854-telegram-auth-open-mode`); the
  sdd-coder engine gives each task its own sub-worktree.
- **Module dependency graph**:
  - M3 → M1 (reads `config.auth_open_mode`, models.py)
  - M4 → M1, M2 (registry import, config read)
  - M5 → M2, M4 (consumes registry, calls `_complete_auth_payload`)
  - M6 → M5 (endpoint contract `BROWSER_COMPLETE_PATH`)
  - M7 → all (documents the result)
  - M1 and M2 have no edges between them — expected concurrent.
- **Shared files**: `auth.py` (M3 only), `wrapper.py` (M4 only), `oauth2_callback.py`
  (M5 only), `models.py` (M1 only); the three static HTML pages belong to M6 only.
  `browser_login.py` is created by M2 and extended by M5 after M2 completes; do not
  schedule those edits concurrently. M5 owns host verifier wiring in `orchestrator.py`.
- **Exclusive resources**: none (no native builds, no migrations, no lockfile).
- **Cross-feature dependencies**: none — no open feature touches
  `telegram/auth.py`/`wrapper.py` per `sdd/tasks/index/` at spec time.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-09 | Jesus Lara + Claude | Initial draft (scope resolved interactively: all strategies) |
| 0.2 | 2026-11-09 | Codex | Resolve four design-review findings: verified browser identities, SSO context preservation, explicit browser replay routing, and single-owner OAuth completion; extend tests and acceptance criteria. |

### Review resolution evidence (specification changes only)

| Ledger issue | Resolution | Required implementation evidence |
|---|---|---|
| `4d8c2ca6b557` | §2 verification boundary; M2 protocol, M4 verified candidate construction, M5 concrete verifier wiring | Forged-identity/JWT rejection, issuer contract tests, no mutation on failure |
| `2a71290fb8bf` | M6 redirect allowlists preserve browser context before token handling | Executed Azure/Google page round trips and missing-context failures |
| `b2c02f74fc6d` | `browser.` state namespace; M2 atomic consumption; M5 classifies before legacy rendering | GET/POST expiry and replay → 410, including swept/restart-lost entries |
| `1152c28db7d5` | M4 sole primary-auth owner; M5 delegates exactly once | Single/composite OAuth callback/exchange once; concurrent replay has no second exchange |

These issues track defects in the draft design and are resolved by revision 0.2.
Their closure does not claim the feature is implemented or its acceptance tests pass;
the status remains draft and all implementation acceptance criteria remain unchecked.
