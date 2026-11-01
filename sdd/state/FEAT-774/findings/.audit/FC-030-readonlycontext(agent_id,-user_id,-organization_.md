---
id: FC-030
query_id: Q044
type: read
intent: "MCP context module"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-030 — ReadonlyContext(agent_id, user_id, organization_id, roles, scopes, ...) frozen; MCPSessionManager caches sessions by headers

## Summary

`parrot/mcp/context.py` defines `ReadonlyContext` (frozen pydantic: `agent_id`, optional `user_id`, `organization_id`, `roles`, `scopes`, `conversation_id`, `metadata`) used by `header_provider(ReadonlyContext)` in the MCP client, plus `MCPSessionManager` (sessions cached by header hash, retry on `TransientMCPError`). `_CREDENTIAL_VAR` is NOT in this module (it is referenced from client.py; location not confirmed here).

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/context.py`
  lines: 15-44
  symbol: `ReadonlyContext`
  excerpt: |
    class ReadonlyContext(BaseModel):
        agent_id: str; user_id: Optional[str] = None; organization_id: Optional[str] = None
        roles: List[str] = []; scopes: List[str] = []; conversation_id: Optional[str] = None
        model_config = ConfigDict(frozen=True)

- path: `packages/ai-parrot/src/parrot/mcp/context.py`
  lines: 105-136
  symbol: `MCPSessionManager._session_key`
  excerpt: |
    return hash(tuple(sorted(headers.items())))


## Notes

[cross-lane: type=grep, intent=locate `_CREDENTIAL_VAR` definition (expected parrot/tools/abstract.py or tools/manager.py) — S-1 M9 cites client.py:242/282 only]
