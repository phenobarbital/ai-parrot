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

- path: `https://github.com/h4ckf0r0day/obscura/blob/main/crates/obscura-mcp/src/lib.rs`
  lines: 2572-2696, 2729-2792, 3537-3624 (accessed 2026-09-05)
  symbol: `obscura_mcp::run`, `handle_tools_list`, browser tool dispatch
  excerpt: |
    Obscura exposes newline-delimited JSON MCP over stdin/stdout and registers
    browser_* tools, including navigate, snapshot, click, fill, evaluate,
    screenshots/PDF under render, and browser state operations.

- path: `https://github.com/h4ckf0r0day/obscura/wiki/Use-as-a-Rust-library`
  lines: 187-192 (accessed 2026-09-05)
  symbol: interface selection guidance
  excerpt: |
    The upstream guide recommends the Rust crate for embedding, CDP for
    Node/Python Playwright or Puppeteer, and MCP for AI-agent browser tools.

## Notes

Recommendation for the first milestone: implement Obscura process supervision plus a CDP endpoint configuration, then prove that existing Playwright and Chrome DevTools MCP flows work against it. Add direct Obscura MCP as an optional integration after comparing tool parity and session behavior. This keeps the existing agent/tool contract as the compatibility oracle.
