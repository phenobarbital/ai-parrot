---
type: Concept
title: create_perplexity_mcp_server()
id: func:parrot.mcp.integration.create_perplexity_mcp_server
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create configuration for Perplexity MCP server.
---

# create_perplexity_mcp_server

```python
def create_perplexity_mcp_server(api_key: str, *, name: str='perplexity', timeout_ms: int=600000, **kwargs) -> MCPServerConfig
```

Create configuration for Perplexity MCP server.

The Perplexity MCP server provides 4 tools:
- perplexity_search: Direct web search via Search API
- perplexity_ask: Conversational AI with sonar-pro model
- perplexity_research: Deep research with sonar-deep-research
- perplexity_reason: Advanced reasoning with sonar-reasoning-pro

Args:
    api_key: Perplexity API key (get from perplexity.ai/account/api)
    name: Server name for tool prefixing
    timeout_ms: Request timeout (default 600000ms for deep research)
    **kwargs: Additional MCPServerConfig parameters

Returns:
    MCPServerConfig configured for Perplexity

Example:
    >>> config = create_perplexity_mcp_server(
    ...     api_key=os.environ["PERPLEXITY_API_KEY"]
    ... )
    >>> await agent.add_mcp_server(config)
