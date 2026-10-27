---
type: feature
base_branch: dev
projects: [ai-parrot-tools]
tags: [browsing, scraping, playwright, screencast, mcp]
---

# Feature Specification: browsing-playwright-default-and-screencast

**Feature ID**: FEAT-763
**Date**: 2026-10-27
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

A live test of the `parrot-browsing` MCP server (`WebBrowsingToolkit`) showed
two gaps:

1. The toolkit's browser backend silently defaults to Selenium/Chrome
   (`DriverConfig.driver_type` default `"selenium"`,
   `toolkit_models.py:114`; `WebScrapingToolkit.__init__`'s own
   `driver_type` default `"selenium"`, `toolkit.py:308`) even though the
   project's own `PlaywrightDriver` is the more capable, actively
   maintained backend (FEAT-058, FEAT-681). A user assuming
   "browsing uses Playwright" gets Selenium instead, with no signal that
   the default changed anything — and hit a Selenium-specific
   `element not interactable` failure that would not have reproduced on
   Playwright.
2. There is no way to get a recording of what a catalogued browsing
   session actually did. Only step-level PNG screenshots exist
   (`screenshot` DSL action, FEAT-681). Playwright already supports
   native per-`BrowserContext` video recording
   (`PlaywrightConfig.record_video_dir`,
   `drivers/playwright_config.py`, already wired into
   `PlaywrightDriver._build_context_kwargs()`,
   `drivers/playwright_driver.py:655-656`) — but nothing above the driver
   layer exposes it: `DriverConfig` has no video field, and
   `DriverFactory.create()`'s `"playwright"` branch never forwards one
   into `PlaywrightConfig(...)`.

### Goals
- `WebScrapingToolkit` / `WebBrowsingToolkit` default to the Playwright
  backend when `driver_type` is not specified, everywhere that default is
  read (`DriverConfig`, `WebScrapingToolkit.__init__`,
  `DriverFactory.create()`'s dict fallback).
- An opt-in `record_video` flag on `WebScrapingToolkit`
  (and therefore `WebBrowsingToolkit`, which forwards unknown kwargs to
  it) causes every Playwright session the toolkit opens to record a
  `.webm` video, confined under the toolkit's existing `files_root`
  (`<plans_dir>/files/recordings`, the same confinement root FEAT-681
  already uses for screenshots).
- `WebBrowsingToolkit.close_browser()` reports the finished recording's
  path once the session's browser context has closed (Playwright only
  finalizes the video file after `context.close()`).
- `parrot-browsing`'s local MCP deployment (`.parrot/mcp-toolkits.yaml`)
  turns this capability on by default for this repo.

### Non-Goals (explicitly out of scope)
- No recording support for Selenium or Obscura. Selenium has no native
  video API; Obscura connects to an externally supervised CDP endpoint
  this driver does not own the lifecycle of (`_owns_context=False`,
  `playwright_driver.py:68-75`). No `AbstractDriver`-level
  `start_recording`/`stop_recording` hook is added either — the user
  explicitly chose "Playwright-only, opt-in" over "Playwright now, leave
  a hook for other drivers" when this was scoped.
- No live/streaming screencast (CDP `Page.startScreencast`). This is
  post-hoc video review only, via Playwright's native per-context
  recording — matching how `screenshot` already works (FEAT-681: capture
  now, inspect later).
- No change to the `screenshot` DSL action/step or any other
  `BrowserAction` — FEAT-681 already covers that surface correctly.
- No change to `AbstractDriver`'s abstract interface. `recording_path` is
  a `PlaywrightDriver`-only attribute, read via `getattr(driver,
  "recording_path", None)` by the one caller that needs it
  (`close_browser()`), exactly the same duck-typed pattern already used
  for driver-specific capabilities elsewhere in this toolkit family.
- No retention, rotation, or size cap for `<plans_dir>/files/recordings/`.
  Recordings accumulate indefinitely, same as FEAT-762's own, independently
  reached decision to defer retention for `artifacts/logs/e2e/` — this
  feature documents the disk-growth risk (§7) but does not solve it; a
  separate housekeeping feature or manual cleanup is the follow-up.
- Changing `driver_type` default does not change `browser` (still
  `"chrome"`, mapped to Playwright's `chromium` via
  `DriverFactory._map_browser_to_playwright`) or `headless` defaults.

---

## 2. Architectural Design

### Overview

Two independent, additive changes to the same three files
(`toolkit_models.py`, `scraping/toolkit.py`, `scraping/driver_factory.py`)
plus one driver file and one toolkit file:

1. **Default swap**: three `"selenium"` default-value literals become
   `"playwright"`. No new code paths, no new branches — this changes
   which existing branch in `DriverFactory.create()` runs when a caller
   does not pass `driver_type`.
2. **Screencast plumbing**: a new optional field flows
   `WebScrapingToolkit(record_video=True)` →
   `DriverConfig.record_video_dir` (resolved to a confined path, not a
   raw bool, so `DriverFactory.create()` has nothing to compute) →
   `PlaywrightConfig.record_video_dir` (already consumed by
   `PlaywrightDriver._build_context_kwargs()` — no driver-layer change
   needed there) → Playwright writes a `.webm` on `context.close()` →
   `PlaywrightDriver.quit()` captures `page.video.path()` into a new
   `recording_path` attribute before nulling `self._page` →
   `WebBrowsingToolkit.close_browser()` reads it off the driver before
   dropping the reference and adds it to its result dict.

### Component Diagram
```
WebScrapingToolkit.__init__(record_video=True, plans_dir=...)
        │  (after self._plans_dir is set)
        ▼
DriverConfig.record_video_dir = str(files_root / "recordings")   (toolkit_models.py)
        │
        ▼
DriverFactory.create(config)  ── driver_type == "playwright" branch ──┐
        │                                                             │
        ▼                                                             ▼
PlaywrightConfig(record_video_dir=...)                 driver_type == "obscura" branch:
        │                                               record_video_dir NEVER forwarded
        ▼
PlaywrightDriver.start() → _build_context_kwargs()   (unchanged, FEAT already wired)
        │
        ▼ (session runs: navigate / fill / screenshot / ...)
        ▼
PlaywrightDriver.quit()
    await self._context.close()
    self.recording_path = await self._page.video.path()  (new, only if configured)
        │
        ▼
WebBrowsingToolkit.close_browser()
    driver = self._session_driver        # captured before self.stop() drops it
    await self.stop()                    # → _quit_driver(driver) → driver.quit()
    return {"closed": was_open, "recording_path": getattr(driver, "recording_path", None)}
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `DriverConfig` | extends (1 new field) | `record_video_dir: Optional[str] = None` |
| `WebScrapingToolkit.__init__` | extends (1 new param) | `record_video: bool = False`, resolves into `self._config` after `self._plans_dir` is set |
| `DriverFactory.create()` | modifies | forwards `record_video_dir` only in the `"playwright"` branch; default fallback literal changes |
| `PlaywrightDriver.quit()` | extends | captures `self.recording_path` before releasing `self._page` |
| `WebBrowsingToolkit.close_browser()` | modifies | result dict gains `"recording_path"` |
| `.parrot/mcp-toolkits.yaml` (`browsing:` kwargs) | config | adds `record_video: true` — this repo's local MCP deployment choice |

### Data Models
No new Pydantic/dataclass models. `DriverConfig` (existing `BaseModel`,
`toolkit_models.py:71`) gains one field; `PlaywrightConfig` (existing
`dataclass`, `drivers/playwright_config.py`) is unchanged — it already has
`record_video_dir`.

### New Public Interfaces
```python
# scraping/toolkit.py — WebScrapingToolkit.__init__ gains one parameter
class WebScrapingToolkit(AbstractToolkit):
    def __init__(
        self,
        ...,
        confine_paths: bool = False,
        record_video: bool = False,  # new
        **kwargs: Any,
    ) -> None: ...

# drivers/playwright_driver.py — PlaywrightDriver gains one attribute, no new method
class PlaywrightDriver:
    recording_path: Optional[str]  # set by quit(); None unless record_video_dir was configured
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Default driver → Playwright | yes | Three literal default changes; exact lines fixed in §6 Edit Sites | — |
| M2: Screencast config plumbing | yes | Field name, resolution point, and forwarding branch all fixed in §2/§6 | — |
| M3: Recording capture + MCP exposure | yes | `quit()` change, `close_browser()` return shape, and `.parrot/mcp-toolkits.yaml` key all fixed in §2/§6 | — |

### Module 1: Default driver → Playwright
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/{toolkit_models.py,toolkit.py,driver_factory.py}`
- **Responsibility**: when `driver_type` is not supplied, the toolkit uses Playwright instead of Selenium.
- **Depends on**: nothing (pure default-value change; no new behavior).
- **Interface Skeleton**:
  ```python
  # toolkit_models.py:114  (modifies)
  class DriverConfig(BaseModel):
      driver_type: Literal["selenium", "playwright", "obscura"] = "playwright"  # was "selenium"

  # scraping/toolkit.py:308  (modifies)
  class WebScrapingToolkit(AbstractToolkit):
      def __init__(
          self,
          driver_type: Literal["selenium", "playwright", "obscura"] = "playwright",  # was "selenium"
          ...
      ) -> None: ...

  # scraping/driver_factory.py:94  (modifies)
  class DriverFactory:
      @staticmethod
      def create(config: ...) -> AbstractDriver:
          driver_type: str = config.get("driver_type", "playwright")  # was "selenium"
  ```

### Module 2: Screencast config plumbing
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/{toolkit_models.py,toolkit.py,driver_factory.py}`
- **Responsibility**: let a caller opt a session into Playwright video recording, confined under the toolkit's existing files root.
- **Depends on**: Module 1 is independent of this module (both touch the same files but different lines — see Worktree Strategy for the shared-file serialization this implies).
- **Interface Skeleton**:
  ```python
  # toolkit_models.py (modifies DriverConfig; new field after obscura_allow_private_network, ~toolkit_models.py:134)
  class DriverConfig(BaseModel):
      ...
      record_video_dir: Optional[str] = None
      """Confined directory Playwright should write session `.webm` recordings
      to. Set by ``WebScrapingToolkit`` when ``record_video=True``; never
      None for a hand-built config that wants recording on."""

  # scraping/toolkit.py (modifies WebScrapingToolkit.__init__; new param after confine_paths, toolkit.py:329)
  class WebScrapingToolkit(AbstractToolkit):
      def __init__(
          self,
          ...,
          confine_paths: bool = False,
          record_video: bool = False,
          **kwargs: Any,
      ) -> None:
          """... record_video: opt every Playwright session this toolkit
          opens into native per-context video recording
          (``<plans_dir>/files/recordings/*.webm``). No-op for
          driver_type="selenium"/"obscura" — DriverFactory.create() only
          forwards it in the "playwright" branch."""
          # after self._plans_dir = Path(plans_dir) if plans_dir else Path("scraping_plans")  (toolkit.py:358)
          if record_video:
              self._config = self._config.merge(
                  {"record_video_dir": str(self.files_root / "recordings")}
              )

  # scraping/driver_factory.py (modifies the "playwright" branch only, toolkit.py:108-127)
  class DriverFactory:
      @staticmethod
      def create(config: ...) -> AbstractDriver:
          if driver_type == "playwright":
              pw_config = PlaywrightConfig(
                  ...,  # unchanged existing fields
                  record_video_dir=config.get("record_video_dir"),  # new
              )
          # "obscura" branch: record_video_dir intentionally NEVER forwarded
  ```

### Module 3: Recording capture + MCP exposure
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py`, `packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py`, `.parrot/mcp-toolkits.yaml`
- **Responsibility**: surface the finished recording's path to the MCP caller once a session closes.
- **Depends on**: Module 2 (needs `DriverConfig.record_video_dir` to exist and reach `PlaywrightConfig`).
- **Interface Skeleton**:
  ```python
  # drivers/playwright_driver.py:62-75  (modifies __init__)
  class PlaywrightDriver:
      def __init__(self, config: Optional[PlaywrightConfig] = None) -> None:
          ...
          self._owns_context: bool = False
          self.recording_path: Optional[str] = None  # new

      # drivers/playwright_driver.py:157-182  (modifies quit())
      async def quit(self) -> None:
          """... Captures ``self.recording_path`` from the owned context's
          page video BEFORE releasing ``self._page``, when
          ``config.record_video_dir`` was set. Playwright only finalizes
          the video file after ``context.close()`` — ``page.video.path()``
          is awaited after that call, never before."""
          if self._context and self._owns_context:
              await self._context.close()
              if self.config.record_video_dir and self._page is not None:
                  video = getattr(self._page, "video", None)
                  if video is not None:
                      self.recording_path = str(await video.path())
          self._context = None
          ...  # rest unchanged

  # browsing/toolkit.py:176-188  (modifies close_browser())
  class WebBrowsingToolkit(WebScrapingToolkit):
      async def close_browser(self) -> Dict[str, Any]:
          """... Returns: Dict with ``closed`` (bool) and ``recording_path``
          (str | None — populated only when the session recorded video)."""
          driver = self._session_driver
          was_open = driver is not None
          await self.stop()
          recording_path = getattr(driver, "recording_path", None) if driver is not None else None
          return {"closed": was_open, "recording_path": recording_path}
  ```
  ```yaml
  # .parrot/mcp-toolkits.yaml:104-109  (modifies browsing: kwargs)
  browsing:
    class: parrot_tools.browsing.toolkit.WebBrowsingToolkit
    kwargs:
      catalog_dir: .parrot/browsing_catalog
      headless: false
      record_video: true   # new — this repo's local MCP deployment turns the capability on
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_driver_config_defaults_to_playwright` | M1 | `DriverConfig().driver_type == "playwright"` |
| `test_web_scraping_toolkit_defaults_to_playwright` | M1 | `WebScrapingToolkit()._config.driver_type == "playwright"` with no `driver_type` arg |
| `test_driver_factory_dict_fallback_defaults_to_playwright` | M1 | `DriverFactory.create({})` returns a `PlaywrightDriver` instance |
| `test_driver_factory_create_explicit_selenium_still_works` | M1 | `DriverFactory.create({"driver_type": "selenium"})` still returns `SeleniumDriver` (default change is additive, not a removal) |
| `test_record_video_resolves_confined_dir` | M2 | `WebScrapingToolkit(record_video=True, plans_dir=tmp_path)._config.record_video_dir == str(tmp_path / "files" / "recordings")` |
| `test_record_video_false_leaves_record_video_dir_none` | M2 | default `WebScrapingToolkit()._config.record_video_dir is None` |
| `test_driver_factory_forwards_record_video_dir_playwright` | M2 | `DriverFactory.create({"driver_type": "playwright", "record_video_dir": "/x"})` constructs `PlaywrightConfig(record_video_dir="/x", ...)` (mock/spy `PlaywrightConfig`) |
| `test_driver_factory_obscura_never_forwards_record_video_dir` | M2 | `DriverFactory.create({"driver_type": "obscura", "record_video_dir": "/x"})`'s resulting `PlaywrightConfig.record_video_dir is None` |
| `test_playwright_driver_quit_sets_recording_path` | M3 | mocked `self._context`/`self._page.video.path()`; after `quit()`, `driver.recording_path` equals the mocked path |
| `test_playwright_driver_quit_no_recording_when_not_configured` | M3 | `config.record_video_dir is None` → `quit()` leaves `recording_path is None`, never calls `video.path()` |
| `test_playwright_driver_quit_skips_reused_obscura_context` | M3 | `_owns_context=False` → `quit()` does not touch `self._page.video` at all (reused CDP context) |
| `test_close_browser_reports_recording_path` | M3 | `WebBrowsingToolkit.close_browser()` result includes `"recording_path"` sourced from the (mocked) driver, even after `self._session_driver` has been set to `None` by `stop()` |
| `test_close_browser_no_recording_path_when_not_recording` | M3 | no `record_video` → `close_browser()["recording_path"] is None` |
| `test_close_browser_no_session_open` | M3 | `close_browser()` with no prior session → `{"closed": False, "recording_path": None}` |

### Integration Tests
| Test | Description |
|---|---|
| `test_real_playwright_session_produces_webm_recording` | `WebBrowsingToolkit(driver_type="playwright", record_video=True, plans_dir=tmp_path)`, run one `run_site_action` navigation against a local `file://` fixture page (same pattern as `test_browsing_action_sequence.py`'s hover/type/submit/screenshot tests), then `close_browser()` — assert the returned `recording_path` exists on disk, is a `.webm` file, and sits under `<plans_dir>/files/recordings/` |

### Validation Contract

```
tests:
- packages/ai-parrot-tools/tests/scraping/test_toolkit_models.py
- packages/ai-parrot-tools/tests/scraping/test_toolkit.py
- packages/ai-parrot-tools/tests/scraping/test_driver_factory.py
- packages/ai-parrot-tools/tests/scraping/test_playwright_driver.py
- packages/ai-parrot-tools/tests/scraping/test_browsing_screencast.py
markers: none
```

### Test Data / Fixtures
```python
# New file: packages/ai-parrot-tools/tests/scraping/test_browsing_screencast.py
# Reuses the local file:// fixture page pattern already established in
# test_browsing_action_sequence.py for the one integration test above.
```

---

## 5. Acceptance Criteria

- [ ] `DriverConfig()` (no args) has `driver_type == "playwright"`.
- [ ] `WebScrapingToolkit()` and `WebBrowsingToolkit()` (no `driver_type` arg) open a `PlaywrightDriver`, not `SeleniumDriver`.
- [ ] `driver_type="selenium"` / `"obscura"` still work unchanged (default swap is additive).
- [ ] `WebScrapingToolkit(record_video=True)` resolves `DriverConfig.record_video_dir` to `<files_root>/recordings` and no other driver_type's branch in `DriverFactory.create()` is affected.
- [ ] `DriverFactory.create()` forwards `record_video_dir` to `PlaywrightConfig` only for `driver_type="playwright"`; never for `"obscura"`.
- [ ] After a recorded session's `close_browser()`, the returned `recording_path` points at an existing `.webm` file under `<plans_dir>/files/recordings/`.
- [ ] `close_browser()` without recording configured, or with no session ever opened, returns `recording_path: None` and never raises.
- [ ] `.parrot/mcp-toolkits.yaml`'s `browsing:` kwargs carry `record_video: true`.
- [ ] All tests listed in §4 Validation Contract pass.
- [ ] No breaking changes to `WebScrapingToolkit`/`WebBrowsingToolkit`/`DriverFactory` public signatures (only new optional parameters/fields, no removals, no required-arg additions).

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot_tools.scraping.toolkit_models import DriverConfig  # verified: packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py:71
from parrot_tools.scraping.toolkit import WebScrapingToolkit    # verified: packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py:266
from parrot_tools.scraping.driver_factory import DriverFactory  # verified: packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py:31
from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver  # verified: packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py (class def near top of file)
from parrot_tools.scraping.drivers.playwright_config import PlaywrightConfig  # verified: packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_config.py:11
from parrot_tools.browsing.toolkit import WebBrowsingToolkit     # verified: packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py (class def), close_browser at :176
```

### Existing Class Signatures
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py
class DriverConfig(BaseModel):                                  # line 71
    driver_type: Literal["selenium", "playwright", "obscura"] = "selenium"  # line 114 — TO CHANGE
    obscura_allow_private_network: bool = False                 # line 134 — last field before new one
    def merge(self, overrides: Optional[Dict[str, Any]] = None) -> DriverConfig: ...  # line 136

# packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py
class WebScrapingToolkit(AbstractToolkit):                      # line 266
    def __init__(
        self,
        driver_type: Literal["selenium", "playwright", "obscura"] = "selenium",  # line 308 — TO CHANGE
        ...,
        confine_paths: bool = False,                             # line 329
        **kwargs: Any,
    ) -> None: ...                                               # body builds self._config (DriverConfig) ~lines 312-343,
                                                                   # then self._plans_dir = Path(plans_dir) if plans_dir else Path("scraping_plans")  # line 358
    @property
    def files_root(self) -> Path: ...                            # line 370 — returns self._plans_dir / "files"
    async def start(self) -> None: ...                            # line ~374 — factory = DriverRegistry.get(self._config.driver_type)

# packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py
class DriverFactory:                                              # line 31
    @staticmethod
    def create(config: Optional[Union[Dict[str, Any], Any]] = None) -> AbstractDriver:  # line 44
        driver_type: str = config.get("driver_type", "selenium")  # line 94 — TO CHANGE
        if driver_type == "playwright":                           # line 98
            pw_config = PlaywrightConfig(                          # line 108
                ...,
                executable_path=resolve_browser_binary(            # line 123 (occurs once in this file)
                    config.get("browser_binary") or config.get("executable_path"), browser, channel
                ),
            )                                                      # line 127
            return PlaywrightDriver(pw_config)                     # line 128
        if driver_type == "obscura":                               # line ~131
            pw_config = PlaywrightConfig(                          # line 141 — never gets record_video_dir
                ...,
            )
            return PlaywrightDriver(pw_config)                     # line 163

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py
class PlaywrightDriver:
    def __init__(self, config: Optional[PlaywrightConfig] = None) -> None:  # line 62
        self._context: Any = None                                 # line 67
        self._page: Any = None                                    # line 68
        self._owns_context: bool = False                           # line 75
    async def quit(self) -> None:                                 # line 157
        if self._context and self._owns_context:                  # line 172
            await self._context.close()                            # line 173
        self._context = None                                      # line 174
        ...
        self._page = None                                         # line 182
    def _build_context_kwargs(self) -> Dict[str, Any]:             # line 636
        if self.config.record_video_dir:                           # line 655 — already wired, unchanged
            kwargs["record_video_dir"] = self.config.record_video_dir  # line 656

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_config.py
@dataclass
class PlaywrightConfig:
    record_video_dir: Optional[str] = None   # already exists — no change needed here

# packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py
class WebBrowsingToolkit(WebScrapingToolkit):
    async def close_browser(self) -> Dict[str, Any]:               # line 176
        was_open = self._session_driver is not None                # line 186 — TO CHANGE (capture driver ref first)
        await self.stop()                                          # line 187
        return {"closed": was_open}                                # line 188 — TO CHANGE
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `DriverConfig.record_video_dir` | `PlaywrightConfig.record_video_dir` | `DriverFactory.create()`'s `"playwright"` branch, constructor kwarg | `driver_factory.py:108-127` |
| `WebScrapingToolkit.__init__`'s `record_video` | `DriverConfig.record_video_dir` | `self._config.merge({...})` after `self._plans_dir` is set | `toolkit.py:358` (new code right after) |
| `PlaywrightDriver.quit()` | `page.video.path()` (Playwright API) | `await video.path()` after `await self._context.close()` | `playwright_driver.py:172-182` |
| `WebBrowsingToolkit.close_browser()` | `PlaywrightDriver.recording_path` | `getattr(driver, "recording_path", None)` (duck-typed — Selenium/other drivers simply don't have it) | `browsing/toolkit.py:176-188` |

### Does NOT Exist (Anti-Hallucination)
- ~~`AbstractDriver.start_recording()` / `AbstractDriver.stop_recording()`~~ — explicitly out of scope (Non-Goals); no such hook is added to the abstract base.
- ~~`DriverConfig.record_video` (bool field)~~ — the field is `record_video_dir: Optional[str]`, already resolved to a confined path string by `WebScrapingToolkit.__init__`. The bare `bool` toggle lives only on `WebScrapingToolkit.__init__`'s `record_video` parameter, not on `DriverConfig`.
- ~~`SeleniumDriver.recording_path`~~ — does not exist; `recording_path` is `PlaywrightDriver`-only, accessed via `getattr(..., None)`.
- ~~`PlaywrightConfig.record_video_size` being read anywhere~~ — the dataclass has no such field today (only `record_video_dir` and `record_har_path`); do not invent one.
- ~~A `start_recording()`/`get_recording()` MCP tool~~ — not added. The only new surface is `close_browser()`'s result shape.

### Edit Sites (Blueprint Anchors)

Verified against: `3816b03d6` (origin/dev, 2026-10-27)

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py` | MODIFY | `driver_type: Literal["selenium", "playwright", "obscura"] = "selenium"` | `toolkit_models.py:114` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py` | MODIFY | `obscura_allow_private_network: bool = False` | `toolkit_models.py:134` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py` | MODIFY | `driver_type: Literal["selenium", "playwright", "obscura"] = "selenium",` | `toolkit.py:308` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py` | MODIFY | `confine_paths: bool = False,` | `toolkit.py:329` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py` | MODIFY | `self._plans_dir = Path(plans_dir) if plans_dir else Path("scraping_plans")` | `toolkit.py:358` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py` | MODIFY | `driver_type: str = config.get("driver_type", "selenium")` | `driver_factory.py:94` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py` | MODIFY | `executable_path=resolve_browser_binary(` | `driver_factory.py:123` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py` | MODIFY | `self._owns_context: bool = False` | `playwright_driver.py:75` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py` | MODIFY | `if self._context and self._owns_context:` (within `quit()`) | `playwright_driver.py:172` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py` | MODIFY | `was_open = self._session_driver is not None` | `browsing/toolkit.py:186` | 1 |
| `.parrot/mcp-toolkits.yaml` | MODIFY | `      headless: false` (under `browsing:`) | `.parrot/mcp-toolkits.yaml:108` | 1 |
| `packages/ai-parrot-tools/tests/scraping/test_browsing_screencast.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- `DriverConfig.merge()` (never mutate `self._config` fields in place) — the
  same pattern `WebBrowsingToolkit.__init__` already uses for
  `user_data_dir`/`profile_directory`/`browser_channel`.
- Confine new filesystem writes under `files_root` (`<plans_dir>/files`),
  reusing the exact root FEAT-681's `confined_file`/`confine_to_files_root`
  (`scraping/confine.py`) already established for screenshots — do not
  invent a second "files" convention.
- Keep the new `recording_path` attribute duck-typed on `PlaywrightDriver`
  only; do not touch `AbstractDriver`'s interface (Non-Goals).
- `self.logger` (never `print`) for any new log lines, per repo convention.

### Known Risks / Gotchas
- **Ordering matters in `WebScrapingToolkit.__init__`**: `self._config` is
  built (with `DriverConfig(...)`) *before* `self._plans_dir` is set. The
  `record_video` → `record_video_dir` resolution MUST happen after
  `self._plans_dir` is assigned (via `self._config.merge(...)`), not
  inlined into the original `DriverConfig(...)` call — `files_root` is not
  computable yet at that point.
- **`page.video` can be `None`** even with `record_video_dir` configured,
  if Playwright's video recorder failed to attach (rare, but the Playwright
  docs do not guarantee a non-`None` `page.video`). Guard with
  `getattr(self._page, "video", None) is not None` before awaiting
  `.path()` — never assume it is present.
- **Obscura's reused context** (`_owns_context=False`) never runs the
  `await self._context.close()` branch at all, so `recording_path` simply
  stays `None` for Obscura sessions — this is correct behavior per
  Non-Goals, not a bug to "fix" by adding a separate code path.
- **`DriverFactory.create()`'s two `PlaywrightConfig(...)` call sites**
  (`"playwright"` at line 108, `"obscura"` at line 141) must NOT be
  refactored into one shared call in this feature — the obscura branch's
  `record_video_dir` omission is an explicit Non-Goal, and merging the two
  call sites risks silently reintroducing it.
- Changing a library-wide default (`driver_type`) is observable by every
  consumer of `WebScrapingToolkit`/`WebBrowsingToolkit`, not just
  `parrot-browsing`'s MCP deployment. §4's blast-radius check found only
  one test instantiates either toolkit without an explicit `driver_type`;
  re-run a full grep for `WebScrapingToolkit(` / `WebBrowsingToolkit(`
  call sites across the whole monorepo (not just `ai-parrot-tools`) during
  implementation to catch any other implicit-selenium caller.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `playwright` | `>=1.52` (already required) | Native video recording API (`record_video_dir`, `page.video.path()`) — already a dependency, no version bump needed |

---

## 8. Open Questions

- [x] Should the screencast cover Selenium/Obscura too, or stay
  Playwright-only? — *Resolved by user*: Playwright-only, opt-in. No
  `AbstractDriver` hook for other drivers.
- [x] Should recording be always-on for every Playwright session, or
  opt-in? — *Resolved by user*: opt-in (`record_video: bool = False`
  default).
- [x] Should `record_video_dir`'s recordings ever be pruned/rotated (they
  accumulate under `<plans_dir>/files/recordings/` indefinitely)? —
  *Resolved by user*: out of scope for this feature, matching FEAT-762's
  independently-reached decision to defer the same question for
  `artifacts/logs/e2e/`. Documented as a Non-Goal (§1); a follow-up
  housekeeping feature or manual cleanup handles it later.

No unresolved open questions remain.

---

## Worktree Strategy

- **Isolation**: one feature worktree (`feat-FEAT-763-browsing-playwright-default-and-screencast`); the
  sdd-coder engine gives each task its own sub-worktree.
- **Module dependency graph**: M2 → M1 is not a true dependency (both touch
  `toolkit_models.py`/`toolkit.py`/`driver_factory.py` but different lines) —
  listed as a shared-file serialization below, not an edge. M3 → M2 (needs
  `DriverConfig.record_video_dir` to exist before `PlaywrightDriver.quit()`
  and `close_browser()` have anything meaningful to read).
- **Shared files**: `toolkit_models.py`, `scraping/toolkit.py`,
  `scraping/driver_factory.py` (M1 and M2 both touch these — serialize M1
  before M2 since M2's new field sits right next to M1's default-value
  edits in the same files).
- **Exclusive resources**: none.
- **Cross-feature dependencies**: none.

---

## 9. Design Research Cross-Check

Status: skipped (no accepted exploration document exists for this spec —
it was authored directly from intake notes gathered in conversation with
the user, per `/sdd-spec`'s own guard: the codex design-research seat only
runs over an *accepted* brainstorm/proposal, and none was created for this
feature).
