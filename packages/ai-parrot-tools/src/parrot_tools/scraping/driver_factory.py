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

from .drivers.abstract import AbstractDriver

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

                - ``driver_type``: ``"selenium"``, ``"playwright"``, or
                  ``"obscura"`` (default: ``"selenium"``). ``"obscura"``
                  returns a ``PlaywrightDriver`` connected over CDP to a
                  supervised Obscura process (see
                  ``parrot.mcp.obscura.ObscuraProcessManager``) — it does
                  not launch a browser itself.
                - ``browser``: Browser name (default: ``"chrome"``).
                  Ignored for ``driver_type="obscura"``, which always
                  connects over Chromium CDP (Obscura speaks CDP as a
                  Chromium-compatible engine).
                - ``headless``: Whether to run headless (default: ``True``)
                - ``cdp_endpoint_url``, ``obscura_binary``,
                  ``obscura_port``, ``obscura_stealth``,
                  ``obscura_allow_private_network``: forwarded to
                  ``PlaywrightConfig`` when ``driver_type="obscura"``.
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
            from .drivers.playwright_config import (
                PlaywrightConfig,
            )
            from .drivers.playwright_driver import (
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
                user_data_dir=config.get("user_data_dir"),
                channel=config.get("browser_channel") or config.get("channel"),
            )
            logger.info("Creating PlaywrightDriver (browser=%s)", pw_browser)
            return PlaywrightDriver(pw_config)

        if driver_type == "obscura":
            from .drivers.playwright_config import (
                PlaywrightConfig,
            )
            from .drivers.playwright_driver import (
                PlaywrightDriver,
            )

            # Obscura is a CDP-speaking, Chromium-compatible engine — it is
            # never selected via the generic `browser` mapping, and it must
            # not silently fall back to launching Chrome/Chromium locally.
            pw_config = PlaywrightConfig(
                browser_type="chromium",
                engine="obscura",
                headless=headless,
                slow_mo=config.get("slow_mo", 0),
                timeout=config.get("default_timeout", 30),
                viewport=config.get("viewport"),
                locale=config.get("locale"),
                timezone=config.get("timezone"),
                proxy=config.get("proxy"),
                ignore_https_errors=config.get("ignore_https_errors", False),
                storage_state=config.get("storage_state"),
                cdp_endpoint_url=config.get("cdp_endpoint_url"),
                obscura_binary=config.get("obscura_binary"),
                obscura_port=config.get("obscura_port", 9222),
                obscura_stealth=config.get("obscura_stealth", False),
                obscura_allow_private_network=config.get(
                    "obscura_allow_private_network", False
                ),
            )
            logger.info(
                "Creating PlaywrightDriver in Obscura CDP mode (endpoint=%s)",
                pw_config.cdp_endpoint_url
                or f"http://127.0.0.1:{pw_config.obscura_port}",
            )
            return PlaywrightDriver(pw_config)

        if driver_type == "selenium":
            from .drivers.selenium_driver import (
                SeleniumDriver,
            )

            selenium_options: Dict[str, Any] = {}
            if config.get("user_data_dir"):
                selenium_options["user_data_dir"] = config["user_data_dir"]
            if config.get("profile_directory"):
                selenium_options["profile_directory"] = config["profile_directory"]
            extra_kwargs: Dict[str, Any] = (
                {"options": selenium_options} if selenium_options else {}
            )

            logger.info("Creating SeleniumDriver (browser=%s)", browser)
            return SeleniumDriver(
                browser=browser,
                headless=headless,
                auto_install=config.get("auto_install", True),
                mobile=config.get("mobile", False),
                **extra_kwargs,
            )

        raise ValueError(
            f"Unknown driver_type: {driver_type!r}. "
            "Supported values: 'selenium', 'playwright', 'obscura'."
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
