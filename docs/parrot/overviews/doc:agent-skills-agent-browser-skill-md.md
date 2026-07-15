---
type: Wiki Overview
title: Browser Automation with agent-browser (async Playwright)
id: doc:agent-skills-agent-browser-skill-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'name: agent-browser'
---

---
name: agent-browser
description: Automate browser interactions (navigation, form filling, screenshots, data extraction, web-app testing) using a persistent async Playwright session. Use when the user needs to navigate websites, interact with web pages, fill forms, take screenshots, test web applications, or extract information from pages. Activate on tasks mentioning "browser automation", "fill a form", "scrape", "screenshot a page", "test the web app", or "click through a site".
compatibility: Requires Playwright (async API) + Chromium. Install with `uv pip install playwright && playwright install chromium`. Session state lives under ~/.agent-browser/<session>/ (override with AGENT_BROWSER_HOME).
triggers: []
metadata:
  author: ai-parrot
  version: "1.0"
  adapted-from: coleam00/ai-coding-summit-workshop-2 (agent-browser, Node CLI)
allowed-tools: Bash(python:*) Bash(uv:*) Read
---

# Browser Automation with agent-browser (async Playwright)

AI-Parrot adaptation of the upstream `agent-browser` Node CLI. Same command
vocabulary and daemon model, but the backend is **Playwright's async API** —
idiomatic to AI-Parrot's async-first architecture. The driver lives at
`scripts/agent_browser.py` (this skill's bundled asset).

> All examples below assume the venv is active (`source .venv/bin/activate`)
> and use the shorthand `SK=.agent/skills/agent-browser/scripts/agent_browser.py`.

## Why a daemon?

Each CLI invocation is a fresh Python process, but the browser must persist
between commands. `daemon start` launches a long-lived Chromium with a
remote-debugging port; every other command connects to it over **CDP**
(`connect_over_cdp`), performs one action, and disconnects — the browser stays
alive. Element refs (`@e1`, `@e2` …) from the last `snapshot` are cached on disk
so they remain valid across invocations.

## Quick start

```bash
SK=.agent/skills/agent-browser/scripts/agent_browser.py
python $SK daemon start            # launch headless Chromium (add --headed to watch)
python $SK open https://example.com
python $SK snapshot -i             # list interactive elements as @e1, @e2 …
python $SK click @e1               # act on a ref from the snapshot
python $SK fill @e2 "text"
python $SK daemon stop             # tear the browser down
```

## Core workflow

1. **Start the daemon once**: `daemon start`
2. **Navigate**: `open <url>`
3. **Snapshot**: `snapshot -i` → interactive elements with refs (`@e1`, `@e2`)
4. **Interact** using those refs
5. **Re-snapshot** after navigation or significant DOM changes (refs are
   regenerated each snapshot)
6. **Stop the daemon** when done: `daemon stop`

## Commands

### Daemon lifecycle
```bash
python $SK daemon start            # headless
python $SK daemon start --headed   # visible window (debugging)
python $SK daemon start --cdp 9222 # fixed CDP port (default: random free port)
python $SK daemon stop
```

### Navigation
```bash
python $SK open <url>              # navigate (waits for domcontentloaded)
```

### Snapshot (page analysis)
```bash
python $SK snapshot                # all visible elements + refs
python $SK snapshot -i             # interactive elements only (recommended)
python $SK snapshot -i --json      # machine-readable [{ref, role, name, tag}]
```

### Interactions (use @refs from snapshot, or a raw CSS selector)
```bash
python $SK click @e1               # click
python $SK fill @e2 "text"         # clear then type
python $SK type @e2 "text"         # type without clearing
python $SK press Enter             # key press (e.g. Enter, Control+a)
python $SK hover @e1               # hover (mouseover) — reveals menus/tooltips
python $SK select @e1 b            # pick <select> option by value
python $SK select @e1 a b          # multi-select: pass several values
python $SK click "button.primary"  # raw CSS selector also accepted
```

### Get information
```bash
python $SK get title               # page title
python $SK get url                 # current URL
python $SK get text @e1            # element inner text
python $SK get html @e1            # innerHTML
python $SK get value @e1           # input value
python $SK get attr @e1 href       # attribute value
python $SK get count ".item"       # count matching elements (CSS selector)
python $SK get text @e1 --json     # JSON-encoded output for parsing
```

### Wait
```bash
python $SK wait 2000                       # wait milliseconds
python $SK wait --text "Success"           # wait for text to appear
python $SK wait --url "**/dashboard"       # wait for URL glob
python $SK wait --load networkidle         # load | domcontentloaded | networkidle
```

### Screenshots
```bash
python $SK screenshot out.png      # viewport screenshot
python $SK screenshot out.png --full   # full-page screenshot
```

### JavaScript
```bash
python $SK eval "document.title"           # run JS, print result
python $SK eval "window.scrollY" --json    # JSON output
```

### Network (intercept & inspect)
```bash
python $SK network route "**/api/**"            # track-only (just log matches)
python $SK network route "*.png" --abort         # block matching requests
python $SK network route "**/cfg.json" --body '{"flag":true}' --status 200  # mock
python $SK network unroute "*.png"                # remove one rule
python $SK network unroute                        # remove all rules
python $SK network requests                       # list tracked requests
python $SK network requests --filter api          # substring filter
```
URL patterns are globs (`*`, `**`). Rules are stored on disk and re-read on
every request, so you can add/remove them between commands. Interception is
applied **per command connection**: a request is logged/routed when the command
that triggers it (e.g. the `goto` in `open`, or an XHR fired by `eval`/`click`)
holds the connection. Set the rule first, then run the command that loads the
traffic.

### Auth / session state
```bash
python $SK state save auth.json    # persist cookies + localStorage
```
Reuse later by passing the same `AGENT_BROWSER_HOME` and re-logging-in, or load
`auth.json` programmatically in your own Playwright script via
`browser.new_context(storage_state="auth.json")`.

### Parallel sessions
```bash
python $SK --session a daemon start
python $SK --session a open https://site-a.com
python $SK --session b daemon start
python $SK --session b open https://site-b.com
```
`--session` goes **before** the subcommand. Each session is an isolated browser
with its own state dir.

## Example: form submission

```bash
SK=.agent/skills/agent-browser/scripts/agent_browser.py
python $SK daemon start
python $SK open https://example.com/login
python $SK snapshot -i
# → @e1 input "Email", @e2 input "Password", @e3 button "Submit"
python $SK fill @e1 "user@example.com"
python $SK fill @e2 "password123"
python $SK click @e3
python $SK wait --load networkidle
python $SK snapshot -i             # inspect the result
python $SK daemon stop
```

## Notes & limitations

- **Refs are per-snapshot.** Any navigation or DOM mutation invalidates them —
  re-run `snapshot -i` before acting again.
- **CSS selectors** are accepted anywhere a `@ref` is, so you can target
  elements `snapshot` didn't surface.
- This is a focused subset of the upstream CLI. For richer needs (frames,
  device emulation, video recording) extend `scripts/agent_browser.py` — it's
  plain async Playwright.
- Embedding in an agent? Import the helpers directly instead of shelling out:
  `from agent_browser import Connection` and drive the page inside your own
  async flow.
- **Tests** live in `tests/` next to this skill. They are not collected by a
  bare `pytest` run (`.agent/` is a dotted dir), so run them explicitly:
  `pytest .agent/skills/agent-browser/tests/ -v`. Integration tests
  auto-skip when Chromium is unavailable.
