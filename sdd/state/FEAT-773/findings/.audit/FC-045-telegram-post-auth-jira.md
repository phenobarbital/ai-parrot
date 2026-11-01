---
id: FC-045
query_id: Q050-F1
type: read
intent: "Follow-up: read telegram/post_auth_jira.py — the combined BasicAuth + Jira flow."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: FC-031
depth: 1
---

# FC-045 — JiraPostAuthProvider (Telegram combined login) embeds nav_user_id/BasicAuth payload in the Jira OAuth state, lets JiraOAuthManager.handle_callback write Redis (+ sink), then upserts telegram+jira rows in auth.user_identities; no longer writes VaultTokenSync

## Summary

252 lines. `provider_name="jira"`; `__init__(oauth_manager, identity_service, vault_sync)` — vault_sync 'retained for the disconnect path only' since FEAT-735. `build_auth_url` (:68-121) embeds `{"flow":"combined", nav_user_id, nav_display_name, ...}` in `extra_state`. `handle_result` (:123-204) calls `oauth_manager.handle_callback(code, state)`, resolves `nav_user_id` from result/primary_auth_data/extra/session, stamps the Jira identity on the `TelegramUserSession`, then `_write_identity_records` (:206-252) upserts `telegram` and `jira` identities (failures logged, never fail auth).

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py`
  lines: 38-66
  symbol: `JiraPostAuthProvider`
  excerpt: |
    class JiraPostAuthProvider:
        provider_name = "jira"
        def __init__(self, oauth_manager, identity_service, vault_sync)  # vault_sync: disconnect path only (FEAT-735)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py`
  lines: 68-121
  symbol: `JiraPostAuthProvider.build_auth_url`
  excerpt: |
    extra_state = {"flow": "combined", ...}
    if getattr(session, "nav_user_id", None): extra_state["nav_user_id"] = session.nav_user_id
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py`
  lines: 206-252
  symbol: `JiraPostAuthProvider._write_identity_records`
  excerpt: |
    await self._identity.upsert_identity(nav_user_id=str(nav_user_id), auth_provider="telegram", provider_user_id=str(telegram_id), ...)
    await self._identity.upsert_identity(nav_user_id=str(nav_user_id), auth_provider="jira", provider_user_id=account_id, ...)

## Notes

Zero-reconnect migration lever: for Telegram users who linked via the combined flow, the Identity Vault already holds the grant under the nav user. Users who ran plain `/connect_jira` without `/login` have only the Redis `jira:oauth:telegram:<id>` copy (sink skips without nav_user_id).
