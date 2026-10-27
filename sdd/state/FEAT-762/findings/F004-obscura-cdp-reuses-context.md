---
id: F004
query_id: Q005
type: grep
intent: "get exact line numbers for PlaywrightDriver.start/_start_obscura_cdp/_build_context_kwargs"
executed_at: 2026-10-27T19:10:00Z
duration_ms: 0
parent_id: Q004
depth: 1
---

# F004 — `record_video_dir` only engages in Obscura/CDP mode when the endpoint has zero pre-existing contexts

## Summary

Directly verified against the current source (not just the task doc).
`PlaywrightDriver.start()` branches to `_start_obscura_cdp()` when
`engine == "obscura"` and returns immediately — `_build_context_kwargs()`
(which is where `record_video_dir` is injected) is **not called at all**
in that path unless `_start_obscura_cdp` itself decides to call it.
`_start_obscura_cdp` connects via `connect_over_cdp(endpoint)`, then: if
`self._browser.contexts` is non-empty, it **reuses** `contexts[0]` and sets
`self._owns_context = False` (no `_build_context_kwargs()` call at all,
`record_video_dir` silently ignored); only in the `else` branch (zero
existing contexts) does it call `_build_context_kwargs()` and
`browser.new_context(**context_kwargs)`, which is the only path where
`record_video_dir` is honored in Obscura mode.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py`
  lines: 107-112
  symbol: `PlaywrightDriver.start`
  excerpt: |
    if self.config.engine == "obscura":
        await self._start_obscura_cdp(browser_launcher)
        self.logger.info(...)
        return

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py`
  lines: 586-618
  symbol: `PlaywrightDriver._start_obscura_cdp`
  excerpt: |
    endpoint = self._cdp_endpoint()
    self._browser = await browser_launcher.connect_over_cdp(endpoint)
    if self._browser.contexts:
        self._context = self._browser.contexts[0]
        self._owns_context = False
    else:
        context_kwargs = self._build_context_kwargs()
        context_kwargs.pop("storage_state", None)
        self._context = await self._browser.new_context(**context_kwargs)
        self._owns_context = True

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py`
  lines: 636-663
  symbol: `PlaywrightDriver._build_context_kwargs`
  excerpt: |
    if self.config.record_video_dir:
        kwargs["record_video_dir"] = self.config.record_video_dir
    if self.config.record_har_path:
        kwargs["record_har_path"] = self.config.record_har_path

## Notes

Combined with F001's finding that the `minimal` profile's `browser` target
always spawns a *fresh* `obscura serve` process (zero pre-existing
contexts) per run, the "else" branch above is the one that would actually
execute in the deterministic/owned path — favorable, but this is an
inference from reading two separate modules, not an observed runtime fact.
C3 in the synthesis marks this explicitly as medium confidence pending a
real-binary spike (see F007/U1).

Playwright's video recording is a context-creation-time option that
internally drives the browser's own screencast capture; it works over any
CDP-speaking Chromium-compatible engine in principle, but this repo has
never exercised it against a real Obscura process (see F007) — the
"works over CDP regardless of engine" claim is a Playwright-library-level
property, not yet a verified Obscura-specific fact.
