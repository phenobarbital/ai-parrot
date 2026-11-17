---
id: F017
query_id: Q037
type: grep
intent: "R3: MCP client token_supplier / header_provider / user_id binding points."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-018]
---

# F017 — MCPClientConfig has token_supplier: Callable[[], Optional[str]] (no context), header_provider(ReadonlyContext) → headers, and a user_id field mapped to VaultTokenStore key mcp_oauth_{server}_{user_id}

## Summary

`parrot/mcp/client.py`: `:174 token_supplier: Optional[Callable[[], Optional[str]]]` — zero-arg, so it cannot receive a per-call principal; `:186 header_provider: Optional[Callable[['ReadonlyContext'], Dict[str,str]]]` receives a context; `:234-236 user_id: Optional[str]` with comment 'Maps to VaultTokenStore key: mcp_oauth_{server}_{user_id}'; `get_headers(context)` (:250-290) layers static → auth_credential → header_provider(context).

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/client.py`
  lines: 174
  symbol: `MCPClientConfig.token_supplier`
  excerpt: |
    token_supplier: Optional[Callable[[], Optional[str]]] = None
- path: `packages/ai-parrot/src/parrot/mcp/client.py`
  lines: 186
  symbol: `MCPClientConfig.header_provider`
  excerpt: |
    header_provider: Optional[Callable[['ReadonlyContext'], Dict[str, str]]] = None
- path: `packages/ai-parrot/src/parrot/mcp/client.py`
  lines: 234-236
  symbol: `MCPClientConfig.user_id`
  excerpt: |
    # Maps to VaultTokenStore key: mcp_oauth_{server}_{user_id}.
    user_id: Optional[str] = field(default=None)
- path: `packages/ai-parrot/src/parrot/mcp/client.py`
  lines: 250-290
  symbol: `MCPClientConfig.get_headers`
  excerpt: |
    3. Dynamic headers from header_provider(context)
    if self.header_provider and context: dynamic = self.header_provider(context)

## Notes

R3: `token_supplier` does NOT receive a user context (brainstorm asked); `header_provider(ReadonlyContext)` does. `user_id` is bound on the config (add-time), confirming the anti-pattern the brainstorm names.
