---
id: F005
query_id: Q024
type: read
intent: "R1/R4: read the generic OAuth2 callback routes — path, state handling, channel branch, auth exclusion."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-005]
---

# F005 — Generic per-provider OAuth2 callback factory exists (make_oauth2_callback / setup_oauth2_routes) with web postMessage page, A2A resume hook and navigator-auth exclude_list; plus a separate MCP callback

## Summary

`parrot/auth/oauth2_routes.py` (434 lines). `make_oauth2_callback(provider_id)` builds an aiohttp handler: validates code/state, calls `manager.handle_callback(code, state)`, reads `channel = state_payload.get("channel","web")`; for web it persists via `IntegrationsService.persist_credential` and renders `templates/web_oauth_success.html` (postMessage to opener with validated `return_origin`). A2A branch (FEAT-260/TASK-1645) resumes a suspended task via `register_a2a_resume_hook`. `setup_oauth2_routes(app, provider_id, manager, callback_path)` mounts `GET <callback_path>` idempotently and appends it to `navigator_auth.conf.exclude_list`. A second route `GET /api/auth/oauth2/mcp/callback` (`handle_mcp_oauth2_callback`) resolves pending MCP flows via `parrot.mcp.oauth2_state`. The Jira-specific `/api/auth/jira/callback` remains separate (routes.py).

## Citations

- path: `packages/ai-parrot/src/parrot/auth/oauth2_routes.py`
  lines: 123-198
  symbol: `_handle_web_callback`
  excerpt: |
    async def _handle_web_callback(...):
        # validates return_origin allowlist, persists via IntegrationsService, renders web_oauth_success.html
- path: `packages/ai-parrot/src/parrot/auth/oauth2_routes.py`
  lines: 200-281
  symbol: `make_oauth2_callback`
  excerpt: |
    def make_oauth2_callback(provider_id: str):
        async def handler(request):
            token_set, state_payload = await manager.handle_callback(code, state)
            channel = state_payload.get("channel", "web")
            if channel == "web": ...
- path: `packages/ai-parrot/src/parrot/auth/oauth2_routes.py`
  lines: 283-310
  symbol: `setup_oauth2_routes`
  excerpt: |
    def setup_oauth2_routes(app, ...):
        app.router.add_get(callback_path, handler)
        from navigator_auth.conf import exclude_list
        if callback_path not in exclude_list: exclude_list.append(callback_path)
- path: `packages/ai-parrot/src/parrot/auth/oauth2_routes.py`
  lines: 314-434
  symbol: `handle_mcp_oauth2_callback`
  excerpt: |
    _MCP_CALLBACK_PATH = "/api/auth/oauth2/mcp/callback"
    async def handle_mcp_oauth2_callback(request): resolved = resolve_pending_callback(state, code)
- path: `packages/ai-parrot/src/parrot/auth/oauth2_routes.py`
  lines: 80-86
  symbol: `_TEMPLATES_DIR`
  excerpt: |
    (_TEMPLATES_DIR / "web_oauth_success.html").read_text()
    (_TEMPLATES_DIR / "web_oauth_error.html").read_text()

## Notes

Brainstorm proposes `/oauth/callback/{provider}` as new → a per-provider callback factory already exists at `/api/auth/oauth2/{provider}/callback` (path per docs FC-033). Auth-exclusion mechanism = `navigator_auth.conf.exclude_list`. Completion → channel is a direct branch in the handler (web persist/postMessage; A2A resume), not an event.
