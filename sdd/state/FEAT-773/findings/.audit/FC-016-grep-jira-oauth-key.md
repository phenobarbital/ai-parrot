---
id: FC-016
query_id: Q035
type: grep
intent: "R2: enumerate every reader/writer of the legacy Redis key prefix jira:oauth."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-016 — Only JiraOAuthManager reads/writes `jira:oauth:*`; one comment in the Telegram wrapper documents the key; no other reader

## Summary

Case-insensitive grep for `jira:oauth|jira_oauth:` across `packages/` (excluding build/ and tests/): 2 source hits — `parrot/auth/jira_oauth.py:44` (the prefix constant) and `integrations/telegram/wrapper.py:1288` (docstring explaining the PermissionContext carries telegram_id so `JiraToolkit._pre_execute` can look up `jira:oauth:telegram:<telegram_id>`). Test file `tests/unit/test_jira_oauth_manager.py` also references it.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/jira_oauth.py`
  lines: 44
  symbol: `_TOKEN_KEY_PREFIX`
  excerpt: |
    _TOKEN_KEY_PREFIX = "jira:oauth"  # jira:oauth:{channel}:{user_id}
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py`
  lines: 1284-1292
  symbol: `_build_permission_context docstring`
  excerpt: |
    The context carries channel="telegram" and the telegram_id as the session user_id so JiraToolkit._pre_execute can look up the per-user OAuth2 3LO token in Redis (key jira:oauth:telegram:<telegram_id>)

## Notes

Migration blast radius for the legacy key is a single writer/reader (the manager). Toolkits never touch the key directly — they go through `OAuthCredentialResolver` → `get_valid_token`.
