# TASK-056: AbstractDriver Interface

**Feature**: FEAT-015 — PlaywrightDriver
**Spec**: `sdd/specs/scraping-playwrightdriver.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

> This task implements Module 1 from the spec: the `AbstractDriver` ABC that
> defines the unified interface for browser automation drivers. Both the new
> `PlaywrightDriver` and the refactored `SeleniumDriver` will implement this
> interface. The ABC is the foundation for all subsequent driver tasks in
> FEAT-015.

---

## Scope

- Create the `parrot/tools/scraping/drivers/` package with `__init__.py`
- Implement `AbstractDriver` as an ABC in `abstract.py` with the following
  abstract method groups:
  - **Lifecycle**: `start()`, `quit()`
  - **Navigation**: `navigate(url, timeout)`, `go_back()`, `go_forward()`, `reload()`
  - **DOM interaction**: `click(selector, timeout)`, `fill(selector, value, timeout)`,
    `select_option(selector, value, timeout)`, `hover(selector, timeout)`,
    `press_key(key)`
  - **Content extraction**: `get_page_source()`, `get_text(selector, timeout)`,
    `get_attribute(selector, attribute, timeout)`, `get_all_texts(selector, timeout)`,
    `screenshot(path, full_page)`
  - **Waiting**: `wait_for_selector(selector, timeout, state)`,
    `wait_for_navigation(timeout)`, `wait_for_load_state(state, timeout)`
  - **Media / scripts**: `execute_script(script, *args)`, `evaluate(expression)`
  - **Property**: `current_url` (abstract property)
- Implement **extended capability methods** (non-abstract, raise
  `NotImplementedError` by default):
  - `intercept_requests(handler)`, `record_har(path)`, `save_pdf(path)`,
    `start_tracing(name, screenshots, snapshots)`,
    `stop_tracing(path)`, `mock_route(url_pattern, handler)`
- Export `AbstractDriver` from `drivers/__init__.py`
- Write unit tests verifying ABC behaviour

**NOT in scope**: PlaywrightDriver (TASK-058), SeleniumDriver (TASK-059),
DriverFactory (TASK-060)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/drivers/__init__.py` | CREATE | Package init, exports `AbstractDriver` |
| `parrot/tools/scraping/drivers/abstract.py` | CREATE | `AbstractDriver` ABC definition |
| `tests/tools/scraping/test_abstract_driver.py` | CREATE | Unit tests for the ABC |

---

## Implementation Notes

### Pattern to Follow

```python
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional


class AbstractDriver(ABC):
    """Unified interface for browser automation drivers.

    All driver-specific capabilities are exposed through this interface.
    Methods not supported by a concrete driver raise NotImplementedError
    with a clear message indicating which driver does support the feature.
    """

    # ── Lifecycle ──────────────────────────────────────────────
    @abstractmethod
    async def start(self) -> None:
        """Initialize the browser and create a default page/tab."""

    @abstractmethod
    async def quit(self) -> None:
        """Close the browser and release all resources."""

    # ── Navigation ─────────────────────────────────────────────
    @abstractmethod
    async def navigate(self, url: str, timeout: int = 30) -> None: ...

    @abstractmethod
    async def go_back(self) -> None: ...

    @abstractmethod
    async def go_forward(self) -> None: ...

    @abstractmethod
    async def reload(self) -> None: ...

    # ── DOM Interaction ────────────────────────────────────────
    @abstractmethod
    async def click(self, selector: str, timeout: int = 10) -> None: ...

    @abstractmethod
    async def fill(self, selector: str, value: str, timeout: int = 10) -> None: ...

    @abstractmethod
    async def select_option(self, selector: str, value: str, timeout: int = 10) -> None: ...

    @abstractmethod
    async def hover(self, selector: str, timeout: int = 10) -> None: ...

    @abstractmethod
    async def press_key(self, key: str) -> None: ...

    # ── Content Extraction ─────────────────────────────────────
    @abstractmethod
    async def get_page_source(self) -> str: ...

    @abstractmethod
    async def get_text(self, selector: str, timeout: int = 10) -> str: ...

    @abstractmethod
    async def get_attribute(self, selector: str, attribute: str, timeout: int = 10) -> Optional[str]: ...

    @abstractmethod
    async def get_all_texts(self, selector: str, timeout: int = 10) -> List[str]: ...

    @abstractmethod
    async def screenshot(self, path: str, full_page: bool = False) -> bytes: ...

    # ── Waiting ────────────────────────────────────────────────
    @abstractmethod
    async def wait_for_selector(self, selector: str, timeout: int = 10, state: str = "visible") -> None: ...

    @abstractmethod
    async def wait_for_navigation(self, timeout: int = 30) -> None: ...

    @abstractmethod
    async def wait_for_load_state(self, state: str = "load", timeout: int = 30) -> None: ...

    # ── Media / Scripts ────────────────────────────────────────
    @abstractmethod
    async def execute_script(self, script: str, *args: Any) -> Any: ...

    @abstractmethod
    async def evaluate(self, expression: str) -> Any: ...

    # ── Property ───────────────────────────────────────────────
    @property
    @abstractmethod
    def current_url(self) -> str: ...

    # ── Extended Capabilities (non-abstract) ───────────────────
    async def intercept_requests(self, handler: Callable) -> None:
        """Set up a request interception handler. Playwright-only."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support intercept_requests. "
            "Use PlaywrightDriver for this feature."
        )

    async def record_har(self, path: str) -> None:
        """Start recording a HAR file. Playwright-only."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support record_har. "
            "Use PlaywrightDriver for this feature."
        )

    async def save_pdf(self, path: str) -> bytes:
        """Save the current page as PDF. Playwright (Chromium) only."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support save_pdf. "
            "Use PlaywrightDriver for this feature."
        )

    async def start_tracing(
        self, name: str = "trace", screenshots: bool = True, snapshots: bool = True
    ) -> None:
        """Start Playwright tracing. Playwright-only."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support start_tracing. "
            "Use PlaywrightDriver for this feature."
        )

    async def stop_tracing(self, path: str) -> None:
        """Stop tracing and save to file. Playwright-only."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support stop_tracing. "
            "Use PlaywrightDriver for this feature."
        )

    async def mock_route(self, url_pattern: str, handler: Callable) -> None:
        """Mock network route matching pattern. Playwright-only."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support mock_route. "
            "Use PlaywrightDriver for this feature."
        )
```

### Key Constraints

- Use `abc.ABC` and `abc.abstractmethod` — NOT a protocol class
- All methods must be `async def` (except `current_url` property)
- `current_url` must be an abstract property (`@property @abstractmethod`)
- Extended capability methods are concrete but raise `NotImplementedError`
  with a message naming the class and the feature
- Google-style docstrings on every method

### References in Codebase

- `parrot/clients/abstract_client.py` — existing ABC pattern in the project
- `sdd/proposals/scrapingplan-playwrightdriver.md` Section 2.2 — interface definition

---

## Acceptance Criteria

- [ ] `AbstractDriver` cannot be instantiated directly (TypeError)
- [ ] All abstract methods listed in scope are defined
- [ ] Extended capability methods raise `NotImplementedError` with descriptive message
- [ ] `from parrot.tools.scraping.drivers import AbstractDriver` works
- [ ] `from parrot.tools.scraping.drivers.abstract import AbstractDriver` works
- [ ] All tests pass: `pytest tests/tools/scraping/test_abstract_driver.py -v`
- [ ] No linting errors: `ruff check parrot/tools/scraping/drivers/`

---

## Test Specification

```python
# tests/tools/scraping/test_abstract_driver.py
import pytest
from parrot.tools.scraping.drivers.abstract import AbstractDriver


class TestAbstractDriverCannotInstantiate:
    def test_direct_instantiation_raises(self):
        with pytest.raises(TypeError):
            AbstractDriver()


class ConcreteStub(AbstractDriver):
    """Minimal concrete implementation for testing."""

    async def start(self) -> None: ...
    async def quit(self) -> None: ...
    async def navigate(self, url, timeout=30): ...
    async def go_back(self): ...
    async def go_forward(self): ...
    async def reload(self): ...
    async def click(self, selector, timeout=10): ...
    async def fill(self, selector, value, timeout=10): ...
    async def select_option(self, selector, value, timeout=10): ...
    async def hover(self, selector, timeout=10): ...
    async def press_key(self, key): ...
    async def get_page_source(self): return ""
    async def get_text(self, selector, timeout=10): return ""
    async def get_attribute(self, selector, attribute, timeout=10): return None
    async def get_all_texts(self, selector, timeout=10): return []
    async def screenshot(self, path, full_page=False): return b""
    async def wait_for_selector(self, selector, timeout=10, state="visible"): ...
    async def wait_for_navigation(self, timeout=30): ...
    async def wait_for_load_state(self, state="load", timeout=30): ...
    async def execute_script(self, script, *args): return None
    async def evaluate(self, expression): return None

    @property
    def current_url(self): return "about:blank"


class TestConcreteSubclass:
    def test_can_instantiate(self):
        driver = ConcreteStub()
        assert isinstance(driver, AbstractDriver)

    def test_current_url_property(self):
        driver = ConcreteStub()
        assert driver.current_url == "about:blank"


class TestExtendedCapabilitiesRaiseNotImplemented:
    @pytest.fixture
    def driver(self):
        return ConcreteStub()

    @pytest.mark.asyncio
    async def test_intercept_requests(self, driver):
        with pytest.raises(NotImplementedError):
            await driver.intercept_requests(lambda r: r)

    @pytest.mark.asyncio
    async def test_record_har(self, driver):
        with pytest.raises(NotImplementedError):
            await driver.record_har("/tmp/test.har")

    @pytest.mark.asyncio
    async def test_save_pdf(self, driver):
        with pytest.raises(NotImplementedError):
            await driver.save_pdf("/tmp/test.pdf")

    @pytest.mark.asyncio
    async def test_start_tracing(self, driver):
        with pytest.raises(NotImplementedError):
            await driver.start_tracing()

    @pytest.mark.asyncio
    async def test_stop_tracing(self, driver):
        with pytest.raises(NotImplementedError):
            await driver.stop_tracing("/tmp/trace.zip")

    @pytest.mark.asyncio
    async def test_mock_route(self, driver):
        with pytest.raises(NotImplementedError):
            await driver.mock_route("**/api/*", lambda r: r)


class TestImports:
    def test_import_from_package(self):
        from parrot.tools.scraping.drivers import AbstractDriver
        assert AbstractDriver is not None

    def test_import_from_module(self):
        from parrot.tools.scraping.drivers.abstract import AbstractDriver
        assert AbstractDriver is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scraping-playwrightdriver.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-056-abstract-driver.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Created `parrot/tools/scraping/drivers/` package with `AbstractDriver` ABC in
`abstract.py`. The ABC defines 22 abstract methods grouped by category (lifecycle, navigation,
DOM interaction, content extraction, waiting, media/scripts) plus `current_url` as an abstract
property. Six extended capability methods (intercept_requests, record_har, save_pdf,
start_tracing, stop_tracing, mock_route) are concrete with `NotImplementedError` defaults
that include the class name in the error message. Package `__init__.py` exports `AbstractDriver`.
14 unit tests — all passing, lint clean.

**Deviations from spec**: Minor method signature differences from the original proposal
(e.g. added `timeout` params consistently, `screenshot` returns `bytes`, `go_forward` added
alongside `go_back`, `get_page_source` instead of `get_html` for full-page source). These
align better with both Selenium and Playwright APIs.
