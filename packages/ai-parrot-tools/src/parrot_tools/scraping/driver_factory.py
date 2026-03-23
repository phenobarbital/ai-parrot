"""Factory for creating browser automation driver instances.

Provides :class:`DriverFactory` as the single entry point for obtaining a
properly configured :class:`AbstractDriver`.  Consumers call
``DriverFactory.create(config)`` instead of instantiating driver classes
directly.

Both ``PlaywrightDriver`` and ``SeleniumDriver`` are imported lazily so the
module works even when only one library is installed.
"""

import logging
from dataclasses import asdict
from typing import Any, Dict, Optional, Union

from parrot.tools.scraping.drivers.abstract import AbstractDriver

logger = logging.getLogger(__name__)

# Browser name → Playwright browser type mapping
_BROWSER_TO_PLAYWRIGHT: Dict[str, str] = {
    "chrome": "chromium",
    "chromium": "chromium",
    "firefox": "firefox",
    "safari": "webkit",
    "webkit": "webkit",
    "edge": "chromium",
}


class DriverFactory:
    """Factory for creating browser automation driver instances.

    Dispatches to the correct driver implementation based on configuration.
    This is the single entry point for obtaining an ``AbstractDriver``.

    Usage::

        driver = DriverFactory.create({"driver_type": "playwright", "browser": "chromium"})
        await driver.start()
    """

    @staticmethod
    def create(
        config: Optional[Union[Dict[str, Any], Any]] = None,
    ) -> AbstractDriver:
        """Create and return an AbstractDriver based on configuration.

        Args:
            config: Driver configuration.  Can be a ``dict``, a Pydantic
                model (with ``model_dump()``), or a dataclass.  If ``None``,
                defaults to ``SeleniumDriver`` with Chrome.

                Key fields:

                - ``driver_type``: ``"selenium"`` or ``"playwright"``
                  (default: ``"selenium"``)
                - ``browser``: Browser name (default: ``"chrome"``)
                - ``headless``: Whether to run headless (default: ``True``)
                - Plus driver-specific options.

        Returns:
            An ``AbstractDriver`` instance (**not yet started** — caller
            must ``await driver.start()``).

        Raises:
            ValueError: If ``driver_type`` is unknown or browser name is
                invalid for Playwright.
        """
        if config is None:
            config = {}

        # Normalize to dict
        if hasattr(config, "model_dump"):
            config = config.model_dump()
        elif hasattr(config, "__dataclass_fields__"):
            config = asdict(config)

        driver_type: str = config.get("driver_type", "selenium")
        browser: str = config.get("browser", "chrome")
        headless: bool = config.get("headless", True)

        if driver_type == "playwright":
            from parrot.tools.scraping.drivers.playwright_config import (
                PlaywrightConfig,
            )
            from parrot.tools.scraping.drivers.playwright_driver import (
                PlaywrightDriver,
            )

            pw_browser = DriverFactory._map_browser_to_playwright(browser)
            pw_config = PlaywrightConfig(
                browser_type=pw_browser,
                headless=headless,
                slow_mo=config.get("slow_mo", 0),
                timeout=config.get("default_timeout", 30),
                viewport=config.get("viewport"),
                locale=config.get("locale"),
                timezone=config.get("timezone"),
                proxy=config.get("proxy"),
                mobile=config.get("mobile", False),
                device_name=config.get("device_name"),
                ignore_https_errors=config.get("ignore_https_errors", False),
                storage_state=config.get("storage_state"),
            )
            logger.info("Creating PlaywrightDriver (browser=%s)", pw_browser)
            return PlaywrightDriver(pw_config)

        if driver_type == "selenium":
            from parrot.tools.scraping.drivers.selenium_driver import (
                SeleniumDriver,
            )

            logger.info("Creating SeleniumDriver (browser=%s)", browser)
            return SeleniumDriver(
                browser=browser,
                headless=headless,
                auto_install=config.get("auto_install", True),
                mobile=config.get("mobile", False),
            )

        raise ValueError(
            f"Unknown driver_type: {driver_type!r}. "
            "Supported values: 'selenium', 'playwright'."
        )

    @staticmethod
    def _map_browser_to_playwright(browser: str) -> str:
        """Map a generic browser name to a Playwright browser type.

        Args:
            browser: Generic browser name (e.g. ``"chrome"``, ``"firefox"``).

        Returns:
            Playwright browser type (``"chromium"``, ``"firefox"``, or
            ``"webkit"``).

        Raises:
            ValueError: If browser name is not recognized.
        """
        browser_lower = browser.lower()
        if browser_lower in _BROWSER_TO_PLAYWRIGHT:
            return _BROWSER_TO_PLAYWRIGHT[browser_lower]
        raise ValueError(
            f"Unknown browser: {browser!r}. "
            f"Supported: {', '.join(sorted(_BROWSER_TO_PLAYWRIGHT.keys()))}"
        )
