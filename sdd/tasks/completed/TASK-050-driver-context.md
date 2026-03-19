# TASK-050: Driver Context Manager

**Feature**: FEAT-014 — WebScrapingToolkit
**Spec**: `sdd/specs/scraping-toolkit.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-049
**Assigned-to**: claude-session

---

## Context

> This task implements Module 2 from the spec: the driver context manager that
> abstracts browser lifecycle (session vs per-operation). It also implements
> plugin-style driver registration as approved in Open Questions §7.

---

## Scope

- Implement `DriverContextManager` — async context manager yielding a browser driver
- Support `session_based=True` (reuse driver) and `session_based=False` (fresh per use)
- Implement `DriverRegistry` for plugin-style driver registration (`register_driver()`)
- Default registration of `SeleniumSetup` as the `"selenium"` driver
- Write unit tests with mock drivers

**NOT in scope**: Step executor (TASK-051), WebScrapingToolkit (TASK-053)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/driver_context.py` | CREATE | DriverContextManager + DriverRegistry |
| `tests/tools/scraping/test_driver_context.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
import logging
from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, Optional, Protocol

from .toolkit_models import DriverConfig


class DriverProtocol(Protocol):
    """Minimal interface a browser driver must satisfy."""
    async def quit(self) -> None: ...


class DriverRegistry:
    """Plugin-style registry for browser driver factories."""
    _factories: Dict[str, Callable] = {}

    @classmethod
    def register(cls, driver_type: str, factory: Callable) -> None:
        cls._factories[driver_type] = factory

    @classmethod
    def get(cls, driver_type: str) -> Callable:
        if driver_type not in cls._factories:
            raise ValueError(f"Unknown driver type: {driver_type!r}. "
                             f"Registered: {list(cls._factories.keys())}")
        return cls._factories[driver_type]


# Default registration
def _create_selenium_driver(config: DriverConfig):
    from .driver import SeleniumSetup
    return SeleniumSetup(
        browser=config.browser,
        headless=config.headless,
        mobile=config.mobile,
        # ... map remaining config fields
    )

DriverRegistry.register("selenium", _create_selenium_driver)


@asynccontextmanager
async def driver_context(config: DriverConfig, session_driver=None):
    """Yield an active driver, managing lifecycle based on session mode."""
    if session_driver is not None:
        yield session_driver
    else:
        factory = DriverRegistry.get(config.driver_type)
        setup = factory(config)
        driver = await setup.get_driver()
        try:
            yield driver
        finally:
            await driver.quit()
```

### Key Constraints
- `DriverRegistry` must be a class-level registry (not instance-level) for global plugin registration
- Session mode: yield existing driver without lifecycle management
- Fresh mode: create driver, yield, then quit in finally block
- Must work with existing `SeleniumSetup.get_driver()` async pattern
- Playwright registration is NOT required — just ensure the registry interface supports it

### References in Codebase
- `parrot/tools/scraping/driver.py` — `SeleniumSetup` class and its constructor params
- `parrot/tools/toolkit.py` — `AbstractToolkit.start()/stop()` lifecycle pattern

---

## Acceptance Criteria

- [ ] `DriverRegistry.register()` and `DriverRegistry.get()` work correctly
- [ ] `DriverRegistry` has `"selenium"` registered by default
- [ ] `DriverRegistry.get()` raises `ValueError` for unknown driver types
- [ ] `driver_context()` in session mode yields the session driver without creating new one
- [ ] `driver_context()` in fresh mode creates driver, yields, and quits on exit
- [ ] All tests pass: `pytest tests/tools/scraping/test_driver_context.py -v`
- [ ] No linting errors: `ruff check parrot/tools/scraping/driver_context.py`
- [ ] Import works: `from parrot.tools.scraping.driver_context import driver_context, DriverRegistry`

---

## Test Specification

```python
# tests/tools/scraping/test_driver_context.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.tools.scraping.driver_context import driver_context, DriverRegistry
from parrot.tools.scraping.toolkit_models import DriverConfig


class TestDriverRegistry:
    def test_selenium_registered_by_default(self):
        assert "selenium" in DriverRegistry._factories

    def test_register_custom_driver(self):
        DriverRegistry.register("test-driver", lambda cfg: MagicMock())
        assert "test-driver" in DriverRegistry._factories
        # Cleanup
        del DriverRegistry._factories["test-driver"]

    def test_get_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown driver type"):
            DriverRegistry.get("nonexistent")


class TestDriverContext:
    @pytest.mark.asyncio
    async def test_session_mode_yields_existing(self):
        mock_driver = MagicMock()
        async with driver_context(DriverConfig(), session_driver=mock_driver) as d:
            assert d is mock_driver

    @pytest.mark.asyncio
    async def test_fresh_mode_creates_and_quits(self):
        mock_driver = AsyncMock()
        mock_setup = MagicMock()
        mock_setup.get_driver = AsyncMock(return_value=mock_driver)

        DriverRegistry.register("test-fresh", lambda cfg: mock_setup)
        try:
            config = DriverConfig(driver_type="test-fresh")
            async with driver_context(config) as d:
                assert d is mock_driver
            mock_driver.quit.assert_awaited_once()
        finally:
            del DriverRegistry._factories["test-fresh"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scraping-toolkit.spec.md` for full context
2. **Check dependencies** — verify TASK-049 is in `sdd/tasks/completed/`
3. **Read** `parrot/tools/scraping/driver.py` to understand `SeleniumSetup` API
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-050-driver-context.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Implemented `DriverRegistry` class with plugin-style factory registration (`register`, `unregister`, `get`, `list_registered`), `_create_selenium_setup` factory, `_quit_driver` helper (handles both sync and async quit), and `driver_context` async context manager with session-mode and fresh-mode. Selenium is registered as the default driver on module import. 16 unit tests pass covering registry CRUD, session/fresh modes, exception safety, and async quit handling.

**Deviations from spec**: none
