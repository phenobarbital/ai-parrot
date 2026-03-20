# TASK-057: PlaywrightConfig Dataclass

**Feature**: FEAT-015 — PlaywrightDriver
**Spec**: `sdd/specs/scraping-playwrightdriver.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

> This task implements Module 2 from the spec: the `PlaywrightConfig` dataclass
> that holds all Playwright-specific browser configuration. This configuration
> object is consumed by `PlaywrightDriver` to build browser contexts and pages.
> It is intentionally a plain `dataclass` (not Pydantic) to keep the drivers
> package dependency-light.

---

## Scope

- Implement `PlaywrightConfig` as a Python `@dataclass` with the following fields:
  - `browser_type: str = "chromium"` — one of `"chromium"`, `"firefox"`, `"webkit"`
  - `headless: bool = True`
  - `slow_mo: int = 0` — milliseconds between actions
  - `timeout: int = 30` — default timeout in seconds
  - `viewport: Optional[Dict[str, int]] = None` — e.g. `{"width": 1280, "height": 720}`
  - `locale: Optional[str] = None`
  - `timezone: Optional[str] = None`
  - `geolocation: Optional[Dict[str, float]] = None`
  - `permissions: List[str] = field(default_factory=list)`
  - `mobile: bool = False`
  - `device_name: Optional[str] = None` — Playwright device descriptor name
  - `proxy: Optional[Dict[str, str]] = None` — e.g. `{"server": "http://proxy:8080"}`
  - `ignore_https_errors: bool = False`
  - `extra_http_headers: Optional[Dict[str, str]] = None`
  - `http_credentials: Optional[Dict[str, str]] = None`
  - `record_video_dir: Optional[str] = None`
  - `record_har_path: Optional[str] = None`
  - `storage_state: Optional[str] = None` — path to saved auth/session state
- Write unit tests for defaults, custom values, and mutable default safety

**NOT in scope**: PlaywrightDriver (TASK-058), AbstractDriver (TASK-056)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/drivers/playwright_config.py` | CREATE | `PlaywrightConfig` dataclass |
| `tests/tools/scraping/test_playwright_config.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

```python
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class PlaywrightConfig:
    """Configuration for PlaywrightDriver.

    Holds all browser, context, and page settings used to launch and
    configure Playwright browser instances.

    Args:
        browser_type: Browser engine — "chromium", "firefox", or "webkit".
        headless: Whether to run the browser in headless mode.
        slow_mo: Milliseconds to wait between each action (useful for debugging).
        timeout: Default timeout in seconds for navigation and waiting.
        viewport: Browser viewport dimensions, e.g. {"width": 1280, "height": 720}.
        locale: Browser locale, e.g. "en-US".
        timezone: Timezone ID, e.g. "America/New_York".
        geolocation: Geolocation coordinates, e.g. {"latitude": 40.7, "longitude": -74.0}.
        permissions: List of browser permissions to grant, e.g. ["geolocation"].
        mobile: Whether to emulate a mobile device.
        device_name: Playwright device descriptor name, e.g. "iPhone 13".
        proxy: Proxy settings, e.g. {"server": "http://proxy:8080"}.
        ignore_https_errors: Whether to ignore HTTPS certificate errors.
        extra_http_headers: Additional HTTP headers for every request.
        http_credentials: HTTP authentication credentials, e.g. {"username": "u", "password": "p"}.
        record_video_dir: Directory path to save screen recordings.
        record_har_path: File path to record HAR network log.
        storage_state: Path to a JSON file with saved cookies/localStorage for session reuse.
    """

    browser_type: str = "chromium"
    headless: bool = True
    slow_mo: int = 0
    timeout: int = 30
    viewport: Optional[Dict[str, int]] = None
    locale: Optional[str] = None
    timezone: Optional[str] = None
    geolocation: Optional[Dict[str, float]] = None
    permissions: List[str] = field(default_factory=list)
    mobile: bool = False
    device_name: Optional[str] = None
    proxy: Optional[Dict[str, str]] = None
    ignore_https_errors: bool = False
    extra_http_headers: Optional[Dict[str, str]] = None
    http_credentials: Optional[Dict[str, str]] = None
    record_video_dir: Optional[str] = None
    record_har_path: Optional[str] = None
    storage_state: Optional[str] = None
```

### Key Constraints

- Use `@dataclass` from the `dataclasses` module — NOT Pydantic
- Use `field(default_factory=list)` for `permissions` (mutable default safety)
- Use `field(default_factory=dict)` or `Optional[Dict]` with `None` for dict fields
- Google-style docstrings with full `Args:` section
- Validate `browser_type` is one of the three allowed values in a `__post_init__`

### References in Codebase

- `sdd/proposals/scrapingplan-playwrightdriver.md` Section 3.1 — config definition

---

## Acceptance Criteria

- [ ] `PlaywrightConfig` is a `@dataclass` with all 18 fields listed in scope
- [ ] Default values match spec (chromium, headless=True, slow_mo=0, timeout=30, etc.)
- [ ] Mutable defaults use `field(default_factory=...)` — no shared state between instances
- [ ] `__post_init__` validates `browser_type` ∈ {"chromium", "firefox", "webkit"}
- [ ] All tests pass: `pytest tests/tools/scraping/test_playwright_config.py -v`
- [ ] No linting errors: `ruff check parrot/tools/scraping/drivers/playwright_config.py`
- [ ] Import works: `from parrot.tools.scraping.drivers.playwright_config import PlaywrightConfig`

---

## Test Specification

```python
# tests/tools/scraping/test_playwright_config.py
import pytest
from parrot.tools.scraping.drivers.playwright_config import PlaywrightConfig


class TestPlaywrightConfigDefaults:
    def test_default_browser_type(self):
        config = PlaywrightConfig()
        assert config.browser_type == "chromium"

    def test_default_headless(self):
        config = PlaywrightConfig()
        assert config.headless is True

    def test_default_timeout(self):
        config = PlaywrightConfig()
        assert config.timeout == 30

    def test_default_slow_mo(self):
        config = PlaywrightConfig()
        assert config.slow_mo == 0

    def test_optional_fields_are_none(self):
        config = PlaywrightConfig()
        assert config.viewport is None
        assert config.locale is None
        assert config.timezone is None
        assert config.geolocation is None
        assert config.device_name is None
        assert config.proxy is None
        assert config.extra_http_headers is None
        assert config.http_credentials is None
        assert config.record_video_dir is None
        assert config.record_har_path is None
        assert config.storage_state is None

    def test_permissions_default_empty_list(self):
        config = PlaywrightConfig()
        assert config.permissions == []


class TestPlaywrightConfigCustomValues:
    def test_custom_browser_type(self):
        config = PlaywrightConfig(browser_type="firefox")
        assert config.browser_type == "firefox"

    def test_custom_viewport(self):
        config = PlaywrightConfig(viewport={"width": 1920, "height": 1080})
        assert config.viewport == {"width": 1920, "height": 1080}

    def test_custom_proxy(self):
        config = PlaywrightConfig(proxy={"server": "http://localhost:8080"})
        assert config.proxy["server"] == "http://localhost:8080"

    def test_mobile_with_device(self):
        config = PlaywrightConfig(mobile=True, device_name="iPhone 13")
        assert config.mobile is True
        assert config.device_name == "iPhone 13"


class TestPlaywrightConfigMutableSafety:
    def test_permissions_not_shared(self):
        c1 = PlaywrightConfig()
        c2 = PlaywrightConfig()
        c1.permissions.append("geolocation")
        assert c2.permissions == []


class TestPlaywrightConfigValidation:
    def test_invalid_browser_type_raises(self):
        with pytest.raises(ValueError):
            PlaywrightConfig(browser_type="opera")

    def test_valid_browser_types(self):
        for bt in ("chromium", "firefox", "webkit"):
            config = PlaywrightConfig(browser_type=bt)
            assert config.browser_type == bt
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scraping-playwrightdriver.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-057-playwright-config.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Created `PlaywrightConfig` dataclass in `parrot/tools/scraping/drivers/playwright_config.py`
with all 18 fields. Added `__post_init__` validation for `browser_type` (must be chromium/firefox/webkit).
Exported from `drivers/__init__.py`. 27 unit tests covering defaults, custom values, mutable safety,
validation, and imports — all passing, lint clean.

**Deviations from spec**: none
