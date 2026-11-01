---
id: FW-010
query_id: Q010
type: wiki_page
intent: "Read task: TASK-1676 MCP per-user token injection via broker — MCP token_supplier state."
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: null
depth: 0
---

# FW-010 — TASK-1676 (FEAT-264, done): MCP per-user bearer is injected at CALL time through `MCPClientConfig.header_provider`/`token_supplier` fed by `current_credential()`; `MCPClientConfig` still carries a `user_id` field

## Summary

R3 answer: the MCP client does not hold a stand-alone `OAuthManager` any more (TASK-1665 removed it, FEAT-262 replaced it with `MCPOAuth2Config` + presets registry in `parrot/mcp/oauth2_config.py`, callback in `auth/oauth2_routes.py::handle_mcp_oauth2_callback`, shared state in `parrot/mcp/oauth2_state.py`). `MCPClientConfig` (`parrot/mcp/client.py:132` at spec time) has `auth_credential`, `auth_type`, `auth_config`, `token_supplier`, `headers`, `header_provider: Callable[[ReadonlyContext], Dict[str,str]]`, `oauth2`, `auth_preset`, `user_id`, `transport`; `get_headers(context)` precedence static → auth_credential → header_provider(context). TASK-1676 made `parrot/tools/mcp_mixin.py` pass the per-user context so a tool with `credential_provider` + MCP transport sends `Authorization: Bearer <broker token>` resolved per call — i.e. the brainstorm's item 5 ("token_supplier becomes lambda ctx: resolver.resolve(ctx.principal); user_id no longer bound at add time") is partly done: call-time resolution exists, but the `user_id` field on `MCPClientConfig` and `add_mcp_server(config, context)` remain. Tests: `packages/ai-parrot/tests/unit/test_mcp_per_user_token.py`.

## Citations

- path: `sdd/tasks/completed/TASK-1676-mcp-per-user-token-injection.md`
  lines: n/a
  symbol: scope, contract (`MCPClientConfig` fields, `get_headers(context)`, `mcp_mixin.py:57 add_mcp_server(config, context)`)
  wiki_page_id: file:sdd/tasks/completed/TASK-1676-mcp-per-user-token-injection.md
- path: `packages/ai-parrot/src/parrot/mcp/client.py`
  lines: n/a
  symbol: `MCPClientConfig` (`token_supplier`, `header_provider`, `user_id`, `oauth2`, `auth_preset`), `get_headers`
- path: `packages/ai-parrot/src/parrot/tools/mcp_mixin.py`
  lines: n/a
  symbol: `add_mcp_server(self, config, context=None)`
- path: `packages/ai-parrot/src/parrot/mcp/oauth2_config.py`
  lines: n/a
  symbol: `MCPOAuth2Config` models + presets registry (FEAT-262 TASK-1659)
  wiki_page_id: file:packages/ai-parrot/src/parrot/mcp/oauth2_config.py (score=0.11)
- path: `packages/ai-parrot/src/parrot/mcp/oauth2_state.py`
  lines: n/a
  symbol: shared in-process state for MCP OAuth2 callback coordination
  wiki_page_id: file:packages/ai-parrot/src/parrot/mcp/oauth2_state.py
- path: `sdd/tasks/completed/TASK-1665-oauth-manager-removal.md`
  lines: n/a
  symbol: `OAuthManager` removed from `parrot.mcp.oauth`; factory migration to `MCPOAuth2Config`
  wiki_page_id: file:sdd/tasks/completed/TASK-1665-oauth-manager-removal.md (score=0.75)
- path: `packages/ai-parrot/tests/unit/test_mcp_per_user_token.py`
  lines: n/a
  symbol: token-injection tests

## Notes

Ledger `issue:f010a27ccadd`: `create_netsuite_mcp_server` lacks the `token_store` param the test injects (FEAT-562 M7 spin-off) — NetSuite factory drift. `[cross-lane: type=grep, intent=whether add_oauth_mcp_server still exists and its current signature; whether MCPClientConfig.user_id is read anywhere]`.
