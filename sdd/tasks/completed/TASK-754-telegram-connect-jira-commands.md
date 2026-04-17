# TASK-754: Telegram Integration — /connect_jira Commands

**Feature**: FEAT-107 — Jira OAuth 2.0 (3LO) Per-User Authentication
**Spec**: `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-751, TASK-752
**Assigned-to**: unassigned

---

## Context

Module 8 of the spec. Telegram users need a way to authorize their Jira account. This task adds bot commands `/connect_jira`, `/disconnect_jira`, and `/jira_status` that generate auth URLs (deep links), handle post-callback notification, and show connection status.

---

## Scope

- Add `/connect_jira` command: generates Jira OAuth authorization URL and sends it as an inline button.
- Add `/disconnect_jira` command: revokes tokens via `JiraOAuthManager.revoke()`.
- Add `/jira_status` command: shows whether the user has a valid Jira connection.
- Create `TelegramOAuthNotifier` that sends a confirmation message to the user after successful OAuth callback.
- Register commands in `TelegramAgentWrapper`.
- Write unit tests.

**NOT in scope**: AgenTalk integration (TASK-755), JiraToolkit logic (TASK-753), Mini App WebView flow.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/jira_commands.py` | CREATE | /connect_jira, /disconnect_jira, /jira_status handlers |
| `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Register Jira commands on router |
| `packages/ai-parrot/tests/unit/test_telegram_jira_commands.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiogram import Bot, Router, F  # verified: packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py:19
from aiogram.filters import Command  # verified: wrapper.py:28
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton  # verified: wrapper.py:22-27
from parrot.auth.jira_oauth import JiraOAuthManager  # created by TASK-751
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py:49
class TelegramAgentWrapper:
    # Uses aiogram Router for command registration
    # Existing auth strategies: BasicAuthStrategy, OAuth2AuthStrategy
    # from .auth import TelegramUserSession, BasicAuthStrategy, OAuth2AuthStrategy

# packages/ai-parrot/src/parrot/integrations/telegram/oauth2_providers.py
# Existing OAuth2 provider registry — could add "atlassian" entry
@dataclass(frozen=True)
class OAuth2ProviderConfig:
    name: str
    authorization_url: str
    token_url: str
    userinfo_url: str
    default_scopes: list[str] = field(default_factory=list)

OAUTH2_PROVIDERS: Dict[str, OAuth2ProviderConfig]  # currently only has "google"
```

### Does NOT Exist
- ~~`/connect_jira` command~~ — not registered yet (this task adds it)
- ~~`TelegramOAuthNotifier`~~ — does NOT exist yet (this task creates it)
- ~~`jira_commands.py`~~ — module does NOT exist yet (this task creates it)

---

## Implementation Notes

### Command Handlers
```python
# packages/ai-parrot/src/parrot/integrations/telegram/jira_commands.py

async def connect_jira_handler(message: Message, oauth_manager: JiraOAuthManager):
    user_id = str(message.from_user.id)
    channel = "telegram"

    if await oauth_manager.is_connected(channel, user_id):
        await message.reply("You're already connected to Jira. Use /jira_status to see details.")
        return

    url, _ = await oauth_manager.create_authorization_url(channel, user_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Connect Jira Account", url=url)]
    ])
    await message.reply(
        "Click the button below to authorize your Jira account:",
        reply_markup=keyboard,
    )


async def disconnect_jira_handler(message: Message, oauth_manager: JiraOAuthManager):
    user_id = str(message.from_user.id)
    await oauth_manager.revoke("telegram", user_id)
    await message.reply("Your Jira account has been disconnected.")


async def jira_status_handler(message: Message, oauth_manager: JiraOAuthManager):
    user_id = str(message.from_user.id)
    token = await oauth_manager.get_valid_token("telegram", user_id)
    if token:
        await message.reply(
            f"Connected to Jira as {token.display_name}\n"
            f"Site: {token.site_url}"
        )
    else:
        await message.reply("Not connected to Jira. Use /connect_jira to link your account.")
```

### Key Constraints
- The `JiraOAuthManager` must be accessible from command handlers (pass via middleware, bot data, or dependency injection).
- Use inline keyboard buttons with `url=` for the OAuth link (not callback buttons).
- Deep link flow: user clicks button → browser opens Atlassian consent → redirect to callback → TASK-752 handles it.
- The `TelegramOAuthNotifier` is called by the OAuth callback route (TASK-752) to send a confirmation message back to the user's Telegram chat.

---

## Acceptance Criteria

- [ ] `/connect_jira` generates and sends auth URL as inline button
- [ ] `/connect_jira` when already connected shows appropriate message
- [ ] `/disconnect_jira` revokes tokens and confirms
- [ ] `/jira_status` shows connection status with user name and site
- [ ] Commands registered in TelegramAgentWrapper router
- [ ] Tests pass: `pytest packages/ai-parrot/tests/unit/test_telegram_jira_commands.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_telegram_jira_commands.py
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestConnectJiraHandler:
    @pytest.mark.asyncio
    async def test_sends_auth_url(self):
        # Mock message and oauth_manager
        # Verify message.reply called with InlineKeyboardMarkup containing URL
        pass

    @pytest.mark.asyncio
    async def test_already_connected(self):
        # oauth_manager.is_connected returns True
        # Verify "already connected" message
        pass


class TestDisconnectJiraHandler:
    @pytest.mark.asyncio
    async def test_revokes_and_confirms(self):
        # Verify oauth_manager.revoke called, reply sent
        pass


class TestJiraStatusHandler:
    @pytest.mark.asyncio
    async def test_connected_shows_details(self):
        # token exists → shows display_name and site
        pass

    @pytest.mark.asyncio
    async def test_not_connected(self):
        # no token → suggests /connect_jira
        pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md` Module 8
2. **Check dependencies** — verify TASK-751, TASK-752 are in `tasks/completed/`
3. **Verify the Codebase Contract** — read `wrapper.py` for how commands are registered
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-754-telegram-connect-jira-commands.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus)
**Date**: 2026-04-17
**Notes**:
- Created ``parrot.integrations.telegram.jira_commands`` with:
    * ``connect_jira_handler`` — sends the authorization URL as an inline
      button (``InlineKeyboardMarkup``/``InlineKeyboardButton`` with
      ``url=``), embedding the chat id in ``extra_state`` so the callback
      can notify back.
    * ``disconnect_jira_handler`` — revokes the user's tokens via
      ``JiraOAuthManager.revoke``.
    * ``jira_status_handler`` — reports connection status with display
      name and site.
    * ``register_jira_commands(router, oauth_manager)`` — wires the three
      commands onto an aiogram ``Router`` via closures over the manager.
    * ``TelegramOAuthNotifier`` — called by the callback route to push a
      confirmation message; logs and swallows errors so the callback
      cannot fail because of a notification hiccup.
- ``TelegramAgentWrapper._register_jira_commands`` reads
  ``config.jira_oauth_manager`` and registers the commands when present.
  The new field is opt-in — deployments that don't set it are unchanged.
- Tests: ``packages/ai-parrot/tests/unit/test_telegram_jira_commands.py``
  — 10 passing.

**Deviations from spec**: none.  Dependency injection uses closures over
the OAuth manager rather than aiogram middleware; this keeps the module
usable from a plain aiogram ``Router`` without requiring additional
infrastructure.
