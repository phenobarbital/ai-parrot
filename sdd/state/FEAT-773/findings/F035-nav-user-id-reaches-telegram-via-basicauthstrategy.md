---
id: F035
query_id: [Q055, Q050-F1, Q055-F1]
type: [grep, read]
intent: "R1: Telegram identity link at login — where the Telegram id is mapped to the platform user (login/sso handler)."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 1
merged_from: [FC-036, FC-045, FC-046]
---

# F035 — nav_user_id reaches Telegram via BasicAuthStrategy (/login -> TelegramUserSession.nav_user_id), is embedded in the Jira OAuth state by JiraPostAuthProvider, and written to auth.user_identities (telegram + jira rows) after the combined callback; Teams carries nav_user_id via its auth session

## Summary

**[FC-036]** Grep hits: `telegram/auth.py:484-494` BasicAuth callback sets `nav_user_id = data.get("user_id")` on the session; `telegram/post_auth_jira.py:102-103` puts `extra_state["nav_user_id"] = session.nav_user_id`; `:164-168` resolves nav_user_id from several sources; `:213-236` upserts `telegram` and `jira` identities. `msteams/commands/jira_commands.py:149 _resolve_nav_user_id`, `:265-267` embeds `extra_state["nav_user_id"]`; `msteams/oauth_callback.py:258-284` validates it is numeric before `upsert_identity`. `msteams/auth.py:53-90` `nav_user_id` on the Teams session. `knowledge_upload.py:148` also uses `session.nav_user_id`.

**[FC-045]** 252 lines. `provider_name="jira"`; `__init__(oauth_manager, identity_service, vault_sync)` — vault_sync 'retained for the disconnect path only' since FEAT-735. `build_auth_url` (:68-121) embeds `{"flow":"combined", nav_user_id, nav_display_name, ...}` in `extra_state`. `handle_result` (:123-204) calls `oauth_manager.handle_callback(code, state)`, resolves `nav_user_id` from result/primary_auth_data/extra/session, stamps the Jira identity on the `TelegramUserSession`, then `_write_identity_records` (:206-252) upserts `telegram` and `jira` identities (failures logged, never fail auth).

**[FC-046]** 327 lines (FEAT-225). `MSTeamsOAuthNotifier(adapter, app_id)` with `notify_connected(conversation_ref_dict, display_name, site_url)` / `notify_failure` deserialising `ConversationReference` and calling `adapter.continue_conversation(ref, callback, app_id)`. `handle_msteams_jira_callback(request, token_set, state_payload)` (:182-327): writes `auth.user_identities` only when `nav_user_id` is numeric (AAD GUID is the provider account id, never user_id), returns HTML success/error, fires proactive notification (fire-and-forget). Notifier registered as `app["msteams_jira_oauth_notifier"]` by `MSTeamsAgentWrapper` (TASK-1473). `conversation_reference` is serialised into `extra_state` during `/connect_jira`.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py`
  lines: 477-495
  symbol: `BasicAuthStrategy callback`
  excerpt: |
    nav_user_id = data.get("user_id")
    ... TelegramUserSession(..., nav_user_id=str(nav_user_id), ...)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py`
  lines: 68-121
  symbol: `JiraPostAuthProvider.build_auth_url`
  excerpt: |
    if getattr(session, "nav_user_id", None):
        extra_state["nav_user_id"] = session.nav_user_id
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py`
  lines: 206-252
  symbol: `JiraPostAuthProvider._write_identity_records`
  excerpt: |
    await self._identity.upsert_identity(nav_user_id=str(nav_user_id), auth_provider="telegram", ...)
    await self._identity.upsert_identity(nav_user_id=str(nav_user_id), auth_provider="jira", ...)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/jira_commands.py`
  lines: 149,265-267
  symbol: `_resolve_nav_user_id`
  excerpt: |
    nav_user_id = await _resolve_nav_user_id(turn_context, nav_user_id_resolver)
    if nav_user_id: extra_state["nav_user_id"] = nav_user_id
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py`
  lines: 182-305
  symbol: `handle_msteams_jira_callback`
  excerpt: |
    nav_user_id = extra.get("nav_user_id") or state_payload.get("nav_user_id") or ""
    elif not str(nav_user_id).isdigit(): ...skip
    await identity_service.upsert_identity(nav_user_id=nav_user_id, ...)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py`
  lines: 38-66
  symbol: `JiraPostAuthProvider`
  excerpt: |
    class JiraPostAuthProvider:
        provider_name = "jira"
        def __init__(self, oauth_manager, identity_service, vault_sync)  # vault_sync: disconnect path only (FEAT-735)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py`
  lines: 1-22
  symbol: `module docstring`
  excerpt: |
    Teams uses the Bot Framework proactive messaging pattern: adapter.continue_conversation(ref, callback, app_id). The conversation_reference was serialized to JSON and stored in extra_state during /connect_jira
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py`
  lines: 89-143
  symbol: `MSTeamsOAuthNotifier`
  excerpt: |
    class MSTeamsOAuthNotifier:
        def __init__(self, adapter: BotFrameworkAdapter, app_id: str)
        async def notify_connected(self, conversation_ref_dict, display_name, site_url)

## Notes

**[FC-036]** R1 answered: the Telegram↔platform-user link exists ONLY after `/login` (BasicAuth) and is persisted to `auth.user_identities` (provider `telegram`) by the combined Jira flow — i.e. it is written as a side-effect of connecting Jira, not at plain login. The live tool path still keys Redis by the raw telegram_id (FC-016).

**[FC-045]** Zero-reconnect migration lever: for Telegram users who linked via the combined flow, the Identity Vault already holds the grant under the nav user. Users who ran plain `/connect_jira` without `/login` have only the Redis `jira:oauth:telegram:<id>` copy (sink skips without nav_user_id).

**[FC-046]** Brainstorm S-3b 'Teams ConnectionChannel + proactive message' — the proactive-message mechanism and the aadObjectId→nav_user_id handling already exist for Jira (Bot Framework `botbuilder`, not `TeamsHumanChannel`). Slack has the analogous `slack/oauth_callback.py` (DM via Web API).
