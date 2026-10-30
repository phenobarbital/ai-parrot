---
id: FC-036
query_id: Q055
type: grep
intent: "R1: Telegram identity link at login — where the Telegram id is mapped to the platform user (login/sso handler)."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-036 — nav_user_id reaches Telegram via BasicAuthStrategy (/login -> TelegramUserSession.nav_user_id), is embedded in the Jira OAuth state by JiraPostAuthProvider, and written to auth.user_identities (telegram + jira rows) after the combined callback; Teams carries nav_user_id via its auth session

## Summary

Grep hits: `telegram/auth.py:484-494` BasicAuth callback sets `nav_user_id = data.get("user_id")` on the session; `telegram/post_auth_jira.py:102-103` puts `extra_state["nav_user_id"] = session.nav_user_id`; `:164-168` resolves nav_user_id from several sources; `:213-236` upserts `telegram` and `jira` identities. `msteams/commands/jira_commands.py:149 _resolve_nav_user_id`, `:265-267` embeds `extra_state["nav_user_id"]`; `msteams/oauth_callback.py:258-284` validates it is numeric before `upsert_identity`. `msteams/auth.py:53-90` `nav_user_id` on the Teams session. `knowledge_upload.py:148` also uses `session.nav_user_id`.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py`
  lines: 477-495
  symbol: `BasicAuthStrategy callback`
  excerpt: |
    nav_user_id = data.get("user_id")
    ... TelegramUserSession(..., nav_user_id=str(nav_user_id), ...)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py`
  lines: 100-104
  symbol: `JiraPostAuthProvider.build_auth_url`
  excerpt: |
    if getattr(session, "nav_user_id", None):
        extra_state["nav_user_id"] = session.nav_user_id
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py`
  lines: 206-236
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
  lines: 253-284
  symbol: `handle_msteams_jira_callback`
  excerpt: |
    nav_user_id = extra.get("nav_user_id") or state_payload.get("nav_user_id") or ""
    elif not str(nav_user_id).isdigit(): ...skip
    await identity_service.upsert_identity(nav_user_id=nav_user_id, ...)

## Notes

R1 answered: the Telegram↔platform-user link exists ONLY after `/login` (BasicAuth) and is persisted to `auth.user_identities` (provider `telegram`) by the combined Jira flow — i.e. it is written as a side-effect of connecting Jira, not at plain login. The live tool path still keys Redis by the raw telegram_id (FC-016).
