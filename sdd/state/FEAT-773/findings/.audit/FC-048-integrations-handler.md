---
id: FC-048
query_id: Q044-F1
type: read
intent: "Follow-up: read handlers/integrations.py — how IntegrationsHandler derives user_id and validates origin."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: FC-025
depth: 1
---

# FC-048 — IntegrationsHandler derives user_id from request['user_id'] or the navigator session (never the body), validates return_origin against WEB_OAUTH_ALLOWED_ORIGINS, and delegates to IntegrationsService

## Summary

`handlers/integrations.py` (server). `IntegrationsHandler(BaseView)`; `_get_user_id()` (:43-62) reads `request.get("user_id")` then session `user_id|id|username`; `get()` lists; `_post_connect()` (:109-160) requires user (401), body `return_origin` or `Origin` header (400), allowlist check, `IntegrationsService().start_connect(user_id, agent_id, provider, return_origin)`; `_post_enable`, `delete` similar. Four routes documented at :3-11.

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/integrations.py`
  lines: 43-62
  symbol: `IntegrationsHandler._get_user_id`
  excerpt: |
    user_id = self.request.get("user_id")
    if not user_id: session = await get_session(self.request); user_id = session.get("user_id") or session.get("id") or session.get("username")
- path: `packages/ai-parrot-server/src/parrot/handlers/integrations.py`
  lines: 109-160
  symbol: `IntegrationsHandler._post_connect`
  excerpt: |
    user_id = await self._get_user_id()
    if not user_id: return 401
    return_origin = body.get("return_origin") or self.request.headers.get("Origin")
    if return_origin not in WEB_OAUTH_ALLOWED_ORIGINS: return 400
    resp = await svc.start_connect(user_id, agent_id, provider, return_origin)

## Notes

Brainstorm constraint 'principal always from the authenticated session; never from the body' is already satisfied by the existing web API.
