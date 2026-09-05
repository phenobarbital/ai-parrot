# HOTFIX-chromemanager-async-migration-3: Suite verification, live smoke check, docs & changelog

**Feature**: hotfix `chromemanager-async-migration` (no Jira ticket — user decision 2026-09-05) — ChromeManager async migration (requests → aiohttp) *(hotfix — no `FEAT-<NNN>` reserved, FEAT-466)*
**Spec**: `sdd/specs/chromemanager-async-migration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: HOTFIX-chromemanager-async-migration-2
**Assigned-to**: unassigned

---

## Context

Tasks 1-2 change a process supervisor that unit tests can only mock. This
task closes the spec's acceptance list (§5): run the affected suites, do the
one manual live check against a real Chrome (spec §4 Integration Tests), record
evidence under `artifacts/logs/`, and update the two docs that describe the
Chrome DevTools attach flow plus the changelog.

---

## Scope

- Run and record (to `artifacts/logs/chromemanager-async-migration/`):
  - `pytest tests/mcp/test_chrome_manager.py packages/ai-parrot/tests/bots/test_chrome.py tests/unit/test_mcp_validator.py -v`
  - `pytest tests/mcp tests/unit packages/ai-parrot/tests/bots -q`
  - `ruff check packages/ai-parrot-server/src/parrot/mcp/chrome.py packages/ai-parrot/src/parrot/mcp/integration.py`
  - `grep -rn "import requests" packages/ai-parrot-server/src packages/ai-parrot/src/parrot/mcp` → must be empty.
- Manual live check (only if a Chrome/Chromium binary is available; otherwise record "skipped: no browser" in the log): a short script that instantiates `WebAgent()` with default `ChromeConfig`, awaits `configure()` while a 50 ms ticker task counts loop iterations, asserts `http://127.0.0.1:9222/json/version` answers via aiohttp, then awaits `shutdown()` and confirms the process is gone. Record ticker count and wall time.
- Docs: in `docs/web-agent.md` and `docs/web-navigator-agent.md`, update any sentence saying the factory or `create_chrome_devtools_mcp_server` "starts Chrome" to describe `ensure_running=True` on `add_chrome_devtools_mcp_server()`; mention `ensure_running=False` for externally managed browsers.
- `CHANGELOG.md`: add an entry under the unreleased/next-patch heading: `ChromeManager` is now async (aiohttp + asyncio subprocess); `create_chrome_devtools_mcp_server()` no longer launches Chrome; new `ensure_chrome_running()` and `ensure_running` kwarg; `is_chrome_running()` deprecated in favour of `is_running()`.

**NOT in scope**: code changes to `chrome.py` / `integration.py` beyond what a failing verification forces (if something fails, fix it in the task that owns the file and note the deviation here). No edits to `docs/superpowers/**` (historical design notes).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/logs/chromemanager-async-migration/*.log` | CREATE | pytest / ruff / grep / live-check evidence |
| `docs/web-agent.md` | MODIFY | attach-flow wording, `ensure_running` |
| `docs/web-navigator-agent.md` | MODIFY | same |
| `CHANGELOG.md` | MODIFY | next-patch entry |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.chrome import ChromeConfig, WebAgent          # packages/ai-parrot/src/parrot/bots/chrome.py:15, 290
from parrot.mcp.integration import ensure_chrome_running, _chrome_managers   # after task 2
from parrot.mcp.chrome import ChromeManager                     # server package
import aiohttp
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/chrome.py
class WebAgent(BasicAgent):                      # line 290
    def __init__(self, name="WebAgent", chrome_config: ChromeConfig | None = None, default_timeout_ms=60_000, screenshot_dir=None, **kwargs)  # line 295
    async def configure(self, app=None) -> None  # line 302
# MCPEnabledMixin.shutdown(self, **kwargs)       # integration.py:1842
# Docs that mention the flow (verified by grep 2026-09-05): docs/web-agent.md, docs/web-navigator-agent.md, CHANGELOG.md (repo root)
```

### Does NOT Exist
- ~~`docs/chrome-devtools.md`~~ — no such doc; the two files above are the only user-facing docs that mention the flow.
- ~~`WebAgent.stop_chrome()`~~ — cleanup is only `shutdown()`.
- ~~a CI job with a Chrome binary~~ — none verified; the live check is manual and may be recorded as skipped.

---

## Implementation Notes

### Key Constraints
- Evidence files go under `artifacts/logs/` (project rule), named with the command and a timestamp.
- If the live check is skipped, say so explicitly in the Completion Note; do not describe a run that did not happen.
- Do not claim suites passed without the log file.

---

## Acceptance Criteria

- [ ] All four recorded commands pass and their logs exist under `artifacts/logs/chromemanager-async-migration/`.
- [ ] `tests/unit/test_mcp_validator.py` passes with no modification (`git diff --quiet main -- tests/unit/test_mcp_validator.py`).
- [ ] Live check recorded (result or explicit skip reason).
- [ ] `docs/web-agent.md`, `docs/web-navigator-agent.md` no longer say the factory starts Chrome; `ensure_running` documented.
- [ ] `CHANGELOG.md` entry added.
- [ ] Every spec §5 checkbox can be ticked with a pointer to evidence.

---

## Test Specification

No new automated tests. Verification commands are the scope list above; the
live check script is throwaway (keep it under `artifacts/logs/.../live_check.py`).

---

## Agent Instructions

1. Confirm tasks 1 and 2 are in `sdd/tasks/completed/`.
2. Run the commands, save logs, do or skip the live check honestly.
3. Update docs and changelog; run `pytest` once more after doc edits (no-op but required by the project workflow rule).
4. Update the per-spec index → `done`; move this file to `sdd/tasks/completed/`; fill in the Completion Note with links to the logs.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
