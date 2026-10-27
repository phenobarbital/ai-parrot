---
id: F003
query_id: Q004
type: wiki_page
intent: "find PlaywrightConfig / PlaywrightDriver video-recording fields"
executed_at: 2026-10-27T19:10:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F003 — `PlaywrightConfig` already carries `record_video_dir` and an `engine="obscura"` CDP-attach mode

## Summary

`PlaywrightConfig` (a plain dataclass, `packages/ai-parrot-tools/src/
parrot_tools/scraping/drivers/playwright_config.py`) already has
`record_video_dir: Optional[str] = None` (added TASK-057, FEAT-015) and,
separately, `engine: str = "playwright"` / `cdp_endpoint_url` (added
TASK-2876, FEAT-530) which makes `PlaywrightDriver` connect to a supervised
Obscura process via `chromium.connect_over_cdp()` instead of launching its
own browser. `__post_init__` enforces `engine="obscura"` requires
`browser_type="chromium"` (Obscura speaks CDP as Chromium-compatible only).

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_config.py`
  lines: 95
  symbol: `PlaywrightConfig.record_video_dir`
  excerpt: |
    record_video_dir: Optional[str] = None

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_config.py`
  lines: 101-102
  symbol: `PlaywrightConfig.engine`, `PlaywrightConfig.cdp_endpoint_url`
  excerpt: |
    engine: str = "playwright"
    cdp_endpoint_url: Optional[str] = None

- path: `sdd/tasks/completed/TASK-2876-obscura-playwright-cdp.md`
  lines: n/a (task doc, no line numbers)
  symbol: Completion Note
  excerpt: |
    `PlaywrightDriver.start()` branches on `config.engine == "obscura"`:
    connects via `chromium.connect_over_cdp()`, reuses the endpoint's
    default context/page (`browser.contexts[0]`/`context.pages[0]`) when
    present, else creates a new context/page

## Notes

This task's own completion note is the first-hand source of the
"reuse-vs-create" branching behavior that F004 re-verifies directly against
the current `playwright_driver.py` source (not just the task doc, which
could have drifted).
