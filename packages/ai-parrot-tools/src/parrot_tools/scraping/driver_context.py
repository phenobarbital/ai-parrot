"""
Driver Context Manager — manages browser driver lifecycle.

Provides a plugin-style ``DriverRegistry`` for registering driver factories
and an async context manager ``driver_context()`` that handles session-based
(persistent) and per-operation (fresh) driver modes.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Dict, Optional

from .toolkit_models import DriverConfig

logger = logging.getLogger(__name__)


class DriverRegistry:
    """Plugin-style registry for browser driver factories.

    Driver factories are callables that accept a ``DriverConfig`` and return
    a setup object with an ``async def get_driver()`` method.

    Usage::

        DriverRegistry.register("selenium", my_selenium_factory)
        factory = DriverRegistry.get("selenium")
    """

    _factories: Dict[str, Callable[[DriverConfig], Any]] = {}

    @classmethod
    def register(cls, driver_type: str, factory: Callable[[DriverConfig], Any]) -> None:
        """Register a driver factory for a given driver type.

        Args:
            driver_type: Identifier for the driver (e.g. ``"selenium"``, ``"playwright"``).
            factory: Callable that accepts a ``DriverConfig`` and returns a
                setup object with ``async def get_driver()``.
        """
        cls._factories[driver_type] = factory
        logger.debug("Registered driver factory: %s", driver_type)

    @classmethod
    def unregister(cls, driver_type: str) -> None:
        """Remove a registered driver factory.

        Args:
            driver_type: Identifier to remove.
        """
        cls._factories.pop(driver_type, None)

    @classmethod
    def get(cls, driver_type: str) -> Callable[[DriverConfig], Any]:
        """Get a registered driver factory.

        Args:
            driver_type: Identifier of the driver factory.

        Returns:
            The registered factory callable.

        Raises:
            ValueError: If the driver type is not registered.
        """
        if driver_type not in cls._factories:
            raise ValueError(
                f"Unknown driver type: {driver_type!r}. "
                f"Registered: {list(cls._factories.keys())}"
            )
        return cls._factories[driver_type]

    @classmethod
    def list_registered(cls) -> list[str]:
        """Return list of registered driver type names.

        Returns:
            List of driver type identifiers.
        """
        return list(cls._factories.keys())


def _create_selenium_setup(config: DriverConfig) -> Any:
    """Create a SeleniumSetup instance from a DriverConfig.

    Args:
        config: Browser configuration.

    Returns:
        A ``SeleniumSetup`` instance ready to call ``get_driver()``.
    """
    from .driver import SeleniumSetup

    return SeleniumSetup(
        browser=config.browser,
        headless=config.headless,
        mobile=config.mobile,
        mobile_device=config.mobile_device,
        auto_install=config.auto_install,
        timeout=config.default_timeout,
        disable_images=config.disable_images,
        custom_user_agent=config.custom_user_agent,
    )


# Register Selenium as the default driver
DriverRegistry.register("selenium", _create_selenium_setup)


async def _quit_driver(driver: Any) -> None:
    """Quit a driver, handling both sync and async quit methods.

    Args:
        driver: Browser driver instance.
    """
    if hasattr(driver, "quit"):
        result = driver.quit()
        # Handle case where quit() is a coroutine
        if hasattr(result, "__await__"):
            await result


@asynccontextmanager
async def driver_context(
    config: DriverConfig,
    session_driver: Optional[Any] = None,
) -> AsyncIterator[Any]:
    """Async context manager that yields a browser driver.

    In session mode (``session_driver`` provided), the existing driver is
    yielded without lifecycle management. In fresh mode, a new driver is
    created from the registry, yielded, and quit on exit.

    Args:
        config: Driver configuration.
        session_driver: Existing driver to reuse (session mode). If ``None``,
            a fresh driver is created and destroyed.

    Yields:
        A browser driver instance.
    """
    if session_driver is not None:
        logger.debug("Using session driver (reuse mode)")
        yield session_driver
    else:
        factory = DriverRegistry.get(config.driver_type)
        setup = factory(config)
        logger.debug("Creating fresh %s driver", config.driver_type)
        driver = await setup.get_driver()
        try:
            yield driver
        finally:
            logger.debug("Quitting fresh %s driver", config.driver_type)
            await _quit_driver(driver)
