---
kind: inline
jira_key: null
fetched_at: 2026-10-27T19:07:34Z
summary_oneline: Give the FEAT-581 E2E `browser` target an operational screencast (.webm) alongside its on-anomaly screenshot
---

# Source request (inline, from a conversational exploration of FEAT-581's E2E module)

Topic: add screencast (video) recording as an operational log artifact for
the FEAT-581 E2E `browser` target / `e2e-ui-tester` exploration flow (and,
potentially, a future deterministic UI scenario).

## Prior context established in conversation (to be verified, not assumed)

- `parrot.e2e.targets.browser._BrowserAdapter`
  (`packages/ai-parrot-server/src/parrot/e2e/targets/browser.py`) only
  spawns `obscura serve --host --port --storage-dir` and exposes a raw CDP
  endpoint. It never touches Playwright itself.
- The `e2e-ui-tester` subagent (`.claude/agents/e2e-ui-tester.md`) attaches
  to that CDP endpoint via a generic DevTools/browser-automation MCP tool
  (e.g. `chrome-devtools-mcp`), not via `PlaywrightDriver`. Its only visual
  evidence today is a one-off PNG screenshot captured "on any unexpected
  finding", referenced in `e2e-exploration.json`'s
  `observations[].evidence_refs`.
- The Playwright-backed driver that DOES support video is a separate
  module: `parrot_tools.scraping.drivers.playwright_driver.PlaywrightDriver`
  + `PlaywrightConfig`
  (`packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/`), which
  already has a `record_video_dir` field (TASK-057) and an
  `engine="obscura"` CDP-attach mode (TASK-2876, FEAT-530) connecting via
  `chromium.connect_over_cdp()`.
- Per TASK-2876's completion note, in `engine="obscura"` mode,
  `PlaywrightDriver.start()` reuses the endpoint's existing default
  context/page (`browser.contexts[0]`/`context.pages[0]`) when present,
  and only creates a fresh `new_context(**context_kwargs)` when none
  exists. `record_video_dir` is a context-creation-time Playwright option
  — video recording works via CDP screencast frames regardless of engine,
  but only engages on a freshly created context. Wiring this naively risks
  silently producing no video whenever a context is reused.
- The `browser` e2e target's `minimal` profile (deterministic path) always
  spawns a fresh, isolated `obscura serve` instance per run (unique port +
  private `--storage-dir`), which is the case most likely to have no
  pre-existing context — favorable for this feature, but needs
  verification, not assumption.
- `e2e-exploration.json`'s schema has no `passed`/`status`/
  `gate_satisfied` field (spec §3 M8) and must never be presented as
  deterministic gate evidence — any screencast capability must stay
  confined to the *exploration* report (`evidence_refs`), not the
  `parrot e2e run`/`verify` `E2EVerdict` evidence tree
  (`sdd/state/<FEAT-ID>/e2e/runs/<run-id>/`), unless a separate, explicit
  decision is made to also wire it into a deterministic scenario's
  evidence.

## The ask

Give the `e2e-ui-tester` exploration flow (and/or a future deterministic
UI scenario) the ability to record a Playwright-backed screencast (.webm)
of the browser session against the Obscura CDP endpoint, saved as an
operational log artifact (not gate evidence) alongside the existing
screenshot-on-anomaly behavior. Always-on vs. on-anomaly-only, and
retention/size concerns for `artifacts/logs/e2e/<run-id>/`, are open for
this proposal's research to resolve.
