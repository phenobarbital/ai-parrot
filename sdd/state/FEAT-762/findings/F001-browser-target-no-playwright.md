---
id: F001
query_id: Q002
type: read
intent: "verify browser.py never touches Playwright, only spawns obscura serve"
executed_at: 2026-10-27T19:10:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F001 — The `browser` e2e target only spawns `obscura serve`; it never drives Playwright

## Summary

`_BrowserAdapter` (`parrot.e2e.targets.browser`) is a pure process-launch
adapter: `prepare()` returns a `LaunchSpec` invoking `obscura serve --host
--port --storage-dir [--stealth] [--allow-private-network]` directly
(`shell=False`), or (in `full`/`adopt` mode) a benign sentinel. The module's
own docstring states the CDP endpoint it allocates is "exactly the same
real `http://host:port`" a caller — "Playwright's `chromium.connect_over_
cdp()`, or a human's DevTools tab" — attaches to *separately*. No Playwright
import, context, or page exists anywhere in this file.

## Citations

- path: `packages/ai-parrot-server/src/parrot/e2e/targets/browser.py`
  lines: 58-60
  symbol: module docstring, "DevTools attachment" paragraph
  excerpt: |
    DevTools attachment: once :meth:`ready` reports ``True``, the CDP endpoint a
    caller (e.g. Playwright's ``chromium.connect_over_cdp()``, or a human's
    DevTools tab) attaches to is exactly ``ObscuraProcessManager.endpoint``

- path: `packages/ai-parrot-server/src/parrot/e2e/targets/browser.py`
  lines: 316-323
  symbol: `_BrowserAdapter._prepare_owned`
  excerpt: |
    argv = [
        resolved_binary,
        "serve",
        "--host", host, "--port", str(port),
        "--storage-dir", str(storage_dir),
    ]

- path: `packages/ai-parrot-server/src/parrot/e2e/targets/browser.py`
  lines: 267 (spec row cited inside docstring)
  symbol: spec §2 Target table row for `browser`
  excerpt: |
    `browser` | Own Obscura on unique loopback CDP port/private profile;
    attach DevTools to returned endpoint.

## Notes

The `minimal` profile (deterministic/owned path) always builds a fresh
`storage_dir` and allocates a fresh loopback port per run (`_free_loopback_
port()`), so each run's `obscura serve` process starts with zero
pre-existing browser contexts. This is the condition F004 identifies as
favorable for `record_video_dir` to actually engage once a Playwright
client connects.
