---
type: Wiki Overview
title: 'TASK-1476: AsyncComputerBackend'
id: doc:sdd-tasks-completed-task-1476-async-computer-backend-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §2 AsyncComputerBackend and §3 Module 2. This is the async
  Playwright
relates_to:
- concept: mod:parrot_tools.computer.backend
  rel: mentions
- concept: mod:parrot_tools.computer.models
  rel: mentions
- concept: mod:parrot_tools.scraping.drivers.playwright_config
  rel: mentions
---

# TASK-1476: AsyncComputerBackend

**Feature**: FEAT-227 — Computer-Use Agent
**Spec**: `sdd/specs/computer-use-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1475
**Assigned-to**: unassigned

---

## Context

Implements spec §2 AsyncComputerBackend and §3 Module 2. This is the async Playwright
wrapper that translates coordinate-based computer-use actions into Playwright API calls.
Every action returns an `EnvState` with a screenshot and the current URL.

---

## Scope

- Implement `AsyncComputerBackend` class with browser lifecycle (start/stop)
- Implement all 13 predefined computer-use actions as async methods:
  `click_at`, `hover_at`, `type_text_at`, `scroll_document`, `scroll_at`,
  `wait_seconds`, `go_back`, `go_forward`, `search`, `navigate`,
  `key_combination`, `drag_and_drop`, `open_web_browser`
- Implement `current_state()` — returns current screenshot + URL
- Implement `screenshot(full_page)` — standalone screenshot capture
- Implement coordinate denormalization: `int(coord / 1000 * dimension)`
- Handle browser context creation with configurable viewport, headless mode
- Implement `screen_size()` returning current viewport dimensions

**NOT in scope**: toolkit wrapper, agent logic, loop execution, Google client changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/computer/backend.py` | CREATE | AsyncComputerBackend implementation |
| `packages/ai-parrot-tools/tests/computer/test_backend.py` | CREATE | Backend unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.computer.models import EnvState  # from TASK-1475
from parrot_tools.scraping.drivers.playwright_config import PlaywrightConfig  # verified: playwright_config.py:9

# Playwright async API
from playwright.async_api import async_playwright  # verified: playwright>=1.40.0
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_config.py:9
@dataclass
class PlaywrightConfig:
    browser_type: str = "chromium"    # line 11
    headless: bool = True             # line 12
    slow_mo: int = 0                  # line 13
    timeout: int = 30                 # line 14
    viewport: Optional[Dict[str, int]] = None  # line 15
    record_video_dir: Optional[str] = None     # line 28
```

### Does NOT Exist
- ~~`PlaywrightDriver.click_at(x, y)`~~ — PlaywrightDriver uses `click(selector)`, NOT coordinate-based
- ~~`PlaywrightDriver.type_text_at()`~~ — does not exist; driver has `fill(selector, value)`
- ~~`AbstractDriver.screenshot()` with no args~~ — signature is `screenshot(path, full_page) -> bytes`

---

## Implementation Notes

### Pattern to Follow
```python
# Reference: google-gemini/computer-use-preview/computers/playwright/playwright.py
# BUT adapted for async — use playwright.async_api, not sync_api.
# Use asyncio.sleep() instead of time.sleep()

class AsyncComputerBackend:
    def __init__(self, viewport=(1280, 720), headless=True, browser_type="chromium",
                 initial_url="https://www.google.com", search_engine_url="https://www.google.com"):
        self._viewport = viewport
        self._headless = headless
        ...

    async def start(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        self._context = await self._browser.new_context(
            viewport={"width": self._viewport[0], "height": self._viewport[1]}
        )
        self._page = await self._context.new_page()
        await self._page.goto(self._initial_url)

    async def click_at(self, x: int, y: int) -> EnvState:
        await self._page.mouse.click(x, y)
        await self._page.wait_for_load_state()
        return await self.current_state()
```

### Key Constraints
- All methods MUST be async (no time.sleep — use asyncio.sleep)
- Coordinate params to action methods are ALREADY denormalized (pixel values)
  The denormalization happens in the toolkit layer, not here
- `current_state()` must add a small `asyncio.sleep(0.5)` after `wait_for_load_state`
  (page may not be fully rendered even when Playwright reports loaded)
- Handle new-tab interception: override `context.on("page", ...)` to redirect
  to current page (single-tab model)
- Key combination mapping: translate common key names to Playwright format
  (e.g., "control" → "ControlOrMeta", "enter" → "Enter")

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py` — existing async Playwright usage
- Reference repo `computers/playwright/playwright.py` — action implementations (adapt to async)

---

## Acceptance Criteria

- [ ] `AsyncComputerBackend` starts and stops Playwright browser cleanly
- [ ] All 13 predefined actions implemented and return `EnvState`
- [ ] `screenshot()` returns PNG bytes
- [ ] `screen_size()` returns viewport dimensions
- [ ] New-tab interception redirects to current page
- [ ] Key combination mapping covers common keys (enter, control, shift, etc.)
- [ ] Tests pass: `pytest packages/ai-parrot-tools/tests/computer/test_backend.py -v`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/computer/test_backend.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot_tools.computer.backend import AsyncComputerBackend
from parrot_tools.computer.models import EnvState

@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.screenshot.return_value = b"\x89PNG\r\n\x1a\n"
    page.url = "https://example.com"
    page.viewport_size = {"width": 1280, "height": 720}
    page.wait_for_load_state = AsyncMock()
    page.mouse = AsyncMock()
    page.keyboard = AsyncMock()
    return page

class TestAsyncComputerBackend:
    @pytest.mark.asyncio
    async def test_click_at(self, mock_page):
        backend = AsyncComputerBackend()
        backend._page = mock_page
        result = await backend.click_at(640, 360)
        assert isinstance(result, EnvState)
        mock_page.mouse.click.assert_called_once_with(640, 360)

    @pytest.mark.asyncio
    async def test_type_text_at(self, mock_page):
        backend = AsyncComputerBackend()
        backend._page = mock_page
        result = await backend.type_text_at(100, 200, "hello", press_enter=True)
        assert isinstance(result, EnvState)

    def test_screen_size(self):
        backend = AsyncComputerBackend(viewport=(1920, 1080))
        assert backend.screen_size() == (1920, 1080)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/computer-use-agent.spec.md` for full context
2. **Check dependencies** — verify TASK-1475 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm PlaywrightConfig still at line 9
4. **Implement** the backend with all 13 actions + screenshot + lifecycle
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

Implemented AsyncComputerBackend with all 13 predefined actions plus screenshot, recording (start/stop), tracing, HAR, PDF, and current_state(). Uses playwright.async_api throughout. Key mapping covers 40+ common keys. New-tab interception implemented via context.on("page"). All 29 unit tests pass with mocked Playwright page.
