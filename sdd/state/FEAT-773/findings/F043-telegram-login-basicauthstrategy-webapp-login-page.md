---
id: F043
query_id: Q055-F2
type: read
intent: "Follow-up: Telegram login path — BasicAuthStrategy sets nav_user_id; combined_callback reunites BasicAuth + Jira; /connect_office365 exists."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: FC-036
depth: 1
merged_from: [FC-051]
---

# F043 — Telegram /login (BasicAuthStrategy, WebApp login page) stores nav_user_id on the in-memory TelegramUserSession; combined_callback.py chains Jira after BasicAuth; office365_commands.py adds /connect_office365 gated on /login with a Microsoft provider

## Summary

`telegram/auth.py` (BasicAuthStrategy :377+, callback :477-495 sets `nav_user_id=str(data.get("user_id"))`; `TelegramUserSession` fields :70-201 incl. `nav_user_id`, Jira identity fields). `telegram/combined_callback.py` ('Combined BasicAuth + secondary OAuth callback for the Telegram WebApp'; BasicAuth result carried across the Jira redirect in state). `telegram/office365_commands.py`: `/connect_office365` requires `/login` with a Microsoft provider ('Current /login provider is not Microsoft'). Directory listing also shows `oauth2_callback.py`, `mcp_commands.py`, `operator_commands.py`.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py`
  lines: 477-495
  symbol: `BasicAuthStrategy (callback)`
  excerpt: |
    nav_user_id = data.get("user_id")
    ... nav_user_id=str(nav_user_id)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/combined_callback.py`
  lines: 1-12
  symbol: `module docstring`
  excerpt: |
    Combined BasicAuth + secondary OAuth callback for the Telegram WebApp. After the login page completes BasicAuth and redirects the user to a secondary provider ... The BasicAuth result itself is carried across the Jira redirect via the state
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/office365_commands.py`
  lines: 4,44,53,101
  symbol: `/connect_office365`
  excerpt: |
    /login when the wrapper is configured with auth_method: oauth2
    "You need to authenticate first. Use /login, then try /connect_office365."
    "Current /login provider is not Microsoft."

## Notes

The Telegram↔platform link is session-held (in-memory) and only persisted to `auth.user_identities` through the Jira combined flow. A per-provider command (`/connect_jira`, `/connect_office365`) exists per provider — the N×M duplication the brainstorm describes is real on the channel side.
