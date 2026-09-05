---
id: F007
query_id: Q003/Q007
type: comparison
intent: Compare direct Obscura MCP with reusing Chrome DevTools MCP over Obscura CDP
executed_at: 2026-09-05T14:00:00Z
depth: 1
parent_id: F003
---

# F007 — Direct Obscura MCP and CDP reuse serve different compatibility goals

## Summary

Obscura's MCP server is a self-contained stdio implementation with browser-specific tools such as `browser_navigate`, `browser_snapshot`, `browser_click`, `browser_evaluate`, cookies, screenshots, and PDF support. Reusing the existing Chrome DevTools MCP instead keeps ai-parrot's current `WebAgent` and MCP adapter contract, while pointing its browser URL at Obscura's CDP server. Direct Obscura MCP has fewer moving parts and avoids Node/npx, but its tool names, schemas, session semantics, and output behavior become a second agent-facing contract that ai-parrot would need to support and test.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/integration.py`
  lines: 1105-1192
  symbol: `create_chrome_devtools_mcp_server`
  excerpt: |
    The current integration creates an external stdio MCP configuration with
    command `npx`, the `chrome-devtools-mcp@latest` package, and a browser URL.

- path: `packages/ai-parrot/src/parrot/bots/chrome.py`
  lines: 290-334
  symbol: `WebAgent.configure`
  excerpt: |
    WebAgent delegates browser MCP setup to the existing helper and forwards
    browser URL and configuration fields.

- path: `https://github.com/h4ckf0r0day/obscura/blob/v0.2.2/crates/obscura-mcp/src/lib.rs`
  lines: 223-228, 235-238, 314-720, 742-759 (verified 2026-09-05, revision 2; the file is 2401 lines — the original citation 2572-2696 / 3537-3624 did not exist)
  symbol: `dispatch`, `run`, `handle_tools_list`, tool dispatch
  excerpt: |
    `run` reads newline-delimited JSON-RPC from stdin (235-238); `dispatch`
    routes `tools/list` / `tools/call` (223-228); `handle_tools_list` declares
    37 `browser_*` tools starting at 314 (navigate 318, snapshot 334,
    screenshot 696, pdf 708); tool dispatch at 742-759.

- path: `https://github.com/h4ckf0r0day/obscura/blob/v0.2.2/crates/obscura-cdp/src/server.rs`
  lines: 86, 177, 208, 736-740, 786-800 (verified 2026-09-05, revision 2)
  symbol: HTTP control plane (`/json/version`, `/json/list`, `/json/protocol`)
  excerpt: |
    Default bind host is 127.0.0.1 (86). The accept thread serves /json/*
    endpoints (177, 208, 736-740). `/json/version` reports Chrome/145.0.0.0
    and hardcodes `webSocketDebuggerUrl` to `ws://127.0.0.1:<port>/devtools/browser`
    (791); `/json/list` likewise (800). HTTP discovery therefore only works
    for a local Obscura; remote/containerized deployments must connect by
    explicit ws:// endpoint (`chrome-devtools-mcp --ws-endpoint`,
    Playwright `connect_over_cdp("ws://...")`).

- path: `https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/docs/configuration.md`
  lines: option table (accessed 2026-09-05, revision 2)
  symbol: `--browser-url`, `--ws-endpoint`
  excerpt: |
    `--ws-endpoint`: "WebSocket endpoint to connect to a running Chrome
    instance (e.g., ws://127.0.0.1:9222/devtools/browser/). Alternative to
    --browserUrl." ai-parrot's factory emits only `--browser-url`.

- path: `https://github.com/h4ckf0r0day/obscura/wiki/Use-as-a-Rust-library`
  lines: 187-192 (accessed 2026-09-05)
  symbol: interface selection guidance
  excerpt: |
    The upstream guide recommends the Rust crate for embedding, CDP for
    Node/Python Playwright or Puppeteer, and MCP for AI-agent browser tools.

## Notes

**Revision 2**: `create_chrome_devtools_mcp_server` (integration.py 1158-1166) calls `ChromeManager.start()` for every local URL unless `auto_connect`; with Obscura configured but not running it launches `google-chrome` on the same port. Obscura mode must make process ownership explicit and fail fast.

Recommendation for the first milestone: implement Obscura process supervision plus a CDP endpoint configuration, then prove that existing Playwright and Chrome DevTools MCP flows work against it. Add direct Obscura MCP as an optional integration after comparing tool parity and session behavior. This keeps the existing agent/tool contract as the compatibility oracle.
