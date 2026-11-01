---
id: FC-057
query_id: Q041-F1
type: read
intent: "Follow-up: integrations/manager.py sink wiring, UserSocketManager Redis setup, and auth templates directory."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: FC-022
depth: 1
---

# FC-057 — IntegrationBotManager builds IdentityVaultCredentialSink from app['authdb'] (optional, Redis-only fallback); UserSocketManager connects its own Redis pool on startup for channels/user-info; parrot/auth/templates holds web_oauth_success.html + web_oauth_error.html

## Summary

`integrations/manager.py:85-107` `_build_credential_sink(app)` returns `IdentityVaultCredentialSink(db_pool=app['authdb'])` or None with warning 'Jira refreshes will update Redis only'. `handlers/user.py:115-135` `_on_startup` creates `aioredis.ConnectionPool.from_url(self.redis_url, max_connections=5000)`, registers default channels; `register_channel` defined at :151 and :489 (duplicate). `parrot/auth/templates/`: `web_oauth_error.html` (770B), `web_oauth_success.html` (843B).

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/manager.py`
  lines: 85-107
  symbol: `_build_credential_sink`
  excerpt: |
    db_pool = app.get("authdb") if app is not None else None
    if db_pool is None: return None
    return IdentityVaultCredentialSink(db_pool=db_pool)
    # warning: "IdentityVaultCredentialSink unavailable; Jira refreshes will update Redis only."
- path: `packages/ai-parrot-server/src/parrot/handlers/user.py`
  lines: 115-135
  symbol: `UserSocketManager._on_startup`
  excerpt: |
    self.pool = aioredis.ConnectionPool.from_url(self.redis_url, encoding="utf8", decode_responses=True, max_connections=5000)
    for channel in self.default_channels: self.register_channel(channel)
- path: `packages/ai-parrot/src/parrot/auth/templates/web_oauth_success.html`
  lines: —
  symbol: `template`
  excerpt: |
    postMessage success page used by oauth2_routes / routes web branch

## Notes

The Jira callback success page for web already `postMessage`s to the opener (brainstorm §5 item 7).
