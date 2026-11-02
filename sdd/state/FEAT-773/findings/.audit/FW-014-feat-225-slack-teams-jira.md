---
id: FW-014
query_id: Q014
type: wiki_page
intent: "Read spec: jiratoolkit-integrations-oauth2 (FEAT-225) — Slack/Teams Jira OAuth callbacks + notifications."
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: null
depth: 0
---

# FW-014 — FEAT-225 (approved, 8 tasks done 2026-06-04): Slack AND MS Teams already have `/connect_jira` `/disconnect_jira` `/jira_status`, one shared callback `/api/auth/jira/callback` dispatching on `extra_state["channel"]`, Slack DM + Teams proactive notifiers; shared auth primitives lifted to `integrations/core/auth/`

## Summary

The brainstorm's claim that only a Jira-specific Telegram command exists is wrong on breadth: FEAT-225 added `SlackCommandRouter` + `slack/commands/jira_commands.py`, `MSTeamsCommandRouter` + `msteams/commands/jira_commands.py` (Adaptive Card button), `slack/oauth_callback.py::handle_slack_jira_callback` (DM via `chat.postMessage`), `msteams/oauth_callback.py::handle_msteams_jira_callback` (proactive message via `adapter.continue_conversation`, `conversation_reference` stored in `extra_state`), and `integrations/core/auth/{post_auth.py, oauth2_providers.py}` (`PostAuthProvider`, `PostAuthRegistry`, `OAUTH2_PROVIDERS`). Redis key stays `jira:oauth:{channel}:{user_id}` with `channel ∈ {telegram, slack, msteams, web}` and user_id = telegram_id / `f"{team_id}:{slack_user_id}"` / `aad_object_id` / nav user id — i.e. the hot cache IS channel-keyed exactly as the brainstorm fears, and every channel reconnects separately. Decisions recorded: single Atlassian app + single callback URL dispatching by `extra_state.channel`; `/disconnect_jira` deletes local tokens only (no provider revoke) and preserves identity rows; multi-tenant Slack and Teams.

## Citations

- path: `sdd/specs/jiratoolkit-integrations-oauth2.spec.md`
  lines: n/a
  symbol: FEAT-225 §2–§3, §6 contract (`jira_oauth.py:37 _TOKEN_KEY_PREFIX="jira:oauth"`, `:38 _NONCE_KEY_PREFIX`, `:39 _LOCK_KEY_PREFIX`, `:42 TTL 90d`, `:258 create_authorization_url(channel, user_id, extra_state)`, `:304 handle_callback`, `:384 get_valid_token`, `:405 validate_token`, `:400 revoke`)
  wiki_page_id: ledger::spec:jiratoolkit-integrations-oauth2.spec (score=0.50)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/jira_commands.py`
  lines: n/a
  symbol: Slack `/connect_jira` handlers, `_SLACK_CHANNEL = "slack"`
  wiki_page_id: file:packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/jira_commands.py (score=0.31)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/jira_commands.py`
  lines: n/a
  symbol: Teams `/connect_jira` handlers, `_get_user_id` (aad_object_id), `_MSTEAMS_CHANNEL = "msteams"`
  wiki_page_id: file:packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/jira_commands.py (score=0.14)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py`
  lines: n/a
  symbol: `handle_slack_jira_callback`, `SlackOAuthNotifier`
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py`
  lines: n/a
  symbol: `handle_msteams_jira_callback`, `MSTeamsOAuthNotifier`
- path: `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/__init__.py`
  lines: n/a
  symbol: shared auth primitives (`PostAuthProvider`, `PostAuthRegistry`, `OAUTH2_PROVIDERS`)
  wiki_page_id: file:packages/ai-parrot-integrations/src/parrot/integrations/core/auth/__init__.py (score=0.28)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py`
  lines: n/a
  symbol: `register_jira_commands`, `TelegramOAuthNotifier`, `_TELEGRAM_CHANNEL = "telegram"`
  wiki_page_id: file:packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py (score=0.53)
- path: `sdd/tasks/index/jiratoolkit-integrations-oauth2.json`
  lines: n/a
  symbol: TASK-1467..1474 all `done`

## Notes

The brainstorm's "`/connect <provider>` generic command" indeed does not exist — every channel has Jira-specific commands (confirmed absent in the wiki). `[cross-lane: type=grep, intent=grep 'jira:oauth' to enumerate readers of the channel-keyed Redis cache across packages]`.
