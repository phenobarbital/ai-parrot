---
id: F005
query_id: Q007
type: web_read
intent: Verify Obscura upstream capabilities and limitations
executed_at: 2026-09-05T13:52:00Z
depth: 0
parent_id: null
---

# F005 — Obscura provides the requested process-level compatibility, with maturity caveats

## Summary

Obscura's upstream README describes a Rust headless browser with V8 JavaScript execution, a Chrome DevTools Protocol server, and Playwright connectivity via `chromium.connectOverCDP` at a WebSocket endpoint. It also documents a built-in MCP server over stdio or HTTP and a Docker image. The same README says the independent rendering engine is evolving and may differ from Chromium for long-tail CSS, some Web APIs, media playback, compositor effects, and font rasterization; it also documents SSRF protection and optional stealth behavior.

## Citations

- path: `https://github.com/h4ckf0r0day/obscura`
  lines: README sections “Obscura”, “Rendering”, “Puppeteer / Playwright”, and “MCP” (accessed 2026-09-05)
  symbol: `obscura serve`, Playwright CDP connection, `obscura mcp`
  excerpt: |
    Obscura implements the Chrome DevTools Protocol and shows:
    chromium.connectOverCDP({ endpointURL: 'ws://127.0.0.1:9222' })
    It documents `obscura mcp` for stdio and `obscura mcp --http --port 8080`.

- path: `https://github.com/h4ckf0r0day/obscura`
  lines: README sections “Install”, “Rendering”, “CDP API”, and “Environment variables” (accessed 2026-09-05)
  symbol: distribution and capability limits
  excerpt: |
    Release archives and Docker are documented; rendering is described as an
    evolving independent engine whose CSS/Web API behavior can differ from
    Chromium. Private-network fetches are blocked by default.

- path: `https://docs.obscura.sh/quickstart/connect-puppeteer-or-playwright`
  lines: not retrieved; upstream documentation endpoint returned an internal crawl error
  symbol: `connect-puppeteer-or-playwright`
  excerpt: |
    The URL was supplied by the request but could not be independently read in
    this research run; the repository README contains the equivalent CDP example.

## Notes

The compatibility claim is strong enough to justify a feasibility proposal for a process-level CDP adapter. It is insufficient to recommend native in-process PyO3 embedding without a source-level audit of Obscura's library crates and build requirements.
