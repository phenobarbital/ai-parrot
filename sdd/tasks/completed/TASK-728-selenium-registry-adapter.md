# TASK-728: Selenium registry adapter — return started AbstractDriver

**Feature**: fix-webscrapingtoolkit-executor
**Spec**: `sdd/specs/fix-webscrapingtoolkit-executor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Today the `"selenium"` factory in `DriverRegistry` returns a `SeleniumSetup`
whose `get_driver()` yields a **raw `selenium.webdriver.WebDriver`**. The
`"playwright"` factory (added recently in `_PlaywrightSetup`) yields a started
`PlaywrightDriver` (an `AbstractDriver`). This asymmetry is the root cause of
the executor's Selenium coupling — downstream consumers can't speak to a
unified contract.

This task makes the `"selenium"` factory return a started `SeleniumDriver`
(an `AbstractDriver`) so `driver_context()` ALWAYS yields an `AbstractDriver`,
regardless of `driver_type`.

Implements **Module 4** of the spec.

---

## Scope

- Introduce `_SeleniumSetupAdapter` in `driver_context.py` (mirrors `_PlaywrightSetup`):
  - `__init__(self, config: DriverConfig)` stores config.
  - `async def get_driver(self) -> AbstractDriver` builds a `SeleniumDriver` from `DriverConfig` and `await driver.start()`, returning the started `AbstractDriver`.
- Replace `_create_selenium_setup` so it returns the new adapter (preserve the function name and registration so external code that monkey-patches the factory still works).
- Pass through these `DriverConfig` fields when building `SeleniumDriver`: `browser`, `headless`, `auto_install`, `mobile`, plus `options={"disable_images": ..., "custom_user_agent": ..., "mobile_device": ..., "timeout": default_timeout}` to preserve current behavior.
- Confirm `_quit_driver` still works: it already supports both sync and async `quit()` — `SeleniumDriver.quit()` is async, so coroutine path is taken.

**NOT in scope**:
- Touching `SeleniumSetup` itself (`scraping/driver.py`).
- Touching the executor (TASK-729) or page_snapshot (TASK-730).
- Modifying the Playwright factory (it already returns a started `PlaywrightDriver`).
- Adding new fields to `DriverConfig`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_context.py` | MODIFY | Add `_SeleniumSetupAdapter`; rewrite `_create_selenium_setup` to return it |
| `tests/tools/scraping/test_driver_context.py` | MODIFY | Add `test_selenium_factory_returns_abstract_driver` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.scraping.driver_context import DriverRegistry, _quit_driver, driver_context
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/driver_context.py:19, 111, 125

from parrot_tools.scraping.drivers.abstract import AbstractDriver
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py:11

from parrot_tools.scraping.drivers.selenium_driver import SeleniumDriver
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py:20

from parrot_tools.scraping.toolkit_models import DriverConfig
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py:15
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py:41
class SeleniumDriver(AbstractDriver):
    def __init__(
        self,
        browser: str = "chrome",
        headless: bool = True,
        auto_install: bool = True,
        mobile: bool = False,
        options: Optional[Dict[str, Any]] = None,
    ) -> None: ...

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py:69
async def start(self) -> None:
    """Launch browser via SeleniumSetup and store the WebDriver."""

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py:88
async def quit(self) -> None: ...

# packages/ai-parrot-tools/src/parrot_tools/scraping/driver_context.py:84
def _create_selenium_setup(config: DriverConfig) -> Any:
    # currently returns SeleniumSetup directly — MUST CHANGE

# packages/ai-parrot-tools/src/parrot_tools/scraping/driver_context.py:97 (after recent registry add)
class _PlaywrightSetup:
    def __init__(self, config: DriverConfig) -> None: ...
    async def get_driver(self) -> Any: ...        # mirror this pattern

# packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py:36
class DriverConfig(BaseModel):
    driver_type: Literal["selenium", "playwright"] = "selenium"
    browser: Literal["chrome", "firefox", "edge", "safari", "undetected", "webkit"] = "chrome"
    headless: bool = True
    mobile: bool = False
    mobile_device: Optional[str] = None
    auto_install: bool = True
    default_timeout: int = 10
    disable_images: bool = False
    custom_user_agent: Optional[str] = None
```

### Does NOT Exist
- ~~`SeleniumDriver(driver_type=...)`~~ — `driver_type` is on `DriverConfig`, not the driver
- ~~`SeleniumDriver` accepting `mobile_device` / `disable_images` / `custom_user_agent` as positional kwargs~~ — they go inside the `options` dict and are forwarded to `SeleniumSetup`
- ~~`AbstractDriver.is_started` / `started`~~ — no such attribute; rely on the contract that `start()` was awaited

---

## Implementation Notes

### Pattern to Follow

```python
# In driver_context.py — mirror _PlaywrightSetup

class _SeleniumSetupAdapter:
    """Setup-style wrapper that adapts SeleniumDriver to the registry contract.

    The registry expects ``async def get_driver()`` to return a ready-to-use
    driver. This adapter constructs a SeleniumDriver from DriverConfig and
    starts it so callers receive an AbstractDriver, never a raw WebDriver.
    """

    def __init__(self, config: DriverConfig) -> None:
        self._config = config

    async def get_driver(self) -> Any:
        from .drivers.selenium_driver import SeleniumDriver

        options: Dict[str, Any] = {
            "timeout": self._config.default_timeout,
            "disable_images": self._config.disable_images,
        }
        if self._config.custom_user_agent:
            options["custom_user_agent"] = self._config.custom_user_agent
        if self._config.mobile_device:
            options["mobile_device"] = self._config.mobile_device

        driver = SeleniumDriver(
            browser=self._config.browser,
            headless=self._config.headless,
            auto_install=self._config.auto_install,
            mobile=self._config.mobile,
            options=options,
        )
        await driver.start()
        return driver


def _create_selenium_setup(config: DriverConfig) -> Any:
    return _SeleniumSetupAdapter(config)
```

### Key Constraints

- Keep `_create_selenium_setup` symbol exported (existing tests / external code patches `DriverRegistry.register("selenium", _create_selenium_setup)` via the `_factories` dict).
- Do not change the registration line — the adapter is hidden behind the same factory function.
- `DriverConfig` fields you must NOT silently drop: `disable_images`, `custom_user_agent`, `mobile_device`, `default_timeout`.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_context.py:97-169` — `_PlaywrightSetup` mirror
- `packages/ai-parrot-tools/src/parrot_tools/scraping/driver.py:49-105` — `SeleniumSetup` constructor signature

---

## Acceptance Criteria

- [ ] `await DriverRegistry.get("selenium")(DriverConfig()).get_driver()` returns an `AbstractDriver` instance (NOT a `SeleniumSetup`, NOT a raw `WebDriver`).
- [ ] `await DriverRegistry.get("playwright")(DriverConfig(driver_type="playwright")).get_driver()` continues to return a `PlaywrightDriver` (regression).
- [ ] `_quit_driver(driver)` works for the new `SeleniumDriver` instance (`SeleniumDriver.quit` is async).
- [ ] All existing tests in `tests/tools/scraping/test_driver_context.py` pass — note: tests using `MagicMock` setups via `DriverRegistry.register("selenium", lambda cfg: mock_setup)` MUST keep working because the registry contract (`object with async get_driver()`) is preserved.
- [ ] New test `test_selenium_factory_returns_abstract_driver` verifies the factory output type.

---

## Test Specification

```python
# tests/tools/scraping/test_driver_context.py — add to TestDriverRegistry

class TestSeleniumAdapter:
    @pytest.mark.asyncio
    async def test_selenium_factory_returns_abstract_driver(self):
        from parrot_tools.scraping.drivers.abstract import AbstractDriver
        from parrot_tools.scraping.drivers.selenium_driver import SeleniumDriver
        from parrot_tools.scraping.driver_context import DriverRegistry
        from parrot_tools.scraping.toolkit_models import DriverConfig

        factory = DriverRegistry.get("selenium")
        setup = factory(DriverConfig())
        # Patch SeleniumDriver.start to avoid launching a real browser
        with patch.object(SeleniumDriver, "start", new=AsyncMock()):
            driver = await setup.get_driver()
        assert isinstance(driver, AbstractDriver)
        assert isinstance(driver, SeleniumDriver)

    @pytest.mark.asyncio
    async def test_selenium_adapter_passes_config_fields(self):
        # mock SeleniumDriver constructor and start; assert kwargs include
        # disable_images, custom_user_agent, mobile_device, headless, ...
        ...
```

---

## Agent Instructions

1. Read the spec section "Module 4".
2. No prior task dependencies (technically independent of TASK-727 — they touch different files).
3. Verify signatures, implement, run `tests/tools/scraping/test_driver_context.py`.
4. Move task file to `sdd/tasks/completed/`.

---

## Completion Note

*(Agent fills this in when done)*
