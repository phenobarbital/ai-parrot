---
id: F032
query_id: Q052
type: read
intent: "O365: read the Office 365 delegated OAuth2 integration doc — what shipped (routes, page)."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-033]
---

# F032 — docs/integrations/office365-oauth2.md documents the shipped O365 delegated flow: popup -> POST /api/v1/agents/integrations/{agent}/o365/connect -> GET /api/auth/oauth2/o365/callback -> vault oauth2_o365_web_{user_id} + Redis oauth2:o365:web:{user_id}; PKCE + nonce in Redis

## Summary

199 lines. Architecture: frontend popup → `POST /api/v1/agents/integrations/operator/o365/connect` → Microsoft consent (PKCE code_verifier + nonce in Redis, 10-min TTL) → `GET /api/auth/oauth2/o365/callback?code&state` → `vault.store(user_id, "oauth2_o365_web_{user_id}", token)` + `redis.set("oauth2:o365:web:{user_id}", token, ex=90d)`. Token lifecycle table: hot cache `oauth2:o365:{channel}:{uid}` 90d; refresh lock `lock:oauth2:o365:refresh:...` 10s; nonce+PKCE `oauth2:o365:nonce:<state>` 10 min one-shot. `get_valid_token`: Redis → vault fallback (refill) → locked refresh. `revoke` purges both. Env: `O365_REDIRECT_URI=https://host/api/auth/oauth2/o365/callback`, `OAUTH2_REDIS_URL`; `manager.setup()` mounts the callback.

## Citations

- path: `docs/integrations/office365-oauth2.md`
  lines: 13-37
  symbol: `Architecture summary`
  excerpt: |
    Frontend popup --- POST /api/v1/agents/integrations/operator/o365/connect
    (PKCE code_verifier + nonce stored in Redis, 10-min TTL)
    GET /api/auth/oauth2/o365/callback?code=...&state=...
    |- vault.store(user_id, "oauth2_o365_web_{user_id}", token)
    |- redis.set("oauth2:o365:web:{user_id}", token, ex=90d)
- path: `docs/integrations/office365-oauth2.md`
  lines: 148-165
  symbol: `Token lifecycle`
  excerpt: |
    | Hot cache | Redis oauth2:o365:{channel}:{uid} | 90 days |
    | Refresh lock | Redis lock:oauth2:o365:refresh:... | 10 s |
    | Nonce + PKCE | Redis oauth2:o365:nonce:<state> | 10 minutes | one-shot |

## Notes

R6 (Microsoft): PKCE + offline_access + tenant `common` handled; refresh lifetime not stated. O365 web connect flow shipped in THIS repo's admin UI (not the Oct-2025 'TROC UI page' the brainstorm recalls).
