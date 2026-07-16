---
type: Wiki Overview
title: 'Feature Specification: JiraToolkit Integrations OAuth2'
id: doc:sdd-specs-jiratoolkit-integrations-oauth2-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The Telegram integration exposes three Jira OAuth 2.0 (3LO) commands that
  users rely on:'
relates_to:
- concept: mod:parrot.auth
  rel: mentions
- concept: mod:parrot.auth.jira_oauth
  rel: mentions
- concept: mod:parrot.integrations.core.auth
  rel: mentions
- concept: mod:parrot.integrations.core.auth.post_auth
  rel: mentions
- concept: mod:parrot.integrations.msteams.commands
  rel: mentions
- concept: mod:parrot.integrations.msteams.models
  rel: mentions
- concept: mod:parrot.integrations.msteams.oauth_callback
  rel: mentions
- concept: mod:parrot.integrations.msteams.wrapper
  rel: mentions
- concept: mod:parrot.integrations.slack
  rel: mentions
- concept: mod:parrot.integrations.slack.commands
  rel: mentions
- concept: mod:parrot.integrations.slack.models
  rel: mentions
- concept: mod:parrot.integrations.slack.oauth_callback
  rel: mentions
- concept: mod:parrot.integrations.slack.security
  rel: mentions
- concept: mod:parrot.integrations.slack.socket_handler
  rel: mentions
- concept: mod:parrot.integrations.slack.wrapper
  rel: mentions
- concept: mod:parrot.integrations.telegram
  rel: mentions
- concept: mod:parrot.integrations.telegram.jira_commands
  rel: mentions
- concept: mod:parrot.integrations.telegram.post_auth_jira
  rel: mentions
- concept: mod:parrot.services.identity_mapping
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: JiraToolkit Integrations OAuth2

**Feature ID**: FEAT-225
**Date**: 2026-06-04
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

The Telegram integration exposes three Jira OAuth 2.0 (3LO) commands that users rely on:

- `/connect_jira` — generates an Atlassian authorization URL and sends it as an inline button; after consent, tokens are stored in Redis and the user is confirmed in-chat.
- `/disconnect_jira` — revokes the user's stored Jira tokens.
- `/jira_status` — reports whether a valid Jira connection is on file with display name and site URL.

Neither the **Slack** integration nor the **MS Teams** integration has any Jira authentication infrastructure today. Users interacting with the same agents through Slack or MS Teams cannot connect their Jira accounts and therefore cannot use `JiraToolkit`-powered features. This forces users to authenticate via Telegram even when their primary chat platform is Slack or Teams.

This feature brings Slack and MS Teams to parity with Telegram for the three Jira command families, with a unified identity model: a user who connects Jira via Telegram and later via Slack or Teams appears as the **same** identity in `auth.user_identities`.

### Goals

- Expose `/connect_jira`, `/disconnect_jira`, and `/jira_status` commands in both the Slack and MS Teams integrations.
- Lift shared auth primitives out of the Telegram integration into `integrations/core/auth/` so all three integrations share one source of truth for the post-auth protocol and OAuth2 provider catalog.
- Unify identity persistence: all integrations write to the same Redis token store (keyed by `channel:user_id`) and the same `auth.user_identities` PostgreSQL table.
- Match the existing Telegram UX as closely as each platform allows.

### Non-Goals (explicitly out of scope)

- Azure SSO (`/login` command) — will be a separate spec.
- Office365 commands, composite auth strategies, or post-auth chaining between Azure and Jira.
- Web/AgentChat Jira integration (covered by a separate brainstorm: `cross-repository-jiratoolkit-oauth2-3lo.brainstorm.md`).
- Provider-side token revocation on disconnect (same policy as Telegram: only delete local tokens).
- Vault token mirroring for Slack/Teams channels (Redis + `auth.user_identities` only; Vault is Telegram-specific).

---

## 2. Architectural Design

### Overview

Lift the provider-agnostic post-auth protocol and OAuth2 provider catalog from `integrations/telegram/` to `integrations/core/auth/`. Then add per-integration command modules for Slack and MS Teams that delegate to the existing `JiraOAuthManager` (unchanged) via integration-specific channel constants.

Each integration follows the same pattern:
1. User issues a command (`/connect_jira`).
2. Handler calls `JiraOAuthManager.create_authorization_url(channel=<integration>, user_id=<platform_user_id>)`.
3. Handler sends an interactive element (inline button for Slack, Adaptive Card for Teams) linking to the auth URL.
4. User consents in the browser; Atlassian redirects to the existing `/api/auth/jira/callback` route.
5. Callback stores tokens in Redis, writes `auth.user_identities`, and confirms to the user via platform-specific notification (DM for Slack, proactive message for Teams).

### Component Diagram

```
User (Slack/Teams)
    │
    ▼
┌───────────────────────┐   ┌─────────────────────────┐
│ SlackCommandRouter    │   │ MSTeamsCommandRouter     │
│  /connect_jira        │   │  /connect_jira           │
│  /disconnect_jira     │   │  /disconnect_jira        │
│  /jira_status         │   │  /jira_status            │
└───────┬───────────────┘   └──────────┬──────────────┘
        │                              │
        ▼                              ▼
┌──────────────────────────────────────────────────────┐
│ JiraOAuthManager (unchanged)                         │
│  create_authorization_url(channel, user_id)          │
│  handle_callback(code, state)                        │
│  validate_token(channel, user_id)                    │
│  revoke(channel, user_id)                            │
└──────────────────────┬───────────────────────────────┘
                       │
            ┌──────────┼──────────┐
            ▼          ▼          ▼
         Redis    user_identities  Vault (Telegram only)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `JiraOAuthManager` | uses (no change) | All public methods reused as-is with new channel constants |
| `IdentityMappingService` | uses (no change) | `upsert_identity` writes Slack/Teams identity rows |
| `PostAuthProvider` / `PostAuthRegistry` | moves | Lifted from `telegram/post_auth.py` to `core/auth/post_auth.py` |
| `OAUTH2_PROVIDERS` | moves | Lifted from `telegram/oauth2_providers.py` to `core/auth/oauth2_providers.py` |
| `SlackAgentWrapper._handle_command` | extends | Delegates new commands to `SlackCommandRouter` |
| `SlackSocketHandler._handle_slash_command` | extends | Same delegation to `SlackCommandRouter` |
| `MSTeamsAgentWrapper.on_message_activity` | extends | Adds command detection before agent processing |
| `jira_oauth_callback` route | extends | Adds `channel` dispatch for Slack/Teams notifications |

### Data Models

```python
# No new Pydantic models needed — reuses existing JiraTokenSet.
# Channel constants:
_SLACK_CHANNEL = "slack"        # in slack/commands/jira_commands.py
_MSTEAMS_CHANNEL = "msteams"    # in msteams/commands/jira_commands.py

# Slack user_id format for JiraOAuthManager:
# f"{team_id}:{slack_user_id}" — multi-workspace safe

# MS Teams user_id format:
# turn_context.activity.from_property.aad_object_id or from_property.id
```

### New Public Interfaces

```python
# Slack command router
class SlackCommandRouter:
    """Routes slash commands to registered handlers."""
    def register(self, command: str, handler: Callable) -> None: ...
    async def dispatch(self, command: str, payload: dict) -> Optional[dict]: ...

# MS Teams command router
class MSTeamsCommandRouter:
    """Detects and routes text commands in message activity."""
    def register(self, command: str, handler: Callable) -> None: ...
    async def try_dispatch(self, text: str, turn_context: TurnContext) -> bool: ...

# Slack notification helper (mirrors TelegramOAuthNotifier)
class SlackOAuthNotifier:
    """Push DM confirmation to Slack user after OAuth callback."""
    async def notify_connected(self, team_id: str, user_id: str, display_name: str, site_url: str) -> None: ...
    async def notify_failure(self, team_id: str, user_id: str, reason: str) -> None: ...

# MS Teams notification helper
class MSTeamsOAuthNotifier:
    """Push proactive message to Teams user after OAuth callback."""
    async def notify_connected(self, conversation_ref: dict, display_name: str, site_url: str) -> None: ...
    async def notify_failure(self, conversation_ref: dict, reason: str) -> None: ...
```

---

## 3. Module Breakdown

### Module 1: Lift Shared Auth Primitives to `integrations/core/auth/`

- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/__init__.py`, `post_auth.py`, `oauth2_providers.py`
- **Responsibility**: Move `PostAuthProvider` protocol, `PostAuthRegistry`, `OAUTH2_PROVIDERS` dict, and `OAuth2ProviderConfig` from `telegram/` to `core/auth/`. Update all Telegram imports to the new paths (hard rename, no shims).
- **Depends on**: nothing

### Module 2: Slack Command Router + Jira Commands

- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/__init__.py`, `jira_commands.py`
- **Responsibility**: `SlackCommandRouter` that dispatches `/connect_jira`, `/disconnect_jira`, `/jira_status` from both HTTP and Socket Mode entry points. Each handler mirrors the Telegram pattern: check existing token, generate auth URL, send ephemeral message with button, revoke, or report status.
- **Depends on**: Module 1

### Module 3: Slack OAuth Callback + Notification

- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py`
- **Responsibility**: Extend the OAuth callback to detect `channel="slack"` from `extra_state` and: (a) write `auth.user_identities` row for the Slack provider, (b) return a plain HTML success/error page, (c) DM the Slack user via `chat.postMessage` confirming the connection.
- **Depends on**: Module 2

### Module 4: Slack Wrapper + Socket Handler Wiring

- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py`, `socket_handler.py`
- **Responsibility**: Wire `SlackCommandRouter` into `_handle_command` (HTTP) and `_handle_slash_command` (Socket Mode). Register the Jira commands during `__init__`. Register the OAuth callback aiohttp route.
- **Depends on**: Module 2, Module 3

### Module 5: MS Teams Command Router + Jira Commands

- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py`, `jira_commands.py`
- **Responsibility**: `MSTeamsCommandRouter` that detects text commands (`/connect_jira`, etc.) in `on_message_activity`. Each handler mirrors the Telegram pattern but uses Adaptive Cards (with a button linking to the auth URL) instead of inline keyboards. Additionally, an optional Adaptive Card menu for Jira commands can be triggered by a `jira` or `integrations` text command for discoverability.
- **Depends on**: Module 1

### Module 6: MS Teams OAuth Callback + Notification

- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py`
- **Responsibility**: Extend the OAuth callback to detect `channel="msteams"` from `extra_state` and: (a) write `auth.user_identities` row for the Teams provider, (b) return a plain HTML success/error page, (c) send a proactive message to the Teams user confirming the connection. Proactive messaging requires storing a `conversation_reference` in `extra_state` during URL generation.
- **Depends on**: Module 5

### Module 7: MS Teams Wrapper Wiring

- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py`
- **Responsibility**: Wire `MSTeamsCommandRouter` into `on_message_activity` (intercept commands before passing to agent). Register the OAuth callback aiohttp route alongside the existing webhook handler.
- **Depends on**: Module 5, Module 6

### Module 8: Config + Callback Route Extension

- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py`, `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py`, `packages/ai-parrot/src/parrot/auth/routes.py`
- **Responsibility**: Add optional `jira_client_id`, `jira_client_secret`, `jira_redirect_uri` fields to `SlackAgentConfig` and `MSTeamsAgentConfig`. Extend `jira_oauth_callback` in `auth/routes.py` to branch on `extra_state["channel"]` for Slack/Teams notifications (Telegram path unchanged).
- **Depends on**: Module 3, Module 6

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_slack_command_router_dispatch` | Module 2 | Routes known commands to handlers, returns None for unknown |
| `test_slack_connect_jira_generates_url` | Module 2 | Calls `create_authorization_url` with `channel="slack"` and `f"{team_id}:{user_id}"` |
| `test_slack_connect_jira_already_connected` | Module 2 | Short-circuits with status when `validate_token` returns a token |
| `test_slack_disconnect_jira_revokes` | Module 2 | Calls `JiraOAuthManager.revoke` with correct channel/user_id |
| `test_slack_jira_status_connected` | Module 2 | Returns display_name and site_url |
| `test_slack_jira_status_not_connected` | Module 2 | Returns "Not connected" message |
| `test_slack_multi_workspace_key` | Module 2 | user_id is `f"{team_id}:{slack_user_id}"`, not just `slack_user_id` |
| `test_msteams_command_router_detects_command` | Module 5 | Detects `/connect_jira` in message text |
| `test_msteams_command_router_ignores_normal_text` | Module 5 | Non-command text passes through to agent |
| `test_msteams_connect_jira_sends_card` | Module 5 | Sends an Adaptive Card with auth URL button |
| `test_msteams_disconnect_jira_revokes` | Module 5 | Calls `JiraOAuthManager.revoke` with correct channel/user_id |
| `test_callback_slack_channel_writes_identity` | Module 3 | `extra_state.channel == "slack"` writes `auth.user_identities` row |
| `test_callback_msteams_channel_writes_identity` | Module 6 | `extra_state.channel == "msteams"` writes `auth.user_identities` row |
| `test_callback_telegram_unchanged` | Module 8 | `extra_state.channel == "telegram"` (or absent) follows existing path |
| `test_core_auth_imports_resolve` | Module 1 | `from parrot.integrations.core.auth.post_auth import PostAuthProvider` works |
| `test_telegram_imports_updated` | Module 1 | Telegram modules import from `core.auth.*`, old paths deleted |

### Integration Tests

| Test | Description |
|---|---|
| `test_slack_jira_e2e_flow` | Full flow: command → auth URL → mock callback → token stored → DM sent |
| `test_msteams_jira_e2e_flow` | Full flow: command → auth URL → mock callback → token stored → proactive msg sent |
| `test_cross_integration_identity` | User connects via Telegram and Slack → same `nav_user_id` in `auth.user_identities` |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_jira_oauth_manager():
    """JiraOAuthManager with mocked Redis for token storage."""
    ...

@pytest.fixture
def slack_command_payload():
    """Slack slash command POST data with team_id, user_id, text."""
    return {
        "team_id": "T0001",
        "user_id": "U1234",
        "channel_id": "C5678",
        "text": "connect_jira",
        "response_url": "https://hooks.slack.com/...",
    }

@pytest.fixture
def teams_turn_context():
    """Mock TurnContext with activity.text = '/connect_jira'."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] `/connect_jira` in Slack (HTTP mode) generates an auth URL and sends an ephemeral message with a button.
- [ ] `/connect_jira` in Slack (Socket Mode) behaves identically to HTTP mode.
- [ ] `/disconnect_jira` in Slack revokes the Jira token and sends an ephemeral confirmation.
- [ ] `/jira_status` in Slack reports connection status ephemerally.
- [ ] `/connect_jira` in MS Teams (as text message) sends an Adaptive Card with an auth URL button.
- [ ] `/disconnect_jira` in MS Teams revokes the token and confirms via reply.
- [ ] `/jira_status` in MS Teams reports connection status.
- [ ] MS Teams also shows an Adaptive Card menu for Jira commands on request (e.g., typing `integrations` or `jira`).
- [ ] Slack commands ack within 3 seconds (Slack requirement); OAuth work runs asynchronously.
- [ ] Slack multi-workspace: user_id passed to `JiraOAuthManager` is `f"{team_id}:{slack_user_id}"`.
- [ ] OAuth callback correctly dispatches on `extra_state["channel"]` for Slack, Teams, and Telegram.
- [ ] After successful callback, Slack user receives a DM confirming the connection.
- [ ] After successful callback, Teams user receives a proactive message confirming the connection.
- [ ] `auth.user_identities` rows are written for both Slack and Teams providers.
- [ ] `/connect_jira` when already connected short-circuits with "Already connected" (matches Telegram behavior).
- [ ] `/disconnect_jira` does NOT delete `auth.user_identities` rows (audit trail preserved).
- [ ] `PostAuthProvider` and `OAUTH2_PROVIDERS` are moved to `integrations/core/auth/` with no Telegram regression.
- [ ] All Telegram imports updated to `core.auth.*`; old `telegram/post_auth.py` and `telegram/oauth2_providers.py` deleted.
- [ ] All unit tests pass: `pytest tests/integrations/telegram/ tests/integrations/slack/ tests/integrations/msteams/ -v`
- [ ] No breaking changes to existing Telegram Jira flow.

---

## 6. Codebase Contract

### Verified Imports

```python
# Core auth (verified: packages/ai-parrot/src/parrot/auth/)
from parrot.auth.jira_oauth import JiraOAuthManager, JiraTokenSet  # jira_oauth.py:86, :59

# Identity mapping (verified: packages/ai-parrot/src/parrot/services/)
from parrot.services.identity_mapping import IdentityMappingService  # identity_mapping.py:76

# Telegram (to be refactored — imports move to core.auth.*)
from parrot.integrations.telegram.post_auth import PostAuthProvider, PostAuthRegistry  # post_auth.py:38
from parrot.integrations.telegram.oauth2_providers import OAUTH2_PROVIDERS, OAuth2ProviderConfig, get_provider  # oauth2_providers.py
from parrot.integrations.telegram.jira_commands import TelegramOAuthNotifier, register_jira_commands  # jira_commands.py:192, :156
from parrot.integrations.telegram.post_auth_jira import JiraPostAuthProvider  # post_auth_jira.py:37

# Slack (verified: packages/ai-parrot-integrations/src/parrot/integrations/slack/)
from parrot.integrations.slack.wrapper import SlackAgentWrapper  # wrapper.py:68
from parrot.integrations.slack.socket_handler import SlackSocketHandler  # socket_handler.py:20
from parrot.integrations.slack.models import SlackAgentConfig  # models.py:8
from parrot.integrations.slack.security import verify_slack_signature_raw  # security.py:17

# MS Teams (verified: packages/ai-parrot-integrations/src/parrot/integrations/msteams/)
from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper  # wrapper.py:56
from parrot.integrations.msteams.models import MSTeamsAgentConfig  # models.py:13
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/auth/jira_oauth.py
class JiraOAuthManager:  # line 86
    _TOKEN_KEY_PREFIX = "jira:oauth"      # line 37 — Redis key: jira:oauth:{channel}:{user_id}
    _NONCE_KEY_PREFIX = "jira:nonce"      # line 38
    _LOCK_KEY_PREFIX = "lock:jira:refresh"  # line 39
    _TOKEN_TTL_SECONDS = 90 * 24 * 60 * 60  # line 42 — 90 days

    def setup(self) -> None:  # line 134 — wires into aiohttp app, registers callback route

    async def create_authorization_url(  # line 258
        self, channel: str, user_id: str,
        extra_state: dict | None = None,
    ) -> tuple[str, str]:  # returns (url, nonce)

    async def handle_callback(  # line 304
        self, code: str, state: str,
    ) -> tuple[JiraTokenSet, dict]:  # returns (token_set, extra_state)

    async def get_valid_token(  # line 384
        self, channel: str, user_id: str,
    ) -> JiraTokenSet | None:

    async def validate_token(  # line 405
        self, channel: str, user_id: str,
    ) -> JiraTokenSet | None:  # validates with Atlassian, revokes if invalid

    async def revoke(  # line 400
        self, channel: str, user_id: str,
    ) -> None:

class JiraTokenSet(BaseModel):  # line 59, frozen=True
    access_token: str
    refresh_token: str
    expires_at: float
    cloud_id: str
    site_url: str
    account_id: str
    display_name: str
    email: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)

# packages/ai-parrot/src/parrot/services/identity_mapping.py
class IdentityMappingService:  # line 76
    def __init__(self, db_pool: Any) -> None:  # line 95
    async def upsert_identity(  # line 99
        self, nav_user_id: str, auth_provider: str,
        auth_data: Dict[str, Any],
        display_name: Optional[str] = None,
        email: Optional[str] = None,
    ) -> None:

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py
_TELEGRAM_CHANNEL = "telegram"  # line 39
def register_jira_commands(  # line 156
    router: Router, oauth_manager: "JiraOAuthManager",
    session_clearer: Optional[SessionClearer] = None,
) -> None:
class TelegramOAuthNotifier:  # line 192
    def __init__(self, bot: "Bot") -> None:
    async def notify_connected(self, chat_id: int, display_name: str, site_url: str) -> None:
    async def notify_failure(self, chat_id: int, reason: str) -> None:

# packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py
class SlackAgentWrapper:  # line 68
    def __init__(self, agent, config: SlackAgentConfig, app: web.Application):  # line 79
    commands_route = f"/api/slack/{safe_id}/commands"  # line 110
    async def _handle_command(self, request: web.Request) -> web.Response:  # line 290
        # Current built-in commands: help, clear, commands (lines 308-323)
        # Unrecognized commands processed via _safe_answer in background (line 326)

# packages/ai-parrot-integrations/src/parrot/integrations/slack/socket_handler.py
class SlackSocketHandler:  # line 20
    def __init__(self, wrapper: SlackAgentWrapper):
    async def _handle_slash_command(self, payload: Dict[str, Any]) -> None:  # line 266
        # Built-in commands: help, clear, commands (same as wrapper)

# packages/ai-parrot-integrations/src/parrot/integrations/slack/security.py
def verify_slack_signature_raw(  # line 17
    raw_body: bytes, headers: Mapping[str, str],
    signing_secret: str, max_age_seconds: int = 300,
) -> bool:

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py
class MSTeamsAgentWrapper(ActivityHandler, MessageHandler):  # line 56
    def __init__(self, agent, config: MSTeamsAgentConfig, app: web.Application, ...):
    async def on_message_activity(self, turn_context: TurnContext):  # line 367
        # Authorization check: line 370-379
        # Card submissions: line 398-404
        # Voice: line 406-409
        # Dialog continuation: line 412-415
        # Text processing: line 418+
        # No command detection exists today — text goes to agent
    async def handle_request(self, request: web.Request) -> web.Response:  # line 332

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py
class MSTeamsAgentConfig:  # line 13
    name: str
    chatbot_id: str
    client_id: Optional[str] = None  # Microsoft App ID
    client_secret: Optional[str] = None  # Microsoft App Password
    commands: Dict[str, str] = field(default_factory=dict)  # line 36
    # No Jira-related fields today

# packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py
class SlackAgentConfig:  # line 8
    name: str
    chatbot_id: str
    bot_token: Optional[str] = None
    signing_secret: Optional[str] = None
    connection_mode: str = "webhook"  # "webhook" or "socket"
    # No Jira-related fields today
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `SlackCommandRouter` | `SlackAgentWrapper._handle_command` | delegation before background task | `slack/wrapper.py:290` |
| `SlackCommandRouter` | `SlackSocketHandler._handle_slash_command` | delegation before built-in dispatch | `slack/socket_handler.py:266` |
| `MSTeamsCommandRouter` | `MSTeamsAgentWrapper.on_message_activity` | intercept before dialog/agent processing | `msteams/wrapper.py:418` |
| Slack `connect_jira` handler | `JiraOAuthManager.create_authorization_url` | `channel="slack", user_id=f"{team_id}:{user_id}"` | `parrot/auth/jira_oauth.py:258` |
| Teams `connect_jira` handler | `JiraOAuthManager.create_authorization_url` | `channel="msteams", user_id=aad_object_id` | `parrot/auth/jira_oauth.py:258` |
| `SlackOAuthNotifier` | Slack Web API `chat.postMessage` | `slack-sdk` (existing dep) | — |
| `MSTeamsOAuthNotifier` | Bot Framework `ContinueConversationAsync` | `botbuilder-core` (existing dep) | — |
| `jira_oauth_callback` extension | `extra_state["channel"]` dispatch | branch in existing route | `parrot/auth/routes.py` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.integrations.core.auth`~~ — subpackage does not exist today. `integrations/core/` contains only `state.py`. This spec proposes creating `integrations/core/auth/`.
- ~~`parrot.integrations.slack.auth`~~ — does not exist.
- ~~`parrot.integrations.slack.commands`~~ — subpackage does not exist.
- ~~`parrot.integrations.slack.oauth_callback`~~ — does not exist.
- ~~`SlackUserSession`~~ — no equivalent to `TelegramUserSession` exists for Slack today.

…(truncated)…
