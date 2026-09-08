---
id: F006
query_id: Q006
type: git_log
intent: Review recent history for scraping, MCP, and Rust integration paths
executed_at: 2026-09-05T13:52:00Z
depth: 0
parent_id: null
---

# F006 — The relevant seams are active and already tested at integration boundaries

## Summary

Recent history includes the local toolkit MCP work and scraping model/driver changes. Existing tests cover Playwright driver/configuration and scraping integration, while MCP tests cover local toolkit configuration and server behavior. This supports adding contract and capability tests around a new backend, but it does not establish Obscura runtime availability in CI.

## Citations

- path: `packages/ai-parrot-tools/tests/scraping/test_playwright_driver.py`
  lines: 1-1
  symbol: Playwright driver tests
  excerpt: |
    Existing test module for the Playwright driver contract.

- path: `packages/ai-parrot-tools/tests/scraping/test_playwright_config.py`
  lines: 1-1
  symbol: Playwright configuration tests
  excerpt: |
    Existing test module for Playwright configuration behavior.

- path: `tests/mcp/test_toolkit_config.py`
  lines: 18-48, 102-107
  symbol: local MCP toolkit configuration tests
  excerpt: |
    Tests assert built-in scraping and browsing toolkit class paths and
    configuration values.

- path: `tests/handlers/test_scraping_integration.py`
  lines: 190-201
  symbol: driver discovery integration test
  excerpt: |
    The integration test checks that the driver info includes selenium and
    playwright.

## Notes

The proposal should make live Obscura tests optional or fixture-driven until a supported binary/container is available in CI. Exact upstream version pinning and platform matrix remain open.
