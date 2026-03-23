"""
Enhanced Selenium Setup for WebScrapingTool
Extracted and adapted from SeleniumService class
"""

import asyncio
import logging
import random
from typing import Optional, Dict, Any, Literal, List
from pathlib import Path

# WebDriver Manager for auto-installation
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from webdriver_manager.core.driver_cache import DriverCacheManager

# Selenium imports
try:
    from seleniumwire import webdriver
except ImportError:
    from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.safari.options import Options as SafariOptions
from selenium.webdriver.safari.service import Service as SafariService

# For undetected Chrome
try:
    import undetected_chromedriver as uc
    UNDETECTED_CHROME_AVAILABLE = True
except ImportError:
    UNDETECTED_CHROME_AVAILABLE = False

from .options import (
    USER_AGENTS,
    MOBILE_USER_AGENTS,
    MOBILE_DEVICES,
    CHROME_OPTIONS,
    UNDETECTED_OPTIONS,
    FIREFOX_OPTIONS
)


class SeleniumSetup:
    """
    Selenium Setup Configuration.
    """
    def __init__(
        self,
        browser: Literal['chrome', 'firefox', 'edge', 'safari', 'undetected'] = 'chrome',
        headless: bool = True,
        mobile: bool = False,
        mobile_device: Optional[str] = None,
        browser_binary: Optional[str] = None,
        driver_binary: Optional[str] = None,
        auto_install: bool = True,
        cache_valid_range: int = 7,
        user_data_dir: Optional[str] = None,
        enable_logging: bool = True,
        timeout: int = 10,
        detach: bool = False,
        debugger_address: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize enhanced Selenium setup.

        Args:
            browser: Browser type to use
            headless: Run in headless mode
            mobile: Enable mobile emulation (Chrome only)
            mobile_device: Specific mobile device to emulate
            browser_binary: Path to browser executable
            driver_binary: Path to driver executable
            auto_install: Auto-install driver if not found
            cache_valid_range: Driver cache validity in days
            user_data_dir: Custom user data directory
            enable_logging: Enable detailed logging
        """
        self.browser = browser
        self.headless = headless
        self.mobile = mobile
        self.mobile_device = mobile_device or random.choice(MOBILE_DEVICES)
        self.browser_binary = browser_binary
        self.driver_binary = driver_binary
        self.auto_install = auto_install
        self.cache_valid_range = cache_valid_range
        self.user_data_dir = user_data_dir
        self.enable_logging = enable_logging
        self.timeout = timeout or 10  # Default timeout for waits
        # Additional configuration
        self.disable_http2 = kwargs.get('disable_http2', False)
        self.disable_images = kwargs.get('disable_images', False)
        self.disable_javascript = kwargs.get('disable_javascript', False)
        self.custom_user_agent = kwargs.get('custom_user_agent')
        self.window_size = kwargs.get('window_size', (1920, 1080))
        # Debugging options
        self.detach = detach
        self.debugger_address = debugger_address
        # Setup logging
        self.logger = logging.getLogger(
            f"WebScrapingTool.{self.browser}"
        )
        if not self.enable_logging:
            self.logger.setLevel(logging.WARNING)

    def _get_user_agent(self) -> str:
        """Get appropriate user agent based on mobile/desktop mode"""
        if self.custom_user_agent:
            return self.custom_user_agent

        if self.mobile:
            return random.choice(MOBILE_USER_AGENTS)
        else:
            return random.choice(USER_AGENTS)

    def _setup_chrome_options(self) -> ChromeOptions:
        """Setup Chrome/Chromium options"""
        options = ChromeOptions()

        # Add basic options
        for option in CHROME_OPTIONS:
            options.add_argument(option)

        # Headless mode
        if self.headless:
            options.add_argument("--headless=new")

        # Custom window size
        options.add_argument(f"--window-size={self.window_size[0]},{self.window_size[1]}")

        # User agent
        user_agent = self._get_user_agent()
        options.add_argument(f"--user-agent={user_agent}")

        # enable performance logging
        options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

        # Browser binary
        if self.browser_binary:
            options.binary_location = self.browser_binary

        # User data directory
        if self.user_data_dir:
            options.add_argument(f"--user-data-dir={self.user_data_dir}")

        # Mobile emulation
        if self.mobile:
            mobile_emulation = {
                # "deviceName": self.mobile_device,
                "userAgent": user_agent
            }
            options.add_experimental_option("mobileEmulation", mobile_emulation)
            self.logger.info(f"Mobile emulation enabled: {self.mobile_device}")

        # Performance optimizations
        if self.disable_images:
            prefs = {"profile.managed_default_content_settings.images": 2}
            options.add_experimental_option("prefs", prefs)

        if self.disable_http2:
            options.add_experimental_option("prefs", {"disable-http2": True})

        # Anti-detection measures
        # options.add_experimental_option("excludeSwitches", ["enable-automation"])
        # options.add_experimental_option('useAutomationExtension', False)
        options.page_load_strategy = 'eager'

        # Keep the window open for human interaction after the script ends
        if self.detach:
            options.add_experimental_option("detach", True)

        # Attach to an existing Chrome started with --remote-debugging-port
        if self.debugger_address:
            options.debugger_address = self.debugger_address
            self.logger.info(f"Connecting to debugger at {self.debugger_address}")

        return options

    def _setup_undetected_chrome_options(self) -> 'uc.ChromeOptions':
        """Setup undetected Chrome options"""
        if not UNDETECTED_CHROME_AVAILABLE:
            raise ImportError(
                "undetected-chromedriver not installed. Run: pip install undetected-chromedriver"
            )

        options = uc.ChromeOptions()

        # Add undetected-specific options
        for option in UNDETECTED_OPTIONS:
            options.add_argument(option)

        # User agent
        user_agent = self._get_user_agent()
        options.add_argument(f"--user-agent={user_agent}")

        # Custom window size
        options.add_argument(f"--window-size={self.window_size[0]},{self.window_size[1]}")

        # Browser binary
        if self.browser_binary:
            options.binary_location = self.browser_binary

        return options

    def _setup_firefox_options(self) -> FirefoxOptions:
        """Setup Firefox options"""
        options = FirefoxOptions()

        # Add basic options
        for option in FIREFOX_OPTIONS:
            options.add_argument(option)

        # Headless mode
        if self.headless:
            options.add_argument("--headless")

        # User agent
        user_agent = self._get_user_agent()
        options.set_preference("general.useragent.override", user_agent)

        # Disable HTTP/2 if requested
        if self.disable_http2:
            options.set_preference("network.http.http2.enabled", False)

        # Disable images if requested
        if self.disable_images:
            options.set_preference("permissions.default.image", 2)

        # Disable JavaScript if requested
        if self.disable_javascript:
            options.set_preference("javascript.enabled", False)

        # Browser binary
        if self.browser_binary:
            options.binary_location = self.browser_binary

        try:
            options.set_preference("webdriver.load.strategy", "eager")
        except Exception:
            pass

        return options

    def _setup_edge_options(self) -> EdgeOptions:
        """Setup Edge options"""
        options = EdgeOptions()

        # Add Chrome-like options (Edge is Chromium-based)
        for option in CHROME_OPTIONS:
            options.add_argument(option)

        # Headless mode
        if self.headless:
            options.add_argument("--headless=new")

        # User agent
        user_agent = self._get_user_agent()
        options.add_argument(f"--user-agent={user_agent}")

        # Custom window size
        options.add_argument(f"--window-size={self.window_size[0]},{self.window_size[1]}")

        # Browser binary
        if self.browser_binary:
            options.binary_location = self.browser_binary

        # Mobile emulation (similar to Chrome)
        if self.mobile:
            mobile_emulation = {
                "deviceName": self.mobile_device,
                "userAgent": user_agent
            }
            options.add_experimental_option("mobileEmulation", mobile_emulation)

        # HTTP/2 setting
        options.add_experimental_option("ms:edgeOptions", {"http2": not self.disable_http2})
        options.page_load_strategy = 'eager'
        return options

    def _setup_safari_options(self) -> SafariOptions:
        """Setup Safari options"""
        options = SafariOptions()

        # Safari has limited customization options
        # Mobile mode is not supported via options in Safari
        if self.mobile:
            self.logger.warning("Mobile emulation not supported in Safari WebDriver")

        return options

    def _get_service(self, browser_type: str):
        """Get appropriate WebDriver service with auto-installation"""

        if self.driver_binary:
            # Use custom driver binary
            self.logger.info(f"Using custom {browser_type} driver: {self.driver_binary}")
            if browser_type == 'chrome':
                return ChromeService(executable_path=self.driver_binary)
            elif browser_type == 'firefox':
                return FirefoxService(executable_path=self.driver_binary)
            elif browser_type == 'edge':
                return EdgeService(executable_path=self.driver_binary)
            elif browser_type == 'safari':
                return SafariService(executable_path=self.driver_binary)

        if not self.auto_install:
            # Don't auto-install, use system driver
            if browser_type == 'chrome':
                return ChromeService()
            elif browser_type == 'firefox':
                return FirefoxService()
            elif browser_type == 'edge':
                return EdgeService()
            elif browser_type == 'safari':
                return SafariService()

        # Auto-install driver
        cache_manager = DriverCacheManager(valid_range=self.cache_valid_range)

        if browser_type == 'chrome':
            driver_path = ChromeDriverManager(cache_manager=cache_manager).install()
            return ChromeService(executable_path=driver_path)
        elif browser_type == 'firefox':
            driver_path = GeckoDriverManager(cache_manager=cache_manager).install()
            return FirefoxService(executable_path=driver_path)
        elif browser_type == 'edge':
            driver_path = EdgeChromiumDriverManager(cache_manager=cache_manager).install()
            return EdgeService(executable_path=driver_path)
        elif browser_type == 'safari':
            return SafariService()  # Safari driver is built into macOS

        raise ValueError(f"Unsupported browser type: {browser_type}")

    async def get_driver(self):
        """
        Get configured WebDriver instance.

        Returns:
            WebDriver instance configured according to specifications
        """
        self.logger.info(f"Setting up {self.browser} WebDriver...")

        try:
            if self.browser == 'undetected':
                # Undetected Chrome
                if not UNDETECTED_CHROME_AVAILABLE:
                    raise ImportError(
                        "undetected-chromedriver not available, falling back to regular Chrome"
                    )

                options = self._setup_undetected_chrome_options()

                # Run in executor to avoid blocking
                loop = asyncio.get_event_loop()
                driver = await loop.run_in_executor(
                    None,
                    lambda: uc.Chrome(
                        options=options,
                        headless=self.headless,
                        use_subprocess=False,
                        advanced_elements=True,
                        enable_cdp_events=True
                    )
                )

            elif self.browser == 'chrome':
                # Regular Chrome
                options = self._setup_chrome_options()
                service = self._get_service('chrome')

                loop = asyncio.get_event_loop()
                driver = await loop.run_in_executor(
                    None,
                    lambda: webdriver.Chrome(service=service, options=options)
                )

            elif self.browser == 'firefox':
                # Firefox
                options = self._setup_firefox_options()
                service = self._get_service('firefox')

                loop = asyncio.get_event_loop()
                driver = await loop.run_in_executor(
                    None,
                    lambda: webdriver.Firefox(service=service, options=options)
                )

            elif self.browser == 'edge':
                # Edge
                options = self._setup_edge_options()
                service = self._get_service('edge')

                loop = asyncio.get_event_loop()
                driver = await loop.run_in_executor(
                    None,
                    lambda: webdriver.Edge(service=service, options=options)
                )

            elif self.browser == 'safari':
                # Safari
                options = self._setup_safari_options()
                service = self._get_service('safari')

                loop = asyncio.get_event_loop()
                driver = await loop.run_in_executor(
                    None,
                    lambda: webdriver.Safari(service=service, options=options)
                )

            else:
                raise ValueError(f"Unsupported browser: {self.browser}")

            # Set timeouts
            try:
                self.timeout = max(getattr(self, 'timeout', 10), 10)
            except Exception:
                self.timeout = 10
            driver.implicitly_wait(self.timeout)
            driver.set_page_load_timeout(self.timeout)

            self.logger.info(
                f"{self.browser} WebDriver setup completed successfully"
            )
            return driver

        except Exception as e:
            self.logger.error(
                f"Failed to setup {self.browser} WebDriver: {str(e)}"
            )
            raise
