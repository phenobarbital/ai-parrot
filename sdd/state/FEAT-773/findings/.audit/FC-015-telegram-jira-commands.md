---
id: FC-015
query_id: Q034
type: read
intent: "R2: read Telegram /connect_jira command handlers — how the auth URL is built and the manager reached."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-015 — Telegram exposes /connect_jira, /disconnect_jira, /jira_status; builds URL via JiraOAuthManager.create_authorization_url('telegram', telegram_id, extra_state={chat_id}); TelegramOAuthNotifier pushes completion

## Summary

`parrot/integrations/telegram/jira_commands.py` (233 lines, aiogram). `connect_jira_handler(message, oauth_manager)` uses `user_id = str(message.from_user.id)` (raw Telegram id) and `_TELEGRAM_CHANNEL="telegram"`; calls `validate_token` then `create_authorization_url(_TELEGRAM_CHANNEL, user_id, extra_state={"chat_id": message.chat.id})`, sends an inline button. `disconnect_jira_handler` → `oauth_manager.revoke` + optional `SessionClearer`. `register_jira_commands(router, oauth_manager, session_clearer)` registers `Command("connect_jira")`, `Command("disconnect_jira")`, `Command("jira_status")`. `TelegramOAuthNotifier(bot).notify_connected(chat_id, display_name, site_url)` / `notify_failure` — invoked by the callback route (FC-047). No generic `/connect <provider>`; a separate `office365_commands.py` offers `/connect_office365` (FC-051 notes).

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py`
  lines: 50-88
  symbol: `connect_jira_handler`
  excerpt: |
    user_id = str(message.from_user.id)
    if await oauth_manager.validate_token(_TELEGRAM_CHANNEL, user_id) is not None: ...already connected
    url, _nonce = await oauth_manager.create_authorization_url(_TELEGRAM_CHANNEL, user_id, extra_state={"chat_id": message.chat.id})
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py`
  lines: 156-190
  symbol: `register_jira_commands`
  excerpt: |
    router.message.register(_connect, Command("connect_jira"))
    router.message.register(_disconnect, Command("disconnect_jira"))
    router.message.register(_status, Command("jira_status"))
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py`
  lines: 192-233
  symbol: `TelegramOAuthNotifier`
  excerpt: |
    class TelegramOAuthNotifier:
        def __init__(self, bot: Bot)
        async def notify_connected(self, chat_id, display_name, site_url)
        async def notify_failure(self, chat_id, reason)

## Notes

Brainstorm §3 row '/connect_jira … Jesus says /connect' → the commands are `/connect_jira`, `/disconnect_jira`, `/jira_status` (and `/connect_office365` in office365_commands.py). Completion notification is a direct in-process call from the callback route to the notifier stored on `app['jira_oauth_notifier']` — requires the bot and the HTTP callback to share a process.
