---
type: Wiki Overview
title: 'TASK-1761: Playwright fetch layer — replace Selenium internals with `driver_context`/`DriverConfig`'
id: doc:sdd-tasks-completed-task-1761-playwright-fetch-layer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'In `packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py`:'
relates_to:
- concept: mod:parrot_tools.scraping.driver_context
  rel: mentions
- concept: mod:parrot_tools.scraping.drivers.abstract
  rel: mentions
- concept: mod:parrot_tools.scraping.toolkit_models
  rel: mentions
---

# TASK-1761: Playwright fetch layer — replace Selenium internals with `driver_context`/`DriverConfig`

**Feature**: FEAT-305 — CompanyResearch — extend CompanyInfoToolkit
**Spec**: `sdd/specs/companyresearch-tool.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1759
**Assigned-to**: unassigned

---

## Context

> Implements spec Module 2 (§3) and the acceptance criterion "Page fetches go
> through `driver_context` with `DriverConfig(driver_type='playwright')`; no
> direct `selenium.webdriver` usage remains in `company_info/tool.py`". Moves
> the toolkit onto the repo's current Playwright scraping stack.

---

## Scope

In `packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py`:

- Replace the internals of `_get_driver`, `_close_driver`, and
  `_fetch_page_with_selenium` with the scraping-stack lifecycle:
  `async with driver_context(DriverConfig(driver_type="playwright", ...)) as drv:
  await drv.navigate(url); html = await drv.get_page_source()` → `BeautifulSoup`.
- Introduce a `_fetch_page(self, url) -> Optional[BeautifulSoup]` method (the new
  canonical fetch entry point) returning `None` on failure. Existing callers of
  `_fetch_page_with_selenium` will be repointed here (final repoint of the 5
  existing `scrape_*` methods happens in TASK-1763 wiring; you may keep a thin
  `_fetch_page_with_selenium` delegating to `_fetch_page` for now, or repoint the
  internal calls — coordinate so no direct Selenium remains).
- **Back-compat**: keep the legacy `__init__` kwargs (`browser`,
  `use_undetected`, `auto_install`, `mobile`, `mobile_device`, `headless`,
  `timeout`) accepted; MAP them onto `DriverConfig` fields. Log a deprecation
  notice for `use_undetected`.
- ZoomInfo path keeps headless-hardening (custom UA) via
  `DriverConfig(custom_user_agent=...)`.
- Remove the direct `selenium.webdriver` import/usage from this module (no
  `webdriver.Chrome` construction remains).

**NOT in scope**: the search layer (TASK-1760); `scrape_visualvisitor`
(TASK-1762); the `research_company` aggregate (TASK-1763). Do NOT change
per-source selector logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py` | MODIFY | Replace Selenium fetch with `driver_context`/`DriverConfig`; map legacy kwargs |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-13 on `dev`.

### Verified Imports
```python
from parrot_tools.scraping.driver_context import driver_context   # driver_context.py:236 (async ctx mgr)
from parrot_tools.scraping.toolkit_models import DriverConfig      # toolkit_models.py:15
from parrot_tools.scraping.drivers.abstract import AbstractDriver  # abstract.py:11
from bs4 import BeautifulSoup                                      # satellite dep beautifulsoup4>=4.12
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py:15
class DriverConfig(BaseModel):
    driver_type: Literal["selenium", "playwright"] = "selenium"   # line 36  -> set "playwright"
    browser: Literal["chrome","firefox","edge","safari","undetected","webkit"] = "chrome"  # line 37
    headless: bool = True                                          # line 40
    # also (docstring 21-33): mobile, mobile_device, auto_install, default_timeout,
    #   retry_attempts, custom_user_agent, disable_images

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py
class AbstractDriver(ABC):                                         # line 11
    async def navigate(self, url: str, timeout: int = 30) -> None  # line 47
    async def get_page_source(self) -> str                        # line 130

# packages/ai-parrot-tools/src/parrot_tools/scraping/driver_context.py:236
# usage pattern (see scraping/toolkit.py:750):
#   async with driver_context(config, session_driver=None) as drv:
#       await drv.navigate(url); html = await drv.get_page_source()

# TO REPLACE — packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py
#   _get_driver               -> line 233  (returns webdriver.Chrome today)
#   _close_driver             -> line 253
#   _fetch_page_with_selenium -> line 334  (returns Optional[bs])
#   __init__                  -> line 175  (legacy kwargs: browser/headless/timeout/
#                                           auto_install/mobile/mobile_device/use_undetected)
```

### Does NOT Exist
- ~~`SeleniumService` (parrot / parrot_tools)~~ — flowtask-only; not in this repo.
- ~~a new Playwright helper class~~ — do NOT create one; use `driver_context` +
  `DriverConfig` (user decision).
- ~~`_PlaywrightSetup` direct import~~ — internal to `driver_context.py:161`;
  never import directly.
- `SeleniumSetup` at `parrot_tools/scraping/driver.py` exists but is the LEGACY
  path — do NOT route new fetches through it.

---

## Implementation Notes

### Pattern to Follow
```python
async def _fetch_page(self, url: str) -> Optional[BeautifulSoup]:
    config = DriverConfig(driver_type="playwright", headless=self._headless, ...)
    try:
        async with driver_context(config) as drv:
            await drv.navigate(url)
            html = await drv.get_page_source()
        return BeautifulSoup(html, "html.parser")
    except Exception as exc:
        self.logger.warning("fetch failed for %s: %s", url, exc)
        return None
```

### Key Constraints
- Async throughout; per-fetch browser lifecycle (context manager per fetch,
  mirroring `scraping/toolkit.py:750`).
- Never raise out of `_fetch_page` — return `None`.
- Preserve back-compat: `CompanyInfoToolkit(browser="chrome", use_undetected=True, ...)`
  must still construct (map onto DriverConfig; deprecation log for `use_undetected`).
- `self.logger`; Google-style docstrings.

---

## Acceptance Criteria

- [ ] Page fetches use `driver_context(DriverConfig(driver_type="playwright", ...))`.
- [ ] No `selenium.webdriver` import or `webdriver.Chrome(...)` remains in `tool.py`.
- [ ] `_fetch_page` returns `Optional[BeautifulSoup]`, returns `None` on failure.
- [ ] Legacy `__init__` kwargs still accepted and mapped onto `DriverConfig`;
      `use_undetected` logs a deprecation notice.
- [ ] `CompanyInfoToolkit()` and `CompanyInfoToolkit(browser="chrome", use_undetected=True)`
      both construct without error.
- [ ] `ruff check ...company_info/tool.py` clean; module imports.

---

## Test Specification

```python
# test_fetch_uses_playwright_config (TASK-1764):
#   monkeypatch driver_context; assert the DriverConfig passed has driver_type == "playwright"
# construction back-compat: CompanyInfoToolkit(browser="chrome", use_undetected=True) does not raise
```

---

## Agent Instructions

1. Read spec §2 (Fetch layer) and §7 back-compat notes.
2. Verify TASK-1759 completed. Re-verify the tool.py line refs before editing.
3. Verify the Codebase Contract; update FIRST if drifted.
4. Implement per scope.
5. Verify acceptance criteria.
6. Move this file to `sdd/tasks/completed/`; update the per-spec index to `done`.
7. Fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Sonnet 5)
**Date**: 2026-07-14
**Notes**: Removed the `try: from selenium import ...` block and the
`from ..scraping.driver import SeleniumSetup` import entirely (they had no
remaining callers once the fetch layer was replaced). Added
`_fetch_page(self, url, custom_user_agent=None)` — the new canonical fetch
entry point using `async with driver_context(driver_config) as drv:
await drv.navigate(...); await drv.get_page_source()` →
`BeautifulSoup`, with `DriverConfig(driver_type="playwright", ...)` built
in `__init__` from the legacy ctor kwargs (browser/headless/timeout→
default_timeout/auto_install/mobile/mobile_device/custom_user_agent).
`use_undetected=True` now only logs a deprecation warning (no Playwright
"undetected" equivalent exists) instead of being applied. Kept
`_fetch_page_with_selenium` as a thin delegate to `_fetch_page` per the
task's explicit option, since its 5 call sites in the existing `scrape_*`
methods are out of scope for this task (repointing belongs to TASK-1763);
its docstring makes clear no Selenium is used despite the name. Removed
`_get_driver` entirely (no callers remained); turned `_close_driver` into
a documented no-op so its 5 existing `finally: await
self._close_driver()` call sites keep working unchanged (there's no
persistent driver anymore — `driver_context` tears down a fresh browser
per fetch). Verified: `CompanyInfoToolkit()` and
`CompanyInfoToolkit(browser="chrome", use_undetected=True)` both
construct; `_fetch_page` smoke-tested with a mocked `driver_context`
(success returns parsed BeautifulSoup, failure returns `None`, and the
`DriverConfig.driver_type == "playwright"` passed to `driver_context` was
asserted). `ruff check` is now fully clean (0 errors — this also resolved
the 6 pre-existing F401 selenium-import errors as a side effect of
removing the now-dead import block). `get_tools()` still exposes all 6
existing tools.
**Deviations from spec**: none — the "keep a thin `_fetch_page_with_selenium`
delegating to `_fetch_page`" option explicitly offered by the task was
chosen over repointing the 5 internal call sites, to avoid scope creep
into TASK-1763's wiring responsibility.
