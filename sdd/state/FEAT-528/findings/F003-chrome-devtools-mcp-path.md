---
id: F003
query_id: Q003
type: read
intent: Locate Chrome DevTools MCP server factory, agent wiring, and managed browser lifecycle
executed_at: 2026-09-05T13:52:00Z
depth: 0
parent_id: null
---

# F003 — Existing Chrome DevTools MCP wiring is endpoint-oriented

## Summary

The agent integration builds a stdio `MCPServerConfig` for `chrome-devtools-mcp@latest`, passing a browser URL and optional launch flags. `WebAgent.configure` supplies that configuration from `ChromeConfig`. The server-side `ChromeManager` separately probes and starts a local Chrome debugging endpoint, which is the component an Obscura process manager could replace if ownership is made explicit.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/integration.py`
  lines: 1105-1121, 1139-1168, 1186-1190
  symbol: `create_chrome_devtools_mcp_server`
  excerpt: |
    def create_chrome_devtools_mcp_server(
        browser_url: str = "http://127.0.0.1:9222", ...
    ) -> MCPServerConfig:
        ...
        if is_local and not auto_connect:
            chrome_manager.start(headless=headless)
        args = ["-y", "chrome-devtools-mcp@latest", f"--browser-url={browser_url}"]

- path: `packages/ai-parrot/src/parrot/bots/chrome.py`
  lines: 290-334
  symbol: `WebAgent.configure`
  excerpt: |
    class WebAgent(BasicAgent):
        """General-purpose web interaction agent via Chrome DevTools MCP."""
        ...
        await self.add_chrome_devtools_mcp_server(
            browser_url=config.browser_url or f"http://127.0.0.1:{config.port}",
            ...
        )

- path: `packages/ai-parrot-server/src/parrot/mcp/chrome.py`
  lines: 8-17, 38-70
  symbol: `ChromeManager`
  excerpt: |
    class ChromeManager:
        """Manages a headless Chrome instance for MCP tools."""
        ...
        def start(self, headless: bool = True) -> bool:
            ...

## Notes

Obscura's own MCP server may be consumed directly as an external server, while its CDP server may preserve the current Chrome DevTools MCP shape. These are separate choices: direct Obscura MCP avoids an adapter but duplicates or bypasses ai-parrot's existing WebAgent factory; CDP preserves the Playwright/Chrome DevTools abstraction.
