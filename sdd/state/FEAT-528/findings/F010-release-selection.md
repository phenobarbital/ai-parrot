---
id: F010
query_id: Q009
type: web_read
intent: Verify the selected Obscura release
executed_at: 2026-09-05T14:30:00Z
depth: 0
parent_id: null
---

# F010 — Obscura v0.2.2 is the latest upstream release

## Summary

The upstream release page lists `v0.2.2` as the latest release and `v0.2.1` immediately before it. The user selected the latest release, so the proposal target is updated to `v0.2.2`; the release adds compatibility and robustness fixes affecting Playwright form filling, context setup, generated CDP clients, script scheduling, binary content, and SSRF handling.

## Citations

- path: `https://github.com/h4ckf0r0day/obscura/releases`
  lines: 139-199 (accessed 2026-09-05)
  symbol: latest release list and v0.2.2 notes
  excerpt: |
    The release list shows v0.2.2 above v0.2.1. v0.2.2 is marked latest and
    describes Playwright form filling/context setup, generated CDP clients,
    event-loop robustness, binary content, and SSRF fixes.

- path: `https://github.com/h4ckf0r0day/obscura/releases/tag/v0.2.1`
  lines: 131-171 (accessed 2026-09-05)
  symbol: v0.2.1 release
  excerpt: |
    v0.2.1 is a valid prior release with iframe, MCP, rendering, CDP, and
    stealth improvements, but is no longer the latest release.
