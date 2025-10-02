"""
WebScrapingTool for AI-Parrot
Combines Selenium/Playwright automation with LLM-directed scraping
"""
import sys
from typing import Dict, List, Any, Optional, Union, Literal
from dataclasses import dataclass, field
import select
import time
import asyncio
import logging
import json
from urllib.parse import urlparse, urljoin
from pydantic import BaseModel, Field
from bs4 import BeautifulSoup
# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
# For Playwright alternative
try:
    from playwright.async_api import async_playwright, Page, Browser
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
from ..abstract import AbstractTool
from .driver import SeleniumSetup
from .models import (
    BrowserAction,
    Navigate,
    Click,
    Fill,
    Evaluate,
    PressKey,
    Refresh,
    Back,
    Wait,
    Scroll,
    Authenticate,
    GetCookies,
    SetCookies,
    AwaitHuman,
    AwaitKeyPress,
    AwaitBrowserEvent,
    Loop,
    ScrapingStep,
    ScrapingSelector
)

@dataclass
class ScrapingResult:
    """Stores results from a single page scrape"""
    url: str
    content: str  # Raw HTML content
    bs_soup: BeautifulSoup  # Parsed BeautifulSoup object
    extracted_data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    success: bool = True
    error_message: Optional[str] = None


class WebScrapingToolArgs(BaseModel):
    """Arguments schema for WebScrapingTool."""
    steps: List[Dict[str, Any]] = Field(
        description="List of navigation and interaction steps. Each step should have 'action', 'target', and optional 'value', 'description'"
    )
    selectors: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Content selectors for extraction. Each selector should have 'name', 'selector', and optional 'extract_type', 'multiple'"
    )
    base_url: Optional[str] = Field(
        default="",
        description="Base URL for relative links"
    )
    browser_config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Any Selenium configuration overrides (e.g., headless, mobile, browser type)"
    )


class WebScrapingTool(AbstractTool):
    """
    Advanced web scraping tool with LLM integration support.

    Features:
    - Support for both Selenium and Playwright
    - Step-by-step navigation instructions
    - Flexible content extraction
    - Intermediate result storage
    - Error handling and retry logic
    """

    name = "WebScrapingTool"
    description = """Execute automated web scraping with step-by-step navigation and content extraction.
Supports navigate, click, fill, wait, scroll, set and get cookies, refresh page, back, press keys,
authenticate or waiting for events or human intervention actions."""
    args_schema = WebScrapingToolArgs

    def __init__(
        self,
        browser: Literal['chrome', 'firefox', 'edge', 'safari', 'undetected'] = 'chrome',
        driver_type: Literal['selenium', 'playwright'] = 'selenium',
        headless: bool = True,
        mobile: bool = False,
        mobile_device: Optional[str] = None,
        browser_binary: Optional[str] = None,
        driver_binary: Optional[str] = None,
        auto_install: bool = True,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.driver_type = driver_type
        # Browser configuration
        self.browser_config = {
            'browser': browser,
            'headless': headless,
            'mobile': mobile,
            'mobile_device': mobile_device,
            'browser_binary': browser_binary,
            'driver_binary': driver_binary,
            'auto_install': auto_install,
            **kwargs
        }
        self.driver = None
        self.browser = None  # For Playwright
        self.page = None     # For Playwright
        self.results: List[ScrapingResult] = []
        # Allow turning overlay housekeeping on/off (default ON)
        self.overlay_housekeeping: bool = kwargs.get('overlay_housekeeping', True)
        # Configuration
        self.default_timeout = kwargs.get('default_timeout', 10)
        self.retry_attempts = kwargs.get('retry_attempts', 3)
        self.delay_between_actions = kwargs.get('delay_between_actions', 1)
        logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)

    async def _execute(
        self,
        steps: List[Dict[str, Any]],
        selectors: Optional[List[Dict[str, Any]]] = None,
        base_url: str = "",
        browser_config: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute the web scraping workflow.

        Args:
            steps: List of navigation/interaction steps
            selectors: List of content selectors to extract
            base_url: Base URL for relative links

        Returns:
            Dictionary with scraping results
        """
        self.results = []

        try:
            await self.initialize_driver(config_overrides=browser_config)

            # Convert dictionaries to dataclasses
            scraping_steps = [ScrapingStep(**step) for step in steps]
            scraping_selectors = [ScrapingSelector(**sel) for sel in selectors] if selectors else None

            # Execute scraping workflow
            results = await self.execute_scraping_workflow(
                scraping_steps,
                scraping_selectors,
                base_url
            )

            return {
                "status": len([r for r in results if r.success]) > 0,
                "result": [
                    {
                        "url": r.url,
                        "extracted_data": r.extracted_data,
                        "metadata": r.metadata,
                        "success": r.success,
                        "error_message": r.error_message
                    } for r in results
                ],
                "metadata": {
                    "total_pages_scraped": len(results),
                    "successful_scrapes": len([r for r in results if r.success]),
                    "browser_used": self.selenium_setup.browser,
                    "mobile_mode": self.selenium_setup.mobile,
                }
            }

        except Exception as e:
            self.logger.error(f"Scraping execution failed: {str(e)}")
            return {
                "status": False,
                "error": str(e),
                "result": [],
                "metadata": {
                    "browser_used": self.browser_config.get('browser', 'unknown'),
                }
            }

    async def initialize_driver(self, config_overrides: Optional[Dict[str, Any]] = None):
        """Initialize the web driver based on configuration"""
        if self.driver_type == 'selenium':
            await self._setup_selenium(config_overrides)
        elif self.driver_type == 'playwright' and PLAYWRIGHT_AVAILABLE:
            await self._setup_playwright()
        else:
            raise ValueError(
                f"Driver type '{self.driver_type}' not supported or not available"
            )

    async def _get_selenium_driver(self, config: Dict[str, Any]) -> webdriver.Chrome:
        # Create Selenium setup
        self.selenium_setup = SeleniumSetup(**config)
        # Get the driver
        return await self.selenium_setup.get_driver()

    async def _setup_selenium(self, config_overrides: Optional[Dict[str, Any]] = None):
        """Setup Selenium WebDriver"""
        final_config = self.browser_config.copy()
        if config_overrides:
            final_config.update(config_overrides)
        self.driver = await self._get_selenium_driver(final_config)
        return self.driver

    async def _setup_playwright(self):
        """Setup Playwright browser"""
        if not PLAYWRIGHT_AVAILABLE:
            raise ImportError("Playwright is not installed. Install with: pip install playwright")

        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(
            headless=self.browser_config.get('headless', True)
        )
        self.page = await self.browser.new_page()
        await self.page.set_viewport_size({"width": 1920, "height": 1080})

    async def execute_scraping_workflow(
        self,
        steps: List[ScrapingStep],
        selectors: Optional[List[ScrapingSelector]] = None,
        base_url: str = ""
    ) -> List[ScrapingResult]:
        """
        Execute a complete scraping workflow

        Args:
            steps: List of navigation/interaction steps
            selectors: List of content selectors to extract
            base_url: Base URL for relative links

        Returns:
            List of ScrapingResult objects
        """
        self.results = []

        try:
            # Execute each step in sequence
            for i, step in enumerate(steps):
                self.logger.info(f"Executing step {i+1}/{len(steps)}: {step.description}")
                print(' DEBUG STEP > ', step, base_url)
                success = await self._execute_step(step, base_url)

                if not success and step.action in ['navigate', 'authenticate']:
                    # Critical steps - abort if they fail
                    self.logger.error(
                        f"Critical step failed: {step.description}"
                    )
                    break

                # Add delay between actions
                await asyncio.sleep(self.delay_between_actions)

            # Extract content using selectors
            if selectors:
                current_url = await self._get_current_url()
                result = await self._extract_content(current_url, selectors)
                if result:
                    self.results.append(result)
            else:
                # Default: extract full page content
                current_url = await self._get_current_url()
                result = await self._extract_full_content(current_url)
                if result:
                    self.results.append(result)

        except Exception as e:
            self.logger.error(f"Scraping workflow failed: {str(e)}")
            # Create error result
            error_result = ScrapingResult(
                url="",
                content="",
                bs_soup=BeautifulSoup("", 'html.parser'),
                success=False,
                error_message=str(e)
            )
            self.results.append(error_result)

        finally:
            await self.cleanup()

        return self.results

    async def _execute_step(self, step: ScrapingStep, base_url: str = "") -> bool:
        """Execute a single scraping step with a hard timeout per step."""
        action = step.action
        action_type = step.get_action_type()
        result = None
        try:
            if action_type == 'navigate':
                result = await self._navigate_to(action, base_url)
            elif action_type == 'click':
                result = await self._click(
                    action,
                    timeout=action.timeout or self.default_timeout
                )
            elif action_type == 'fill':
                result = await self._fill(action)
            elif action_type == 'evaluate':
                result = await self._evaluate_js(action)
            elif action_type == 'await_human':
                result = await self._await_human(action)
            elif action_type == 'press_key':
                result = await self._press_key(action)
            elif action_type == 'refresh':
                result = await self._handle_refresh(action)
            elif action_type == 'back':
                result = await self._handle_back(action)
            elif action_type == 'get_cookies':
                result = await self._get_cookies(action)
            elif action_type == 'set_cookies':
                result = await self._set_cookies(action)
            elif action_type == 'await_keypress':
                result = await self._await_keypress(action)
            elif action_type == 'await_browser_event':
                result = await self._await_browser_event(action)
            elif action_type == 'wait':
                result = await self._wait_for_condition(
                    action,
                    step.timeout or self.default_timeout
                )
            elif action_type == 'scroll':
                result = await self._scroll_page(action)
            elif action_type == 'authenticate':
                result = await self._handle_authentication(action)
            else:
                self.logger.warning(f"Unknown action: {step.action}")
                return False
            return result
        except asyncio.TimeoutError:
            self.logger.error(f"Step timed out: {step.description or step.action}")
            return False
        except Exception as e:
            self.logger.error(f"Step execution failed: {step.action} - {str(e)}")
            return False

    async def _evaluate_js(self, action: Evaluate) -> Any:
        """Handle Evaluate action"""
        script = action.script

        # Load script from file if specified
        if action.script_file:
            with open(action.script_file, 'r') as f:
                script = f.read()

        if not script:
            self.logger.warning(
                "No script provided for Evaluate action"
            )
            return False

        if self.driver_type == 'selenium':
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.driver.execute_script(script, *action.args)
            )
        else:  # Playwright
            result = await self.page.evaluate(script, *action.args)

        return result if action.return_value else True

    async def _press_key(self, action: PressKey) -> bool:
        """Handle PressKey action"""
        # Focus on target element if specified
        if action.target:
            if self.driver_type == 'selenium':
                element = self.driver.find_element(By.CSS_SELECTOR, action.target)
                element.click()
            else:
                await self.page.focus(action.target)

        # Press keys
        for key in action.keys:
            if self.driver_type == 'selenium':
                key_obj = getattr(Keys, key.upper(), key)
                if action.target:
                    element.send_keys(key_obj)
                else:
                    self.driver.switch_to.active_element.send_keys(key_obj)
            else:  # Playwright
                await self.page.keyboard.press(key)

        return True

    async def _handle_refresh(self, action: Refresh) -> bool:
        """Handle Refresh action"""
        if self.driver_type == 'selenium':
            loop = asyncio.get_running_loop()
            if action.hard:
                await loop.run_in_executor(
                    None,
                    lambda: self.driver.execute_script("location.reload(true)")
                )
            else:
                await loop.run_in_executor(None, self.driver.refresh)
        else:  # Playwright
            await self.page.reload(wait_until='domcontentloaded')

        return True

    async def _handle_back(self, action: Back) -> bool:
        """Handle Back action"""
        for _ in range(action.steps):
            if self.driver_type == 'selenium':
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self.driver.back)
            else:  # Playwright
                await self.page.go_back()

        return True

    async def _post_navigate_housekeeping(self):
        """Best-effort, non-blocking overlay dismissal. Never stalls navigation."""
        selectors = [
            ".c-close-icon",
            "button#attn-overlay-close",
            "button[aria-label*='Close']",
            "button[aria-label*='close']",
            "button[aria-label*='Dismiss']",
            "#onetrust-accept-btn-handler",
            ".oci-accept-button",
        ]

        if self.driver_type == 'selenium':
            loop = asyncio.get_running_loop()

            def quick_dismiss():
                clicked = 0
                for sel in selectors:
                    try:
                        # No waits—instant check
                        els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                        if not els:
                            continue
                        # Try first two matches at most
                        for el in els[:2]:
                            try:
                                el.click()
                                clicked += 1
                            except Exception:
                                try:
                                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                                    self.driver.execute_script("arguments[0].click();", el)
                                    clicked += 1
                                except Exception:
                                    continue
                    except Exception:
                        continue
                return clicked

            # Run quickly in executor; don't care about result
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(None, quick_dismiss), timeout=1.0
                )
            except Exception:
                pass

        else:
            # Playwright: tiny timeouts; ignore errors
            for sel in selectors:
                try:
                    await self.page.click(sel, timeout=300)  # 0.3s max per selector
                except Exception:
                    continue

    def _session_alive(self) -> bool:
        """Cheap ping to confirm the driver session is alive."""
        try:
            # current_url is a lightweight call; will raise if session is gone
            _ = self.driver.current_url if self.driver_type == 'selenium' else self.page.url
            return True
        except Exception:
            return False

    async def _navigate_to(self, action: Navigate, base_url: str):
        url = urljoin(base_url, action.url) if base_url else action.url
        if self.driver_type == 'selenium':
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.driver.get, url)
            if self.overlay_housekeeping:
                try:
                    current = self.driver.current_url
                    host = (urlparse(current).hostname or "").lower()
                    # TODO create a whitelist of hosts where overlays are common
                    if host and any(x in host for x in ['bestbuy', 'amazon', 'ebay', 'walmart', 'target']):
                        try:
                            await asyncio.wait_for(
                                self._post_navigate_housekeeping(), timeout=1.25
                            )
                        except Exception:
                            pass
                except Exception:
                    pass
        else:
            await self.page.goto(url, wait_until='domcontentloaded')
            if self.overlay_housekeeping:
                try:
                    await asyncio.wait_for(self._post_navigate_housekeeping(), timeout=1.25)
                except Exception:
                    pass
        return True

    def js_click(self, driver, element):
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            driver.execute_script("arguments[0].click();", element)
            return True
        except Exception:
            return False

    async def _click_element(
        self,
        selector: str,
        timeout: Optional[int] = None
    ):
        """Click an element by selector."""
        wait = WebDriverWait(
            self.driver,
            timeout or self.default_timeout,
            poll_frequency=0.25
        )
        try:
            el = wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, selector)
                )
            )
            el.click()
        except Exception:
            # fallback to JS click
            try:
                self.js_click(self.driver, el)
            except Exception:
                return False

    async def _click(
        self,
        action: Click,
        timeout: Optional[int] = None
    ):
        """Click an element.

        Args:
            selector: CSS selector for element to click
            timeout: Timeout for finding the element
            step: Optional ScrapingStep with additional config
        """
        selector = action.selector
        if self.driver_type == 'selenium':
            loop = asyncio.get_running_loop()
            def click_sync():
                wait = WebDriverWait(
                    self.driver,
                    timeout or self.default_timeout,
                    poll_frequency=0.25
                )
                # If an overlay is present, wait for it to disappear
                try:
                    el = wait.until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, selector)
                        )
                    )
                    try:
                        el.click()
                    except Exception:
                        # fallback to JS click
                        try:
                            self.js_click(self.driver, el)
                        except Exception:
                            return False
                except Exception:
                    pass  # continue anyway; we'll try JS fallback

                # Perform the click
                element = wait.until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                try:
                    element.click()
                    self.logger.debug(f"Click performed on: {selector}")
                except Exception:
                    # Scroll into view and JS-click as a fallback
                    self.js_click(self.driver, element)

                if action.no_wait:
                    # Skip any waiting - immediately return
                    return
                elif action.wait_after_click:
                    # Wait for specified element to appear
                    try:
                        WebDriverWait(
                            self.driver,
                            action.wait_after_timeout or self.default_timeout,
                            poll_frequency=0.25
                        ).until(
                            EC.presence_of_element_located(
                                (By.CSS_SELECTOR, action.wait_after_click)
                            )
                        )
                    except Exception:
                        self.logger.warning(
                            f"Post-click wait element not found: {action.wait_after_click}"
                        )
                        return
                    else:
                        # Default: small sleep to allow any navigation/JS to start
                        time.sleep(0.5)
                else:
                    return

            await loop.run_in_executor(None, click_sync)
            return True
        else:  # Playwright
            await self.page.click(selector, timeout=self.default_timeout * 1000)
            # Handle post-click waiting for Playwright
            if action.no_wait:
                self.logger.debug("no_wait=True, skipping post-click wait")
                return
            elif action.wait_after_click:
                try:
                    await self.page.wait_for_selector(
                        action.wait_after_click,
                        timeout=(action.wait_after_timeout or self.default_timeout) * 1000
                    )
                    self.logger.debug(
                        f"Post-click element found: {action.wait_after_click}"
                    )
                except Exception:
                    self.logger.warning(
                        f"Post-click wait timed out: {action.wait_after_click}"
                    )

    async def _fill_element(self, selector: Any, value: str, clear_first: bool = False, press_enter: bool = False) -> bool:
        """Fill an input element"""
        if self.driver_type == 'selenium':
            loop = asyncio.get_running_loop()
            def fill_sync():
                element = WebDriverWait(self.driver, self.default_timeout, poll_frequency=0.25).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, selector)
                    )
                )
                if clear_first:
                    element.clear()
                element.send_keys(value)
                if press_enter:
                    element.send_keys(Keys.ENTER)
            await loop.run_in_executor(None, fill_sync)
            return True
        else:  # Playwright
            await self.page.fill(selector, value)

    async def _fill(self, action: Fill):
        """Fill an input element"""
        selector = action.selector
        value = action.value
        clear_first = action.clear_first
        press_enter = action.press_enter
        return await self._fill_element(selector, value, clear_first=clear_first, press_enter=press_enter)

    async def _wait_for_condition(self, action: Wait, timeout: int = 5):
        """
        Wait for a specific condition to be met.
        Handles multiple selectors separated by commas.
        """
        condition = action.condition
        if self.driver_type == 'selenium':
            loop = asyncio.get_running_loop()

            def wait_sync():
                # Fail fast if session died
                try:
                    _ = self.driver.current_url
                except Exception as e:
                    raise RuntimeError(
                        f"Selenium session not alive: {e}"
                    ) from e

                if action.condition_type == 'selector':
                    # Check if selector is present.
                    selectors = [s.strip() for s in condition.split(',')]
                    for selector in selectors:
                        try:
                            WebDriverWait(self.driver, timeout, poll_frequency=0.25).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                            )
                            self.logger.debug(f"Element found: {selector}")
                            return True
                        except TimeoutException:
                            if selector == selectors[-1]:  # Last selector
                                raise TimeoutException(f"None of the selectors found: {selectors}")
                            continue  # Try next selector

                # Handle prefixed conditions
                if condition.startswith('presence_of_element_located:'):
                    selectors_str = condition.split(':', 1)[1]
                    selectors = [s.strip() for s in selectors_str.split(',')]

                    # Try each selector until one works
                    for selector in selectors:
                        try:
                            WebDriverWait(self.driver, timeout, poll_frequency=0.25).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                            )
                            self.logger.debug(f"Element found: {selector}")
                            return True  # IMPORTANT: Return immediately when found
                        except TimeoutException:
                            if selector == selectors[-1]:  # Last selector
                                raise TimeoutException(f"None of the selectors found: {selectors}")
                            continue  # Try next selector

                elif condition.startswith('element_to_be_clickable:'):
                    selectors_str = condition.split(':', 1)[1]
                    selectors = [s.strip() for s in selectors_str.split(',')]

                    for selector in selectors:
                        try:
                            WebDriverWait(self.driver, timeout).until(
                                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                            )
                            self.logger.debug(f"Clickable element found: {selector}")
                            return True  # Return immediately
                        except TimeoutException:
                            if selector == selectors[-1]:
                                raise TimeoutException(f"None of the selectors clickable: {selectors}")
                            continue

                elif condition.startswith('text_to_be_present:'):
                    text = condition.split(':', 1)[1]
                    WebDriverWait(self.driver, timeout, poll_frequency=0.25).until(
                        EC.text_to_be_present_in_element((By.TAG_NAME, "body"), text)
                    )
                    self.logger.debug(f"Text found: {text}")
                    return True  # Return immediately

                elif condition.startswith('invisibility_of_element:'):
                    selector = condition.split(':', 1)[1]
                    WebDriverWait(self.driver, timeout).until(
                        EC.invisibility_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    self.logger.debug(f"Element invisible: {selector}")
                    return True  # Return immediately

                else:
                    # DEFAULT: Plain CSS selector(s) - use fast JS polling
                    selectors = [s.strip() for s in condition.split(',')]
                    deadline = time.monotonic() + timeout
                    while time.monotonic() < deadline:
                        for selector in selectors:
                            try:
                                count = self.driver.execute_script(
                                    "return document.querySelectorAll(arguments[0]).length;",
                                    selector
                                )
                                if isinstance(count, int) and count > 0:
                                    self.logger.debug(f"Element found via JS: {selector}")
                                    return True  # Return immediately when found
                            except Exception:
                                pass
                        time.sleep(0.15)  # Small delay before retry
                    # Timeout reached
                    raise TimeoutException(f"Timeout waiting for selectors: {selectors}")

            # Execute and return result
            result = await loop.run_in_executor(None, wait_sync)
            return result

        else:  # Playwright
            if condition.startswith('presence_of_element_located:'):
                selectors_str = condition.replace('presence_of_element_located:', '')
                selectors = [s.strip() for s in selectors_str.split(',')]

                # Try each selector
                for selector in selectors:
                    try:
                        await self.page.wait_for_selector(selector, timeout=timeout * 1000)
                        self.logger.debug(f"Playwright found: {selector}")
                        return True
                    except Exception:
                        if selector == selectors[-1]:
                            raise
                        continue

            elif condition.startswith('text_to_be_present:'):
                text = condition.replace('text_to_be_present:', '')
                await self.page.wait_for_function(
                    f"document.body.textContent.includes('{text}')",
                    timeout=timeout * 1000
                )
                return True

            else:
                # Try multiple selectors if comma-separated
                selectors = [s.strip() for s in condition.split(',')]
                for selector in selectors:
                    try:
                        await self.page.wait_for_selector(selector, timeout=timeout * 1000)
                        return True
                    except Exception:
                        if selector == selectors[-1]:
                            raise
                        continue

            return True

    async def _scroll_page(self, action: Scroll):
        """Scroll the page"""
        if self.driver_type == 'selenium':
            target = f"document.querySelector('{action.selector}')" if action.selector else "window"
            behavior = "'smooth'" if action.smooth else "'auto'"
            loop = asyncio.get_running_loop()
            def scroll_sync():
                if action.direction == "top":
                    return f"{target}.scrollTo({{top: 0, behavior: {behavior}}});"
                elif action.direction == "bottom":
                    return f"{target}.scrollTo({{top: {target}.scrollHeight, behavior: {behavior}}});"
                elif action.direction == "up":
                    amount = action.amount or 300
                    return f"{target}.scrollBy({{top: -{amount}, behavior: {behavior}}});"
                elif action.direction == "down":
                    amount = action.amount or 300
                    return f"{target}.scrollBy({{top: {amount}, behavior: {behavior}}});"
                elif action.amount:
                    self.driver.execute_script(f"window.scrollBy(0, {action.amount});")
                elif action.selector:
                    # Scroll to element
                    try:
                        element = self.driver.find_element(By.CSS_SELECTOR, action.selector)
                        self.driver.execute_script("arguments[0].scrollIntoView();", element)
                    except NoSuchElementException:
                        self.logger.warning(
                            f"Element not found for scrolling: {action.selector}"
                        )

            await loop.run_in_executor(None, scroll_sync)
        else:  # Playwright
            if action.direction == "bottom":
                await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            elif action.direction == "top":
                await self.page.evaluate("window.scrollTo(0, 0)")
            elif action.amount:
                await self.page.evaluate(f"window.scrollBy(0, {action.amount})")
            else:
                # Scroll to element
                try:
                    await self.page.locator(action.selector).scroll_into_view_if_needed()
                except:
                    self.logger.warning(f"Element not found for scrolling: {action.selector}")

    async def _get_cookies(self, action: GetCookies) -> Dict[str, Any]:
        """Handle GetCookies action"""
        if self.driver_type == 'selenium':
            loop = asyncio.get_running_loop()
            cookies = await loop.run_in_executor(None, self.driver.get_cookies)
        else:  # Playwright
            cookies = await self.page.context.cookies()

        # Filter by names if specified
        if action.names:
            cookies = [c for c in cookies if c.get('name') in action.names]

        # Filter by domain if specified
        if action.domain:
            cookies = [c for c in cookies if action.domain in c.get('domain', '')]

        self.logger.info(f"Retrieved {len(cookies)} cookies")
        return {"cookies": cookies}

    async def _set_cookies(self, action: SetCookies) -> bool:
        """Handle SetCookies action"""
        if self.driver_type == 'selenium':
            loop = asyncio.get_running_loop()
            for cookie in action.cookies:
                await loop.run_in_executor(
                    None,
                    lambda c=cookie: self.driver.add_cookie(c)
                )
        else:  # Playwright
            await self.page.context.add_cookies(action.cookies)

        self.logger.info(f"Set {len(action.cookies)} cookies")
        return True

    async def _handle_authentication(self, action: Authenticate):
        """Handle authentication flows"""
        username = action.username
        password = action.password
        username_selector = action.username_selector or '#username'
        password_selector = action.password_selector or '#password'
        submit_selector = action.submit_selector or 'input[type="submit"], button[type="submit"]'

        if not username or not password:
            self.logger.error(
                "Authentication requires username and password"
            )
            return

        try:
            # Fill username
            await self._fill_element(username_selector, username)
            await asyncio.sleep(0.5)

            # Fill password
            await self._fill_element(password_selector, password)
            await asyncio.sleep(0.5)

            # Submit form
            await self._click_element(submit_selector)

            # Wait for navigation/login completion
            await asyncio.sleep(2)

            self.logger.info("Authentication completed")

        except Exception as e:
            self.logger.error(f"Authentication failed: {str(e)}")
            raise

    async def _await_browser_event(self, action: AwaitBrowserEvent) -> bool:
        """
        Pause automation until a user triggers a browser-side event.

        Config (put in step.wait_condition or step.target as dict):
        - key_combo: one of ["ctrl_enter", "cmd_enter", "alt_shift_s"]  (default: "ctrl_enter")
        - show_overlay_button: bool (default False) → injects a floating "Resume" button
        - local_storage_key: str (default "__scrapeResume")
        - predicate_js: str (optional) → JS snippet returning boolean; if true, resume
        - custom_event_name: str (optional) → window.dispatchEvent(new Event(name)) resumes

        Any of these will resume:
        1) Pressing the configured key combo in the page
        2) Clicking the optional overlay "Resume" button
        3) Dispatching the custom event:  window.dispatchEvent(new Event('scrape-resume'))
        4) Setting localStorage[local_storage_key] = "1"
        5) predicate_js() evaluates to true
        """
        cfg = action.wait_condition or action.target or {}
        if isinstance(cfg, str):
            cfg = {"key_combo": cfg}

        key_combo = (cfg.get("key_combo") or "ctrl_enter").lower()
        show_overlay = bool(cfg.get("show_overlay_button", False))
        ls_key = cfg.get("local_storage_key", "__scrapeResume")
        predicate_js = cfg.get("predicate_js")  # e.g., "return !!document.querySelector('.dashboard');"
        custom_event = cfg.get("custom_event_name", "scrape-resume")
        timeout = int(action.timeout or 300)

        # 1) Inject listener once
        inject_script = f"""
    (function() {{
    if (window.__scrapeSignal && window.__scrapeSignal._bound) return 0;
    window.__scrapeSignal = window.__scrapeSignal || {{ ready:false, _bound:false }};
    function signal() {{
        try {{ localStorage.setItem('{ls_key}', '1'); }} catch(e) {{}}
        window.__scrapeSignal.ready = true;
    }}

    // Key combos
    window.addEventListener('keydown', function(e) {{
        try {{
        var k = '{key_combo}';
        if (k === 'ctrl_enter' && (e.ctrlKey || e.metaKey) && e.key === 'Enter') {{ e.preventDefault(); signal(); }}
        else if (k === 'cmd_enter' && e.metaKey && e.key === 'Enter') {{ e.preventDefault(); signal(); }}
        else if (k === 'alt_shift_s' && e.altKey && e.shiftKey && (e.key.toLowerCase() === 's')) {{ e.preventDefault(); signal(); }}
        }} catch(_e) {{}}
    }}, true);

    // Custom DOM event
    try {{
        window.addEventListener('{custom_event}', function() {{ signal(); }}, false);
    }} catch(_e) {{}}

    // Optional overlay button
    if ({'true' if show_overlay else 'false'}) {{
        try {{
        if (!document.getElementById('__scrapeResumeBtn')) {{
            var btn = document.createElement('button');
            btn.id = '__scrapeResumeBtn';
            btn.textContent = 'Resume scraping';
            Object.assign(btn.style, {{
            position: 'fixed',
            right: '16px',
            bottom: '16px',
            zIndex: 2147483647,
            padding: '10px 14px',
            fontSize: '14px',
            borderRadius: '8px',
            border: 'none',
            cursor: 'pointer',
            background: '#2563eb',
            color: '#fff',
            boxShadow: '0 4px 12px rgba(0,0,0,0.2)'
            }});
            btn.addEventListener('click', function(e) {{ e.preventDefault(); signal(); }});
            document.body.appendChild(btn);
        }}
        }} catch(_e) {{}}
    }}

    window.__scrapeSignal._bound = true;
    return 1;
    }})();
    """

        def _inject_and_check_ready():
            # Return True if already signaled
            try:
                if self.driver_type == 'selenium':
                    # inject
                    try:
                        self.driver.execute_script(inject_script)
                    except Exception:
                        pass
                    # check any of the resume signals
                    if predicate_js:
                        try:
                            ok = self.driver.execute_script(predicate_js)
                            if bool(ok):
                                return True
                        except Exception:
                            pass
                    try:
                        # localStorage flag
                        val = self.driver.execute_script(f"try{{return localStorage.getItem('{ls_key}')}}catch(e){{return null}}")
                        if val == "1":
                            return True
                    except Exception:
                        pass
                    try:
                        # in-memory flag
                        ready = self.driver.execute_script("return !!(window.__scrapeSignal && window.__scrapeSignal.ready);")
                        if bool(ready):
                            return True
                    except Exception:
                        pass
                    return False
                else:
                    # Playwright branch (optional): basic injection + predicate check
                    try:
                        self.page.evaluate(inject_script)
                    except Exception:
                        pass
                    if predicate_js:
                        try:
                            ok = self.page.evaluate(predicate_js)
                            if bool(ok):
                                return True
                        except Exception:
                            pass
                    try:
                        val = self.page.evaluate(f"try{{return localStorage.getItem('{ls_key}')}}catch(e){{return null}}")
                        if val == "1":
                            return True
                    except Exception:
                        pass
                    try:
                        ready = self.page.evaluate("() => !!(window.__scrapeSignal && window.__scrapeSignal.ready)")
                        if bool(ready):
                            return True
                    except Exception:
                        pass
                    return False
            except Exception:
                return False

        loop = asyncio.get_running_loop()
        self.logger.info(
            "🛑 Awaiting browser event: press the configured key combo in the page, click the floating button, dispatch the custom event, or set the localStorage flag to resume."
        )

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if await loop.run_in_executor(None, _inject_and_check_ready):
                # Clear the LS flag so future waits don't auto-trigger
                try:
                    if self.driver_type == 'selenium':
                        self.driver.execute_script(f"try{{localStorage.removeItem('{ls_key}')}}catch(e){{}}")
                        self.driver.execute_script("if(window.__scrapeSignal){window.__scrapeSignal.ready=false}")
                    else:
                        self.page.evaluate(f"() => {{ try{{localStorage.removeItem('{ls_key}')}}catch(e){{}}; if(window.__scrapeSignal) window.__scrapeSignal.ready=false; }}")
                except Exception:
                    pass
                self.logger.info("✅ Browser event received. Resuming automation.")
                return
            await asyncio.sleep(0.3)

        raise TimeoutError("await_browser_event timed out.")

    async def _await_human(self, action: AwaitHuman):
        """
        Let a human drive the already-open browser, then resume when a condition is met.
        'wait_condition' or 'target' may contain:
        - selector: CSS selector to appear (presence)
        - url_contains: substring expected in current URL
        - title_contains: substring expected in document.title
        """
        timeout = int(action.timeout or 300)
        selector = None
        url_contains = None
        title_contains = None

        if action.condition_type == 'selector':
            selector = action.target
        elif action.condition_type == 'url_contains':
            selector = None
            url_contains = action.target
        elif action.condition_type == 'title_contains':
            selector = None
            title_contains = action.target
        else:
            # Default: expect a dict in target or wait_condition
            cond = action.wait_condition or action.target or {}
            if isinstance(cond, str):
                cond = {"selector": cond}
            selector = cond.get("selector")
            if not selector:
                self.logger.error("await_human requires at least one condition (selector, url_contains, title_contains)")
                return

        loop = asyncio.get_running_loop()

        def _check_sync() -> bool:
            try:
                if self.driver_type == 'selenium':
                    cur_url = self.driver.current_url
                    cur_title = self.driver.title
                    if url_contains and (url_contains not in cur_url):
                        return False
                    if title_contains and (title_contains not in cur_title):
                        return False
                    if selector:
                        try:
                            count = self.driver.execute_script(
                                "return document.querySelectorAll(arguments[0]).length;", selector
                            )
                            if int(count) <= 0:
                                return False
                        except Exception:
                            return False
                    return True
                else:
                    cur_url = self.page.url
                    if url_contains and (url_contains not in cur_url):
                        return False
                    if selector:
                        try:
                            # tiny, non-blocking check
                            el = self.page.query_selector(selector)
                            if not el:
                                return False
                        except Exception:
                            return False
                    return True
            except Exception:
                return False

        self.logger.info(
            f"🛑 {action.message} in the browser window..."
        )
        self.logger.info(
            "ℹ️  I’ll resume automatically when the expected page/element is present."
        )

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ok = await loop.run_in_executor(None, _check_sync)
            if ok:
                self.logger.info(
                    "✅ Human step condition satisfied. Resuming automation."
                )
                return
            await asyncio.sleep(0.5)

        raise TimeoutError(
            "await_human timed out waiting for the specified condition."
        )

    async def _await_keypress(self, action: AwaitKeyPress):
        """
        Pause until the operator presses ENTER in the console.
        Useful when there is no reliable selector to wait on.
        """
        timeout = int(action.timeout or 300)
        prompt = action.message or "Press ENTER to continue..."
        expected_key = action.key

        self.logger.info(f"🛑 {prompt}")
        start = time.monotonic()

        loop = asyncio.get_running_loop()
        while time.monotonic() - start < timeout:
            ready, _, _ = await loop.run_in_executor(
                None, lambda: select.select([sys.stdin], [], [], 0.5)
            )
            if ready:
                try:
                    keypress = sys.stdin.readline().strip()
                    if expected_key is None or keypress == expected_key:
                        self.logger.info("✅ Continuing after keypress.")
                        return
                except Exception:
                    pass
        raise TimeoutError("await_keypress timed out.")

    async def _exec_loop(self, action: Loop, base_url: str) -> bool:
        """Handle Loop action - execute actions repeatedly"""
        iteration = 0
        max_iter = action.iterations or action.max_iterations

        while iteration < max_iter:
            # Check condition if provided
            if action.condition:
                should_continue = await self._evaluate_condition(action.condition)
                if not should_continue:
                    break

            # Execute all actions in the loop
            for loop_action in action.actions:
                step = ScrapingStep(action=loop_action)
                success = await self._execute_step(step, base_url)

                if not success and action.break_on_error:
                    self.logger.warning(f"Loop stopped at iteration {iteration} due to error")
                    return False

            iteration += 1

            # Break if we've reached specified iterations
            if action.iterations and iteration >= action.iterations:
                break

        self.logger.info(f"Loop completed {iteration} iterations")
        return True

    async def _evaluate_condition(self, condition: str) -> bool:
        """Evaluate a JavaScript condition"""
        if self.driver_type == 'selenium':
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.driver.execute_script(f"return Boolean({condition})")
            )
        else:  # Playwright
            result = await self.page.evaluate(f"() => Boolean({condition})")

        return bool(result)

    async def _extract_content(
        self,
        url: str,
        selectors: List[ScrapingSelector]
    ) -> ScrapingResult:
        """Extract content based on provided selectors"""
        # Get page source
        if self.driver_type == 'selenium':
            loop = asyncio.get_running_loop()
            page_source = await loop.run_in_executor(None, lambda: self.driver.page_source)
        else:  # Playwright
            page_source = await self.page.content()

        # Parse with BeautifulSoup
        soup = BeautifulSoup(page_source, 'html.parser')

        # Extract data based on selectors
        extracted_data = {}
        for selector_config in selectors:
            try:
                data = await self._extract_by_selector(soup, selector_config)
                extracted_data[selector_config.name] = data
            except Exception as e:
                self.logger.warning(f"Failed to extract {selector_config.name}: {str(e)}")
                extracted_data[selector_config.name] = None

        return ScrapingResult(
            url=url,
            content=page_source,
            bs_soup=soup,
            extracted_data=extracted_data,
            timestamp=str(time.time())
        )

    async def _extract_full_content(self, url: str) -> ScrapingResult:
        """Extract full page content when no selectors provided"""
        # Get page source
        if self.driver_type == 'selenium':
            loop = asyncio.get_running_loop()
            page_source = await loop.run_in_executor(None, lambda: self.driver.page_source)
        else:  # Playwright
            page_source = await self.page.content()

        # Parse with BeautifulSoup
        soup = BeautifulSoup(page_source, 'html.parser')

        # Extract basic page information
        extracted_data = {
            "title": soup.title.string if soup.title else "",
            "body_text": soup.get_text(strip=True),
            "links": [a.get('href') for a in soup.find_all('a', href=True)],
            "images": [img.get('src') for img in soup.find_all('img', src=True)]
        }

        return ScrapingResult(
            url=url,
            content=page_source,
            bs_soup=soup,
            extracted_data=extracted_data,
            timestamp=str(time.time())
        )

    async def _extract_by_selector(
        self,
        soup: BeautifulSoup,
        selector_config: ScrapingSelector
    ) -> Union[str, List[str], Dict[str, Any]]:
        """Extract content using a specific selector configuration"""
        if selector_config.selector_type == 'css':
            elements = soup.select(selector_config.selector)
        elif selector_config.selector_type == 'xpath':
            # BeautifulSoup doesn't support XPath, you'd need lxml here
            # For now, fallback to CSS
            elements = soup.select(selector_config.selector)
        else:  # tag
            elements = soup.find_all(selector_config.selector)

        if not elements:
            return None if not selector_config.multiple else []

        # Extract content based on type
        extracted = []
        for element in elements:
            if selector_config.extract_type == 'text':
                content = element.get_text(strip=True)
            elif selector_config.extract_type == 'html':
                content = str(element)
            elif selector_config.extract_type == 'attribute':
                content = element.get(selector_config.attribute, '')
            else:
                content = element.get_text(strip=True)

            extracted.append(content)

        return extracted if selector_config.multiple else extracted[0] if extracted else None

    async def _get_current_url(self) -> str:
        """Get current page URL"""
        if self.driver_type == 'selenium':
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: self.driver.current_url)
        else:  # Playwright
            return self.page.url

    async def cleanup(self):
        """Clean up resources"""
        try:
            if self.driver_type == 'selenium' and self.driver:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self.driver.quit)
            elif self.browser:
                await self.browser.close()
        except Exception as e:
            self.logger.error(f"Cleanup failed: {str(e)}")

    def get_tool_schema(self) -> Dict[str, Any]:
        """Define the tool for LLM interaction"""
        return {
            "type": "function",
            "function": {
                "name": "web_scraping_tool",
                "description": "Execute automated web scraping with step-by-step navigation and content extraction",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "steps": {
                            "type": "array",
                            "description": "List of navigation and interaction steps",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "action": {"type": "string", "enum": [
                                        "navigate", "click", "fill", "evaluate", "press_key",
                                        "refresh", "back", "scroll", "get_cookies", "set_cookies",
                                        "wait", "authenticate", "await_human", "await_key_press",
                                        "await_browser_event", "loop"
                                    ]},
                                    "target": {"type": "string"},
                                    "value": {"type": "string"},
                                    "description": {"type": "string"}
                                }
                            }
                        },
                        "selectors": {
                            "type": "array",
                            "description": "Content selectors for extraction",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "selector": {"type": "string"},
                                    "extract_type": {"type": "string", "enum": ["text", "html", "attribute"]}
                                }
                            }
                        },
                        "base_url": {"type": "string", "description": "Base URL for relative links"}
                    },
                    "required": ["steps"]
                }
            }
        }
