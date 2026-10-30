---
id: FW-017
query_id: Q017
type: wiki_related
intent: "Related edges of the generic OAuth2 routes — who mounts them."
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: null
depth: 0
---

# FW-017 — `auth/oauth2_routes.py` is referenced by `auth/oauth2/service.py`, `parrot/conf.py`, `mcp/oauth2_state.py`; tested by `server/tests/unit/test_a2a_resume_trigger.py` (FEAT-260 TASK-1645) and `tests/auth/test_mcp_oauth2_callback.py` (FEAT-262); mounted by `AbstractOAuth2Manager.setup()`

## Summary

Edges: out-`references` → `oauth2/service.py` (IntegrationsService), `conf.py` (`WEB_OAUTH_ALLOWED_ORIGINS`), `mcp/oauth2_state.py`; in-`references` ← `test_a2a_resume_trigger.py`, `test_mcp_oauth2_callback.py`. Defines `make_oauth2_callback(provider_id)` (handler bound to a provider; looks up `app[f'oauth2_manager_{provider_id}']`), `setup_oauth2_routes(app, provider_id, callback_path)` (adds route + excludes it from auth middleware, per FEAT-263 contract `oauth2_routes.py:216`), `_handle_web_callback` (popup postMessage page + persist), `handle_mcp_oauth2_callback` / `setup_mcp_oauth2_callback`, `register_a2a_resume_hook` (nonce → resume suspended A2A task). The mount point is `AbstractOAuth2Manager.setup()` in `auth/oauth2_base.py`, which stores the manager at `app['oauth2_manager_{provider_id}']` and calls `setup_oauth2_routes` with default path `/api/auth/oauth2/{provider_id}/callback`. This is the generic per-provider callback the brainstorm proposes as `/oauth/callback/{provider}` — it exists with a different path shape and a manager-slot convention.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/oauth2_routes.py`
  lines: n/a
  symbol: `make_oauth2_callback`, `setup_oauth2_routes`, `_handle_web_callback`, `handle_mcp_oauth2_callback`, `setup_mcp_oauth2_callback`, `register_a2a_resume_hook`, `_error_response`
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/oauth2_routes.py
- path: `packages/ai-parrot/src/parrot/auth/oauth2_base.py`
  lines: n/a
  symbol: `AbstractOAuth2Manager.setup()` → `app[f'oauth2_manager_{provider_id}']`, `setup_oauth2_routes(app, provider_id, callback_path)`; `_callback_path` default `/api/auth/oauth2/{provider_id}/callback`
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/oauth2_base.py
- path: `packages/ai-parrot-server/tests/unit/test_a2a_resume_trigger.py`
  lines: n/a
  symbol: A2A OAuth-callback resume trigger tests (FEAT-260 / TASK-1645)
  wiki_page_id: file:packages/ai-parrot-server/tests/unit/test_a2a_resume_trigger.py
- path: `tests/auth/test_mcp_oauth2_callback.py`
  lines: n/a
  symbol: MCP OAuth2 callback route tests (FEAT-262 / TASK-1664)
  wiki_page_id: file:tests/auth/test_mcp_oauth2_callback.py
- path: `packages/ai-parrot/src/parrot/mcp/oauth2_state.py`
  lines: n/a
  symbol: shared in-process MCP OAuth2 callback state
  wiki_page_id: file:packages/ai-parrot/src/parrot/mcp/oauth2_state.py

## Notes

`[cross-lane: type=read, intent=oauth2_routes.py full read — confirm which state/channel branches the generic handler supports (web only? telegram?) and how it persists (vault via manager._persist_token + IntegrationsService.persist_credential)]`.
