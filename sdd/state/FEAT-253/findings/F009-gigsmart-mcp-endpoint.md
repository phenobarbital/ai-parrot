---
id: F009
slug: gigsmart-mcp-endpoint
query: "GigSmart MCP integration"
type: web
---

## Finding: GigSmart has a native MCP endpoint

### MCP URL:
- `requester-mcp.prod.gigsmart.com/mcp`

### Details:
- OAuth-based authentication
- Compatible with Claude, Gemini, and ChatGPT
- Announced April 2026 blog post by Jason Waldrip

### Implication:
- GigSmart already exposes an MCP server
- ai-parrot could consume it via MCP client integration instead of (or in addition to) building a custom toolkit
- However, a custom toolkit gives more control over validation, guards, and WorkingMemory integration
- The MCP endpoint could be used as a fallback or for discovery
