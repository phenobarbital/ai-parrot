"""
WebScrapingTool for AI-Parrot
Combines Selenium/Playwright automation with LLM-directed scraping
"""
from pathlib import Path
import random
import sys
from typing import Dict, List, Any, Optional, Union, Literal
import select
import time
import asyncio
import logging
import base64
import re
import json
import contextlib
from urllib.parse import urlparse, urljoin
from lxml import html as lxml_html
import aiofiles
from pydantic import BaseModel, Field
from bs4 import BeautifulSoup
# Selenium imports
try:
    from seleniumwire import webdriver
except ImportError:
    from selenium import webdriver
from selenium.webdriver.chrome.options import Options
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
    Select,
    Evaluate,
    PressKey,
    Refresh,
    Back,
    Wait,
    Scroll,
    Authenticate,
    GetCookies,
    SetCookies,
    GetText,
    GetHTML,
    Screenshot,
    WaitForDownload,
    UploadFile,
    AwaitHuman,
    AwaitKeyPress,
    AwaitBrowserEvent,
    Loop,
    ScrapingStep,
    ScrapingSelector,
    ScrapingResult,
    Conditional
)


class WebScrapingToolArgs(BaseModel):
    """Arguments schema for WebScrapingTool."""
    steps: List[Dict[str, Any]] = Field(
        description="List of navigation and interaction steps. Each step should have 'action' and 'description'"
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
    full_page: bool = Field(
        default=False,
        description="Whether to capture full page content"
    )
    headless: bool = Field(
        default=True,
        description="Whether to run the browser in headless mode"
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

    Supported Actions:
        * Navigation: navigate, back, refresh
        * Interaction: click, fill, press_key, scroll
        * Data Extraction: get_text, get_html, get_cookies
        * Authentication: authenticate
        * File Operations: upload_file, wait_for_download, screenshot
        * State Management: set_cookies
        * Waiting: wait, await_human, await_keypress, await_browser_event
        * Evaluation: evaluate
        * Control Flow: loop
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
        full_page: bool = False,
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
        self._full_page: bool = full_page
        self.results: List[ScrapingResult] = []
        # Allow turning overlay housekeeping on/off (default ON)
        self.overlay_housekeeping: bool = kwargs.get('overlay_housekeeping', True)
        # Configuration
        self.default_timeout = kwargs.get('default_timeout', 10)
        self.retry_attempts = kwargs.get('retry_attempts', 3)
        self.delay_between_actions = kwargs.get('delay_between_actions', 1)
        # extracted cookies and headers from Driver
        self.extracted_cookies: Dict[str, str] = {}
        self.extracted_headers: Dict[str, str] = {}
        self.extracted_authorization: str = None
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
            selectors: List of content selectors to do extraction
            base_url: Base URL for relative links

        Returns:
            Dictionary with scraping results
        """
        self.results = []

        try:
            await self.initialize_driver(
                config_overrides=browser_config
            )

            # Convert dictionaries to dataclasses
            scraping_steps = [ScrapingStep.from_dict(step) for step in steps]
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
                        "error_message": r.error_message,
                        "content": r.content,
                        'bs': r.bs_soup

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
        # Attempt to capture from performance logs first
        try:
            # turn on CDP Network domain
            self.driver.execute_cdp_cmd("Network.enable", {})
        except Exception:  # pragma: no cover - command may not exist
            pass
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
                try:
                    success = await self._execute_step(step, base_url)
                except TimeoutError:
                    self.logger.error(f"Step timed out: {step.description}")
                    success = False
                    break

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
            elif self._full_page:
                # Default: extract full page content
                current_url = await self._get_current_url()
                result = await self._extract_full_content(current_url)
                if result:
                    self.results.append(result)
            # and extract the headers, authorization and cookies
            try:
                self.extracted_headers = self._extract_headers()
                self.extracted_authorization = self._extract_authorization()
                self.extracted_cookies = self._collect_cookies()
            except Exception as e:
                self.logger.error(
                    f"Error extracting headers, authorization, or cookies: {str(e)}"
                )

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

    async def _execute_step(self, step: ScrapingStep, base_url: str = "", args: dict = None) -> bool:
        """Execute a single scraping step with a hard timeout per step."""
        action = step.action
        action_type = action.get_action_type()
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
            elif action_type == 'select':
                result = await self._select(action)
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
            elif action_type == 'get_text':
                result = await self._get_text(action)
            elif action_type == 'get_html':
                result = await self._get_html(action, args)
            elif action_type == 'screenshot':
                result = await self._take_screenshot(action)
            elif action_type == 'wait_for_download':
                result = await self._wait_for_download(action)
            elif action_type == 'upload_file':
                result = await self._upload_file(action)
            elif action_type == 'await_keypress':
                try:
                    result = await self._await_keypress(action)
                except TimeoutError:
                    raise
            elif action_type == 'await_browser_event':
                try:
                    result = await self._await_browser_event(action)
                except TimeoutError:
                    raise
            elif action_type == 'wait':
                result = await self._wait_for_condition(
                    action,
                    step.action.timeout or self.default_timeout
                )
            elif action_type == 'scroll':
                result = await self._scroll_page(action)
            elif action_type == 'authenticate':
                result = await self._handle_authentication(action)
            elif action_type == 'loop':
                result = await self._exec_loop(action, base_url)
            elif action_type == 'conditional':
                result = await self._exec_conditional(action, base_url, args)
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

    async def _select_option(
        self,
        selector: str,
        value: Optional[str] = None,
        text: Optional[str] = None,
        index: Optional[int] = None,
        by: str = 'value',
        blur_after: bool = True,
        wait_after_select: Optional[str] = None,
        wait_timeout: int = 2
    ) -> bool:
        """Select an option from a dropdown/select element"""

        if self.driver_type == 'selenium':
            from selenium.webdriver.support.ui import Select as SeleniumSelect

            loop = asyncio.get_running_loop()

            def select_sync():
                # Wait for select element to be present
                element = WebDriverWait(
                    self.driver,
                    self.default_timeout,
                    poll_frequency=0.25
                ).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )

                # Create Select object
                select = SeleniumSelect(element)

                # Perform selection based on method
                if by == 'value':
                    select.select_by_value(value)
                elif by == 'text':
                    select.select_by_visible_text(text)
                elif by == 'index':
                    select.select_by_index(index)

                # Trigger blur/change events if requested
                if blur_after:
                    # Trigger change event
                    self.driver.execute_script(
                        "arguments[0].dispatchEvent(new Event('change', { bubbles: true }));",
                        element
                    )
                    # Trigger blur event
                    self.driver.execute_script(
                        "arguments[0].blur();",
                        element
                    )

                # Wait for post-select element if specified
                if wait_after_select:
                    try:
                        WebDriverWait(self.driver, wait_timeout).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, wait_after_select))
                        )
                        self.logger.debug(f"Post-select element found: {wait_after_select}")
                    except TimeoutException:
                        self.logger.warning(
                            f"Post-select wait timed out: {wait_after_select}"
                        )

            await loop.run_in_executor(None, select_sync)
            return True

        else:  # Playwright
            # Playwright has built-in select support
            if by == 'value':
                await self.page.select_option(selector, value=value)
            elif by == 'text':
                await self.page.select_option(selector, label=text)
            elif by == 'index':
                await self.page.select_option(selector, index=index)

            # Trigger blur/change events if requested
            if blur_after:
                await self.page.evaluate(f"""
                    const select = document.querySelector('{selector}');
                    select.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    select.blur();
                """)

            # Wait for post-select element if specified
            if wait_after_select:
                try:
                    await self.page.wait_for_selector(
                        wait_after_select,
                        timeout=wait_timeout * 1000
                    )
                    self.logger.debug(f"Post-select element found: {wait_after_select}")
                except Exception:
                    self.logger.warning(
                        f"Post-select wait timed out: {wait_after_select}"
                    )

            return True


    async def _select(self, action: Select):
        """Handle select action"""
        return await self._select_option(
            selector=action.selector,
            value=action.value,
            text=action.text,
            index=action.index,
            by=action.by,
            blur_after=action.blur_after,
            wait_after_select=action.wait_after_select,
            wait_timeout=action.wait_timeout
        )

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

    async def _click(self, action: Click, timeout: Optional[int] = None) -> bool:
        """
        Enhanced click method supporting CSS, XPath, and text-based selection.

        Args:
            action: Click action with selector and options
            timeout: Optional timeout override

        Returns:
            bool: True if click successful
        """
        selector = action.selector
        selector_type = action.selector_type
        timeout = timeout or action.timeout or self.default_timeout

        if self.driver_type == 'selenium':
            loop = asyncio.get_running_loop()

            def click_sync():
                # Determine the locator strategy based on selector_type
                if selector_type == 'xpath':
                    by_type = By.XPATH
                    locator = selector
                elif selector_type == 'text':
                    # Convert text search to XPath
                    # Supports exact match, contains, and case-insensitive
                    if selector.startswith('='):
                        # Exact match: =Filters
                        text = selector[1:]
                        by_type = By.XPATH
                        locator = f"//*[normalize-space(text())='{text}']"
                    elif selector.startswith('~'):
                        # Case-insensitive contains: ~filters
                        text = selector[1:].lower()
                        by_type = By.XPATH
                        locator = f"//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{text}')]"
                    else:
                        # Default: contains (case-sensitive)
                        by_type = By.XPATH
                        locator = f"//*[contains(text(), '{selector}')]"
                else:  # css (default)
                    by_type = By.CSS_SELECTOR
                    locator = selector

                self.logger.debug(f"Clicking element: {by_type}='{locator}'")

                wait = WebDriverWait(
                    self.driver,
                    timeout,
                    poll_frequency=0.25
                )

                # Wait for element to be present
                try:
                    element = wait.until(
                        EC.presence_of_element_located((by_type, locator))
                    )
                except Exception as e:
                    self.logger.error(f"Element not found: {by_type}='{locator}'")
                    raise

                # Try regular click first
                try:
                    # Wait for element to be clickable
                    element = wait.until(
                        EC.element_to_be_clickable((by_type, locator))
                    )
                    element.click()
                    self.logger.debug(f"Click performed on: {locator}")
                except Exception:
                    # Fallback to JS click
                    try:
                        self.logger.debug("Regular click failed, trying JS click")
                        self.js_click(self.driver, element)
                    except Exception as e:
                        self.logger.error(f"Both click methods failed: {str(e)}")
                        raise

                # Handle post-click waiting
                if action.no_wait:
                    self.logger.debug("no_wait=True, skipping post-click wait")
                    return True
                elif action.wait_after_click:
                    # Wait for specified element to appear
                    try:
                        WebDriverWait(
                            self.driver,
                            action.wait_timeout or self.default_timeout,
                            poll_frequency=0.25
                        ).until(
                            EC.presence_of_element_located(
                                (By.CSS_SELECTOR, action.wait_after_click)
                            )
                        )
                        self.logger.debug(f"Post-click element found: {action.wait_after_click}")
                    except Exception:
                        self.logger.warning(
                            f"Post-click wait element not found: {action.wait_after_click}"
                        )
                else:
                    # Default: small sleep to allow any navigation/JS to start
                    time.sleep(0.5)

                return True

            await loop.run_in_executor(None, click_sync)
            return True

        else:  # Playwright
            if selector_type == 'xpath':
                # Playwright supports XPath directly
                await self.page.click(f"xpath={selector}", timeout=timeout * 1000)
            elif selector_type == 'text':
                # Playwright has native text selection
                if selector.startswith('='):
                    # Exact text match
                    text = selector[1:]
                    await self.page.click(f"text={text}", timeout=timeout * 1000)
                elif selector.startswith('~'):
                    # Case-insensitive (Playwright doesn't have built-in, use XPath)
                    text = selector[1:].lower()
                    xpath = f"//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{text}')]"
                    await self.page.click(f"xpath={xpath}", timeout=timeout * 1000)
                else:
                    # Contains (partial match)
                    await self.page.click(f"text={selector}", timeout=timeout * 1000)
            else:
                # CSS selector
                await self.page.click(selector, timeout=timeout * 1000)

            # Handle post-click waiting for Playwright
            if action.no_wait:
                self.logger.debug("no_wait=True, skipping post-click wait")
            elif action.wait_after_click:
                try:
                    await self.page.wait_for_selector(
                        action.wait_after_click,
                        timeout=(action.wait_timeout or self.default_timeout) * 1000
                    )
                    self.logger.debug(f"Post-click element found: {action.wait_after_click}")
                except Exception:
                    self.logger.warning(
                        f"Post-click wait timed out: {action.wait_after_click}"
                    )

            return True

    async def _fill_element(
        self,
        selector: Any,
        value: str,
        selector_type: str = 'css',
        clear_first: bool = False,
        press_enter: bool = False
    ) -> bool:
        """Fill an input element"""
        if self.driver_type == 'selenium':
            loop = asyncio.get_running_loop()
            def fill_sync():
                if selector_type == 'xpath':
                    by_type = By.XPATH
                    locator = selector
                elif selector_type == 'text':
                    # Convert text to XPath for form fields
                    by_type = By.XPATH
                    if selector.startswith('='):
                        text = selector[1:]
                        # Find input with label containing text
                        locator = f"//label[contains(text(), '{text}')]/following-sibling::input | //input[@placeholder='{text}']"
                    else:
                        locator = f"//label[contains(text(), '{selector}')]/following-sibling::input | //input[@placeholder='{selector}']"
                else:
                    by_type = By.CSS_SELECTOR
                    locator = selector
                element = WebDriverWait(
                    self.driver,
                    self.default_timeout,
                    poll_frequency=0.25
                ).until(
                    EC.presence_of_element_located((by_type, locator))
                )
                if clear_first:
                    element.clear()
                element.send_keys(value)
                if press_enter:
                    element.send_keys(Keys.ENTER)
            await loop.run_in_executor(None, fill_sync)
            return True
        else:  # Playwright
            if selector_type == 'xpath':
                await self.page.fill(f"xpath={selector}", value)
            elif selector_type == 'text':
                # Playwright text selector for inputs
                if selector.startswith('='):
                    text = selector[1:]
                    await self.page.fill(f"text={text}", value)
                else:
                    await self.page.fill(f"text={selector}", value)
            else:
                await self.page.fill(selector, value)

            if press_enter:
                await self.page.keyboard.press('Enter')

        return True

    async def _fill(self, action: Fill):
        """Fill an input element"""
        selector = action.selector
        value = action.value
        clear_first = action.clear_first
        press_enter = action.press_enter
        selector_type = getattr(action, 'selector_type', 'css')
        return await self._fill_element(
            selector, value,
            selector_type=selector_type,
            clear_first=clear_first,
            press_enter=press_enter
        )

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
                if action.condition_type == 'simple':
                    # do a simple wait of N.seconds:
                    time.sleep(int(timeout))
                    return True
                elif action.condition_type == 'url_contains':
                    WebDriverWait(self.driver, timeout, poll_frequency=0.25).until(
                        EC.url_contains(condition)
                    )
                    self.logger.debug(f"URL contains: {condition}")
                    return True
                elif action.condition_type == 'url_is':
                    WebDriverWait(self.driver, timeout, poll_frequency=0.25).until(
                        EC.url_to_be(condition)
                    )
                    self.logger.debug(f"URL is: {condition}")
                    return True
                elif action.condition_type == 'selector':
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

    async def _get_text(self, action: GetText) -> bool:
        """
        Extract pure text content from elements and save to results.

        Args:
            action: GetText action with selector and options

        Returns:
            bool: True if extraction successful
        """
        try:
            # Get current URL
            current_url = await self._get_current_url()

            # Get page source
            if self.driver_type == 'selenium':
                loop = asyncio.get_running_loop()
                page_source = await loop.run_in_executor(None, lambda: self.driver.page_source)
            else:  # Playwright
                page_source = await self.page.content()

            # Parse with BeautifulSoup
            soup = BeautifulSoup(page_source, 'html.parser')

            # Find elements by selector
            elements = soup.select(action.selector)

            if not elements:
                self.logger.warning(f"No elements found for selector: {action.selector}")
                extracted_text = None
            elif action.multiple:
                # Extract text from all matching elements
                extracted_text = [elem.get_text(strip=True) for elem in elements]
            else:
                # Extract text from first element only
                extracted_text = elements[0].get_text(strip=True)

            # Create ScrapingResult and append to results
            result = ScrapingResult(
                url=current_url,
                content=page_source,
                bs_soup=soup,
                extracted_data={action.extract_name: extracted_text},
                metadata={
                    "selector": action.selector,
                    "multiple": action.multiple,
                    "elements_found": len(elements)
                },
                timestamp=str(time.time()),
                success=extracted_text is not None
            )

            self.results.append(result)
            self.logger.info(
                f"Extracted text from {len(elements)} element(s) using selector: {action.selector}"
            )

            return True

        except Exception as e:
            self.logger.error(f"GetText action failed: {str(e)}")
            # Create error result
            error_result = ScrapingResult(
                url=await self._get_current_url() if hasattr(self, 'driver') or hasattr(self, 'page') else "",
                content="",
                bs_soup=BeautifulSoup("", 'html.parser'),
                extracted_data={action.extract_name: None},
                success=False,
                error_message=str(e),
                timestamp=str(time.time())
            )
            self.results.append(error_result)
            return False


    async def _get_html(self, action: GetHTML, args: dict) -> bool:
        """
        Extract complete HTML content from elements and save to results.

        Args:
            action: GetHTML action with selector and options
            args: Additional arguments for the action

        Returns:
            bool: True if extraction successful
        """
        try:
            # Get current URL
            current_url = await self._get_current_url()

            # Get page source
            if self.driver_type == 'selenium':
                loop = asyncio.get_running_loop()
                page_source = await loop.run_in_executor(None, lambda: self.driver.page_source)
            else:  # Playwright
                page_source = await self.page.content()

            # Parse with BeautifulSoup
            soup = BeautifulSoup(page_source, 'html.parser')

            # Handle different selector types
            selector_type = getattr(action, 'selector_type', 'css')

            # Find elements by selector
            if selector_type == 'xpath':
                # Use lxml for XPath support
                tree = lxml_html.fromstring(page_source)
                elements_lxml = tree.xpath(action.selector)

                # Convert lxml elements back to BeautifulSoup for consistency
                elements = []
                for elem in elements_lxml:
                    html_str = lxml_html.tostring(elem, encoding='unicode')
                    elements.append(BeautifulSoup(html_str, 'html.parser'))
            else:
                # CSS selector (default)
                elements = soup.select(action.selector)

            if not elements:
                self.logger.warning(f"No elements found for selector: {action.selector}")
                extracted_html = None

            # Extract HTML from all matching elements
            elif action.multiple:
                for elem in elements:
                    # generate one scrapping result per element:
                    elem_bs = elem if isinstance(elem, BeautifulSoup) else BeautifulSoup(str(elem), 'html.parser')
                    data = args.get('data', {}) if args else {}
                    result = ScrapingResult(
                        url=current_url,
                        content=page_source,
                        bs_soup=elem_bs,
                        extracted_data={action.extract_name: str(elem)},
                        metadata={
                            "selector": action.selector,
                            "selector_type": selector_type,
                            "multiple": action.multiple,
                            "iteration": (args or {}).get("iteration"),
                            "data": data,
                        },
                        timestamp=str(time.time()),
                        success=True
                    )
                    # print('DEBUG HTML > ', result)
                    self.results.append(result)
            else:
                extracted_html = str(elements[0])
                # Create ScrapingResult and append to results
                result = ScrapingResult(
                    url=current_url,
                    content=page_source,
                    bs_soup=soup,
                    extracted_data={action.extract_name: extracted_html},
                    metadata={
                        "selector": action.selector,
                        "selector_type": selector_type,
                        "multiple": action.multiple,
                        "elements_found": len(elements)
                    },
                    timestamp=str(time.time()),
                    success=extracted_html is not None
                )

                self.results.append(result)
            self.logger.info(
                f"Extracted HTML from {len(elements)} element(s) using selector: {action.selector}"
            )

            return True

        except Exception as e:
            self.logger.error(f"GetHTML action failed: {str(e)}")
            # Create error result
            error_result = ScrapingResult(
                url=await self._get_current_url() if hasattr(self, 'driver') or hasattr(self, 'page') else "",
                content="",
                bs_soup=BeautifulSoup("", 'html.parser'),
                extracted_data={action.extract_name: None},
                success=False,
                error_message=str(e),
                timestamp=str(time.time())
            )
            self.results.append(error_result)
            return False


    async def _take_screenshot(self, action: Screenshot) -> bool:
        """
        Take a screenshot of the page or specific element.

        Args:
            action: Screenshot action with options

        Returns:
            bool: True if screenshot successful
        """
        try:
            screenshot_data = None
            output_path = action.output_path
            if isinstance(output_path, str):
                output_path = Path(output_path).resolve()
            screenshot_name = action.get_filename()

            if self.driver_type == 'selenium':
                loop = asyncio.get_running_loop()

                def take_screenshot_sync():
                    if action.selector:
                        # Screenshot of specific element
                        element = self.driver.find_element(By.CSS_SELECTOR, action.selector)
                        screenshot_bytes = element.screenshot_as_png
                    else:
                        # Full page screenshot
                        if action.full_page:
                            # Full page screenshot (requires scrolling for some drivers)
                            screenshot_bytes = self.driver.get_screenshot_as_png()
                        else:
                            # Viewport screenshot only
                            screenshot_bytes = self.driver.get_screenshot_as_png()

                    return screenshot_bytes

                screenshot_bytes = await loop.run_in_executor(None, take_screenshot_sync)

                # Save to file if path provided
                filename = output_path.joinpath(screenshot_name)
                async with aiofiles.open(filename, 'wb') as f:
                    await f.write(screenshot_bytes)
                self.logger.info(f"Screenshot saved to: {filename}")

                # Return base64 if requested
                if action.return_base64:
                    return base64.b64encode(screenshot_bytes).decode('utf-8')

                return True

            else:  # Playwright
                screenshot_options = {}

                if action.full_page:
                    screenshot_options['full_page'] = True

                if action.selector:
                    # Screenshot of specific element
                    element = self.page.locator(action.selector)
                    screenshot_bytes = await element.screenshot(**screenshot_options)
                else:
                    # Page screenshot
                    screenshot_bytes = await self.page.screenshot(**screenshot_options)

                # Save to file if path provided
                if output_path:
                    with open(output_path, 'wb') as f:
                        f.write(screenshot_bytes)
                    self.logger.info(f"Screenshot saved to: {output_path}")

                # Return base64 if requested
                if action.return_base64:
                    screenshot_data = base64.b64encode(screenshot_bytes).decode('utf-8')
                else:
                    screenshot_data = True

            # Create ScrapingResult with screenshot data
            current_url = await self._get_current_url()

            result = ScrapingResult(
                url=current_url,
                content="",  # No HTML content for screenshots
                bs_soup=BeautifulSoup("", 'html.parser'),
                extracted_data={
                    "screenshot": screenshot_data if action.return_base64 else output_path,
                    "screenshot_base64": screenshot_data if action.return_base64 else None
                },
                metadata={
                    "selector": action.selector,
                    "full_page": action.full_page,
                    "output_path": output_path,
                    "returned_base64": action.return_base64
                },
                timestamp=str(time.time()),
                success=True
            )

            self.results.append(result)
            self.logger.info(
                f"Screenshot taken: {'element ' + action.selector if action.selector else 'full page'}"
            )

            return True

        except Exception as e:
            self.logger.error(f"Screenshot action failed: {str(e)}")
            # Create error result
            error_result = ScrapingResult(
                url=await self._get_current_url() if hasattr(self, 'driver') or hasattr(self, 'page') else "",
                content="",
                bs_soup=BeautifulSoup("", 'html.parser'),
                extracted_data={"screenshot": None},
                success=False,
                error_message=str(e),
                timestamp=str(time.time())
            )
            self.results.append(error_result)
            return False

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
        if action.method == 'bearer':
            if not action.token:
                self.logger.error("Bearer token authentication requires a 'token' value.")
                return False
            # Construct the header from the provided format and token
            header_value = action.header_value_format.format(action.token)
            headers = {action.header_name: header_value}
            if self.driver_type == 'selenium':
                # For Selenium, we use the Chrome DevTools Protocol (CDP) to set headers.
                # This requires a Chromium-based browser (Chrome, Edge).
                if not hasattr(self.driver, 'execute_cdp_cmd'):
                    self.logger.error(
                        "Bearer token injection for Selenium is only supported on Chromium-based browsers."
                    )
                    return False
                self.logger.info(f"Setting extra HTTP headers for Selenium session: {list(headers.keys())}")
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: self.driver.execute_cdp_cmd(
                        'Network.setExtraHTTPHeaders', {'headers': headers}
                    )
                )

            elif self.driver_type == 'playwright' and PLAYWRIGHT_AVAILABLE:
                # Playwright has a direct and simple method for this.
                self.logger.info(f"Setting extra HTTP headers for Playwright session: {list(headers.keys())}")
                await self.page.set_extra_http_headers(headers)

            else:
                self.logger.error(f"Bearer token authentication is not implemented for driver type: {self.driver_type}")
                return False

            self.logger.info("Bearer token authentication configured. All subsequent requests will include the specified header.")
            return True

        # action form (only programmed until now)
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
            await self._fill_element(username_selector, username, press_enter=action.enter_on_username)
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

        # Inject listener with green button and auto-removal
        inject_script = f"""
(function() {{
if (window.__scrapeSignal && window.__scrapeSignal._bound) return 0;
window.__scrapeSignal = window.__scrapeSignal || {{ ready:false, _bound:false }};
function signal() {{
    try {{ localStorage.setItem('{ls_key}', '1'); }} catch(e) {{}}
    window.__scrapeSignal.ready = true;
    // Remove the button when clicked
    var btn = document.getElementById('__scrapeResumeBtn');
    if (btn) {{ btn.remove(); }}
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

// Optional overlay button with green background
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
        background: '#10b981',
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

    async def _wait_for_download(self, action: WaitForDownload) -> bool:
        """
        Wait for a file download to complete.

        Args:
            action: WaitForDownload action with download monitoring options

        Returns:
            bool: True if download detected successfully
        """
        try:
            # Determine download directory
            if action.download_path:
                download_dir = Path(action.download_path)
            else:
                # Try to get default download directory from browser
                if self.driver_type == 'selenium':
                    # Check Chrome prefs for download directory
                    try:
                        prefs = self.driver.execute_cdp_cmd(
                            'Page.getDownloadInfo', {}
                        )
                        download_dir = Path(prefs.get('behavior', {}).get('downloadPath', '.'))
                    except:
                        # Fallback to common default locations
                        download_dir = Path.home() / 'Downloads'
                else:  # Playwright
                    # Playwright typically uses its own download handling
                    download_dir = Path.cwd() / 'downloads'

            if not download_dir.exists():
                download_dir.mkdir(parents=True, exist_ok=True)

            self.logger.info(f"Monitoring for downloads in: {download_dir}")

            # Get initial files in directory
            initial_files = set(download_dir.glob('*'))

            # Wait for new file to appear
            timeout = action.timeout
            start_time = time.time()
            downloaded_file = None

            while time.time() - start_time < timeout:
                current_files = set(download_dir.glob('*'))
                new_files = current_files - initial_files

                # Filter by pattern if specified
                if action.filename_pattern:
                    matching_files = [
                        f for f in new_files
                        if f.match(action.filename_pattern)
                    ]
                else:
                    matching_files = list(new_files)

                # Check if any new files are complete (not .tmp, .crdownload, .part, etc.)
                for file_path in matching_files:
                    # Skip temporary download files
                    if any(ext in file_path.suffix.lower() for ext in ['.tmp', '.crdownload', '.part', '.download']):
                        continue

                    # Check if file is still being written (size changing)
                    try:
                        size1 = file_path.stat().st_size
                        await asyncio.sleep(0.5)
                        size2 = file_path.stat().st_size

                        if size1 == size2 and size1 > 0:
                            # File size stable and non-zero - download complete
                            downloaded_file = file_path
                            break
                    except:
                        continue

                if downloaded_file:
                    break

                await asyncio.sleep(1)

            if not downloaded_file:
                self.logger.error(
                    f"Download not detected within {timeout} seconds"
                )
                return False

            self.logger.info(f"Download complete: {downloaded_file.name}")

            # Move file if requested
            if action.move_to:
                move_to_path = Path(action.move_to)
                if move_to_path.is_dir():
                    final_path = move_to_path / downloaded_file.name
                else:
                    final_path = move_to_path

                final_path.parent.mkdir(parents=True, exist_ok=True)
                downloaded_file.rename(final_path)
                self.logger.info(f"Moved download to: {final_path}")
                downloaded_file = final_path

            # Store download info in results
            current_url = await self._get_current_url()
            result = ScrapingResult(
                url=current_url,
                content="",
                bs_soup=BeautifulSoup("", 'html.parser'),
                extracted_data={
                    "downloaded_file": str(downloaded_file),
                    "file_name": downloaded_file.name,
                    "file_size": downloaded_file.stat().st_size
                },
                metadata={
                    "download_path": str(download_dir),
                    "filename_pattern": action.filename_pattern,
                    "moved_to": action.move_to
                },
                timestamp=str(time.time()),
                success=True
            )
            self.results.append(result)

            # Delete file if requested
            if action.delete_after:
                downloaded_file.unlink()
                self.logger.info(f"Deleted file: {downloaded_file.name}")

            return True

        except Exception as e:
            self.logger.error(f"WaitForDownload action failed: {str(e)}")
            return False


    async def _upload_file(self, action: UploadFile) -> bool:
        """
        Upload a file to a file input element.

        Args:
            action: UploadFile action with file path and selector

        Returns:
            bool: True if upload successful
        """
        try:
            # Determine file paths
            if action.multiple_files and action.file_paths:
                file_paths = [Path(fp).resolve() for fp in action.file_paths]
            else:
                file_paths = [Path(action.file_path).resolve()]

            # Verify files exist
            for file_path in file_paths:
                if not file_path.exists():
                    self.logger.error(f"File not found: {file_path}")
                    return False

            self.logger.info(f"Uploading {len(file_paths)} file(s)")

            if self.driver_type == 'selenium':
                loop = asyncio.get_running_loop()

                def upload_sync():
                    # Find the file input element
                    file_input = WebDriverWait(
                        self.driver,
                        action.timeout or self.default_timeout
                    ).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, action.selector)
                        )
                    )

                    # Send file paths to input
                    if len(file_paths) == 1:
                        file_input.send_keys(str(file_paths[0]))
                    else:
                        # Multiple files - join with newline
                        file_input.send_keys('\n'.join(str(fp) for fp in file_paths))

                    self.logger.info("File(s) uploaded successfully")

                    # Wait for post-upload element if specified
                    if action.wait_after_upload:
                        try:
                            WebDriverWait(
                                self.driver,
                                action.wait_timeout
                            ).until(
                                EC.presence_of_element_located(
                                    (By.CSS_SELECTOR, action.wait_after_upload)
                                )
                            )
                            self.logger.info(
                                f"Post-upload element found: {action.wait_after_upload}"
                            )
                        except Exception as e:
                            self.logger.warning(
                                f"Post-upload wait timed out: {action.wait_after_upload}"
                            )

                await loop.run_in_executor(None, upload_sync)

            else:  # Playwright
                # For Playwright, set the files directly
                if len(file_paths) == 1:
                    await self.page.set_input_files(action.selector, str(file_paths[0]))
                else:
                    await self.page.set_input_files(
                        action.selector,
                        [str(fp) for fp in file_paths]
                    )

                self.logger.info("File(s) uploaded successfully")

                # Wait for post-upload element if specified
                if action.wait_after_upload:
                    try:
                        await self.page.wait_for_selector(
                            action.wait_after_upload,
                            timeout=action.wait_timeout * 1000
                        )
                        self.logger.info(
                            f"Post-upload element found: {action.wait_after_upload}"
                        )
                    except Exception:
                        self.logger.warning(
                            f"Post-upload wait timed out: {action.wait_after_upload}"
                        )

            # Store upload info in results
            current_url = await self._get_current_url()
            result = ScrapingResult(
                url=current_url,
                content="",
                bs_soup=BeautifulSoup("", 'html.parser'),
                extracted_data={
                    "uploaded_files": [fp.name for fp in file_paths],
                    "file_count": len(file_paths)
                },
                metadata={
                    "selector": action.selector,
                    "file_paths": [str(fp) for fp in file_paths],
                    "multiple_files": action.multiple_files
                },
                timestamp=str(time.time()),
                success=True
            )
            self.results.append(result)

            return True

        except Exception as e:
            self.logger.error(f"UploadFile action failed: {str(e)}")
            return False

    async def _exec_conditional(
        self,
        action: Conditional,
        base_url: str = "",
        args: Optional[dict] = None
    ) -> bool:
        """Handle Conditional action - execute actions based on a condition."""

        CONDITION_TYPES = {
            'exists': lambda element, expected: element is not None,
            'not_exists': lambda element, expected: element is None,
            'text_contains': lambda element, expected: expected in (element.text if element else ''),
            'text_equals': lambda element, expected: (element.text if element else '') == expected,
            'attribute_equals': lambda element, expected: element.get_attribute(expected['attr']) == expected['value'] if element else False,
        }

        target = action.target
        target_type = action.target_type or 'css'
        condition_type = action.condition_type
        expected_value = action.expected_value
        timeout = action.timeout or 5

        self.logger.info(
            f"Evaluating conditional: {condition_type} on {target_type}='{target}' with value '*{expected_value}*'"
        )

        # Find the element
        element = None
        if self.driver_type == 'selenium':
            loop = asyncio.get_running_loop()

            def find_element_sync():
                try:
                    # Determine locator type
                    if target_type == 'xpath':
                        by_type = By.XPATH
                    else:  # css
                        by_type = By.CSS_SELECTOR

                    # Try to find element with timeout
                    try:
                        el = WebDriverWait(
                            self.driver,
                            timeout,
                            poll_frequency=0.25
                        ).until(
                            EC.presence_of_element_located((by_type, target))
                        )
                        return el
                    except (TimeoutException, NoSuchElementException):
                        return None
                except Exception as e:
                    self.logger.debug(f"Error finding element: {str(e)}")
                    return None

            element = await loop.run_in_executor(None, find_element_sync)

        else:  # Playwright
            try:
                if target_type == 'xpath':
                    selector = f"xpath={target}"
                else:
                    selector = target

                element = await self.page.wait_for_selector(
                    selector,
                    timeout=timeout * 1000,
                    state='attached'
                )
            except Exception:
                element = None

        # Evaluate condition
        condition_func = CONDITION_TYPES.get(condition_type)
        if not condition_func:
            self.logger.error(f"Unknown condition type: {condition_type}")
            return False

        # For attribute_equals, expected_value should be a dict
        if condition_type == 'attribute_equals' and isinstance(expected_value, str):
            # Try to parse as "attr=value"
            if '=' in expected_value:
                attr, val = expected_value.split('=', 1)
                expected_value = {'attr': attr.strip(), 'value': val.strip()}

        try:
            condition_result = condition_func(element, expected_value)
        except Exception as e:
            self.logger.error(f"Error evaluating condition: {str(e)}")
            condition_result = False

        self.logger.notice(
            f"Condition result: {condition_result}"
        )

        # Determine which actions to execute
        actions_to_execute = (
            action.actions_if_true if condition_result
            else (action.actions_if_false or [])
        )

        if not actions_to_execute:
            self.logger.info(
                f"No actions to execute for condition result: {condition_result}"
            )
            return True

        self.logger.info(
            f"Executing {len(actions_to_execute)} action(s) based on condition result"
        )

        # Execute the actions
        all_success = True
        for sub_action in actions_to_execute:
            step = ScrapingStep(action=sub_action)
            success = await self._execute_step(step, base_url, args)

            if not success:
                self.logger.warning(
                    f"Conditional sub-action failed: {sub_action.description}"
                )
                all_success = False
                # Continue executing remaining actions even if one fails

        return all_success

    async def _exec_loop(self, action: Loop, base_url: str) -> bool:
        """Handle Loop action - execute actions repeatedly.

        Supports:
        - Fixed iterations
        - Iterating over a list of values
        - Template variable substitution

        Template Variables:
        - {i}, {index}, {iteration} - Current iteration number
        - {i+1} - 1-based iteration (useful for page numbers)
        - {i-1}, {i*2}, etc. - Arithmetic expressions
        - {value} - Current value from values list

        Example:
            Loop with iterations=3, start_index=1:
            - First iteration: {i} -> 1, {i+1} -> 2
            - Second iteration: {i} -> 2, {i+1} -> 3
            - Third iteration: {i} -> 3, {i+1} -> 4
        """
        iteration = 0
        start_index = action.start_index
        value_name = action.value_name

        if action.values:
            max_iter = len(action.values)
            self.logger.info(
                f"Starting loop over {max_iter} values, start_index={start_index}"
            )
        else:
            max_iter = action.iterations or action.max_iterations
            self.logger.info(
                f"Starting loop: {max_iter} iterations, start_index={start_index}"
            )

        while iteration < max_iter:
            display_index = start_index + iteration
            # Get current value if iterating over values
            current_value = action.values[iteration] if action.values else None

            # Check condition if provided
            if action.condition:
                should_continue = await self._evaluate_condition(action.condition)
                if not should_continue:
                    break

            # Execute all actions in the loop
            for loop_action in action.actions:
                # Substitute template variables in the action
                if action.do_replace:
                    sub_action = self._substitute_action_vars(
                        loop_action,
                        iteration,
                        start_index,
                        current_value
                    )
                else:
                    sub_action = loop_action

                step = ScrapingStep(action=sub_action)
                args = {
                    "iteration": iteration,
                    "data": {
                        "index": display_index,
                        value_name: current_value
                    }
                }
                success = await self._execute_step(step, base_url, args)

                if not success and action.break_on_error:
                    self.logger.warning(f"Loop stopped at iteration {iteration} due to error")
                    return False

            iteration += 1

            # Break if we've reached specified iterations
            if action.iterations and iteration >= action.iterations:
                break
            # do a small delay (random) between iterations
            await asyncio.sleep(random.uniform(0.1, 0.5))

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
        """
        Define the tool schema for LLM interaction.
        Provides comprehensive documentation of all available actions and their parameters.
        """
        return {
            "type": "function",
            "function": {
                "name": "web_scraping_tool",
                "description": """Execute automated web scraping with step-by-step navigation and content extraction.
    Supports navigation, interaction, authentication, content extraction, screenshots, file uploads, and download monitoring.
    Works with both Selenium and Playwright drivers.""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "steps": {
                            "type": "array",
                            "description": "List of navigation and interaction steps to execute in sequence",
                            "items": {
                                "type": "object",
                                "required": ["action"],
                                "properties": {
                                    "action": {
                                        "type": "string",
                                        "enum": [
                                            "navigate",
                                            "click",
                                            "fill",
                                            "evaluate",
                                            "press_key",
                                            "refresh",
                                            "back",
                                            "scroll",
                                            "get_cookies",
                                            "set_cookies",
                                            "wait",
                                            "authenticate",
                                            "await_human",
                                            "await_keypress",
                                            "await_browser_event",
                                            "loop",
                                            "get_text",
                                            "get_html",
                                            "screenshot",
                                            "wait_for_download",
                                            "upload_file"
                                        ],
                                        "description": "Type of action to perform"
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": "Human-readable description of what this action does"
                                    },
                                    "timeout": {
                                        "type": "integer",
                                        "description": "Maximum time to wait for action completion (seconds)"
                                    },

                                    # Navigate action
                                    "url": {
                                        "type": "string",
                                        "description": "URL to navigate to (for 'navigate' action)"
                                    },

                                    # Click action
                                    "selector": {
                                        "type": "string",
                                        "description": "CSS selector for element (for 'click', 'fill', 'get_text', 'get_html', 'screenshot', 'upload_file' actions)"
                                    },
                                    "click_type": {
                                        "type": "string",
                                        "enum": ["single", "double", "right"],
                                        "description": "Type of click (for 'click' action)"
                                    },
                                    "wait_after_click": {
                                        "type": "string",
                                        "description": "CSS selector of element to wait for after clicking (for 'click' action)"
                                    },
                                    "wait_timeout": {
                                        "type": "integer",
                                        "description": "Timeout for post-click wait in seconds (for 'click' action)"
                                    },
                                    "no_wait": {
                                        "type": "boolean",
                                        "description": "Skip waiting after click (for 'click' action)"
                                    },

                                    # Fill action
                                    "value": {
                                        "type": "string",
                                        "description": "Text value to enter (for 'fill' action)"
                                    },
                                    "clear_first": {
                                        "type": "boolean",
                                        "description": "Clear existing content before filling (for 'fill' action)"
                                    },
                                    "press_enter": {
                                        "type": "boolean",
                                        "description": "Press Enter after filling (for 'fill' action)"
                                    },

                                    # Evaluate action
                                    "script": {
                                        "type": "string",
                                        "description": "JavaScript code to execute (for 'evaluate' action)"
                                    },
                                    "script_file": {
                                        "type": "string",
                                        "description": "Path to JavaScript file to execute (for 'evaluate' action)"
                                    },
                                    "args": {
                                        "type": "array",
                                        "description": "Arguments to pass to script (for 'evaluate' action)",
                                        "items": {"type": "string"}
                                    },
                                    "return_value": {
                                        "type": "boolean",
                                        "description": "Whether to return script result (for 'evaluate' action)"
                                    },

                                    # PressKey action
                                    "keys": {
                                        "type": "array",
                                        "description": "Keys to press, e.g., ['Tab', 'Enter'] (for 'press_key' action)",
                                        "items": {"type": "string"}
                                    },
                                    "sequential": {
                                        "type": "boolean",
                                        "description": "Press keys sequentially vs as combination (for 'press_key' action)"
                                    },
                                    "target": {
                                        "type": "string",
                                        "description": "CSS selector to focus before pressing keys (for 'press_key' action)"
                                    },

                                    # Refresh action
                                    "hard": {
                                        "type": "boolean",
                                        "description": "Perform hard refresh clearing cache (for 'refresh' action)"
                                    },

                                    # Back action
                                    "steps": {
                                        "type": "integer",
                                        "description": "Number of steps to go back in history (for 'back' action)"
                                    },

                                    # Scroll action
                                    "direction": {
                                        "type": "string",
                                        "enum": ["up", "down", "top", "bottom"],
                                        "description": "Scroll direction (for 'scroll' action)"
                                    },
                                    "amount": {
                                        "type": "integer",
                                        "description": "Pixels to scroll (for 'scroll' action)"
                                    },
                                    "smooth": {
                                        "type": "boolean",
                                        "description": "Use smooth scrolling animation (for 'scroll' action)"
                                    },

                                    # GetCookies action
                                    "names": {
                                        "type": "array",
                                        "description": "Specific cookie names to retrieve (for 'get_cookies' action)",
                                        "items": {"type": "string"}
                                    },
                                    "domain": {
                                        "type": "string",
                                        "description": "Filter cookies by domain (for 'get_cookies' action)"
                                    },

                                    # SetCookies action
                                    "cookies": {
                                        "type": "array",
                                        "description": "List of cookie objects to set (for 'set_cookies' action)",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "name": {"type": "string"},
                                                "value": {"type": "string"},
                                                "domain": {"type": "string"},
                                                "path": {"type": "string"},
                                                "secure": {"type": "boolean"},
                                                "httpOnly": {"type": "boolean"}
                                            }
                                        }
                                    },

                                    # Wait action
                                    "condition": {
                                        "type": "string",
                                        "description": "Condition value - CSS selector, URL substring, etc. (for 'wait' action)"
                                    },
                                    "condition_type": {
                                        "type": "string",
                                        "enum": ["selector", "url_contains", "title_contains", "custom"],
                                        "description": "Type of condition to wait for (for 'wait' action)"
                                    },
                                    "custom_script": {
                                        "type": "string",
                                        "description": "JavaScript returning boolean for custom wait (for 'wait' action)"
                                    },

                                    # Authenticate action
                                    "method": {
                                        "type": "string",
                                        "enum": ["form", "basic", "oauth", "custom"],
                                        "description": "Authentication method (for 'authenticate' action)"
                                    },
                                    "username": {
                                        "type": "string",
                                        "description": "Username or email (for 'authenticate' action)"
                                    },
                                    "enter_on_username": {
                                        "type": "boolean",
                                        "description": "Press Enter after filling username (for multi-step logins, 'authenticate' action)"
                                    },
                                    "password": {
                                        "type": "string",
                                        "description": "Password (for 'authenticate' action)"
                                    },
                                    "username_selector": {
                                        "type": "string",
                                        "description": "CSS selector for username field (for 'authenticate' action)"
                                    },
                                    "password_selector": {
                                        "type": "string",
                                        "description": "CSS selector for password field (for 'authenticate' action)"
                                    },
                                    "submit_selector": {
                                        "type": "string",
                                        "description": "CSS selector for submit button (for 'authenticate' action)"
                                    },

                                    # AwaitHuman action
                                    "message": {
                                        "type": "string",
                                        "description": "Message to display while waiting (for 'await_human', 'await_keypress' actions)"
                                    },

                                    # AwaitKeyPress action
                                    "expected_key": {
                                        "type": "string",
                                        "description": "Specific key to wait for (for 'await_keypress' action)"
                                    },

                                    # AwaitBrowserEvent action
                                    "wait_condition": {
                                        "type": "object",
                                        "description": "Condition configuration for browser event (for 'await_browser_event' action)"
                                    },

                                    # Loop action
                                    "actions": {
                                        "type": "array",
                                        "description": "List of actions to repeat (for 'loop' action)",
                                        "items": {"type": "object"}
                                    },
                                    "iterations": {
                                        "type": "integer",
                                        "description": "Number of times to repeat (for 'loop' action)"
                                    },
                                    "break_on_error": {
                                        "type": "boolean",
                                        "description": "Stop loop if action fails (for 'loop' action)"
                                    },
                                    "max_iterations": {
                                        "type": "integer",
                                        "description": "Safety limit for condition-based loops (for 'loop' action)"
                                    },

                                    # GetText action
                                    "multiple": {
                                        "type": "boolean",
                                        "description": "Extract from all matching elements (for 'get_text', 'get_html' actions)"
                                    },
                                    "extract_name": {
                                        "type": "string",
                                        "description": "Name for extracted data in results (for 'get_text', 'get_html' actions)"
                                    },

                                    # Screenshot action
                                    "full_page": {
                                        "type": "boolean",
                                        "description": "Capture full scrollable page (for 'screenshot' action)"
                                    },
                                    "output_path": {
                                        "type": "string",
                                        "description": "File path to save screenshot (for 'screenshot' action)"
                                    },
                                    "return_base64": {
                                        "type": "boolean",
                                        "description": "Return screenshot as base64 (for 'screenshot' action)"
                                    },

                                    # WaitForDownload action
                                    "filename_pattern": {
                                        "type": "string",
                                        "description": "Filename pattern to match, e.g., '*.pdf' (for 'wait_for_download' action)"
                                    },
                                    "download_path": {
                                        "type": "string",
                                        "description": "Directory to monitor for downloads (for 'wait_for_download' action)"
                                    },
                                    "move_to": {
                                        "type": "string",
                                        "description": "Path to move downloaded file (for 'wait_for_download' action)"
                                    },
                                    "delete_after": {
                                        "type": "boolean",
                                        "description": "Delete file after detection (for 'wait_for_download' action)"
                                    },

                                    # UploadFile action
                                    "file_path": {
                                        "type": "string",
                                        "description": "Path to file to upload (for 'upload_file' action)"
                                    },
                                    "wait_after_upload": {
                                        "type": "string",
                                        "description": "CSS selector to wait for after upload (for 'upload_file' action)"
                                    },
                                    "multiple_files": {
                                        "type": "boolean",
                                        "description": "Whether uploading multiple files (for 'upload_file' action)"
                                    },
                                    "file_paths": {
                                        "type": "array",
                                        "description": "List of file paths for multiple uploads (for 'upload_file' action)",
                                        "items": {"type": "string"}
                                    }
                                }
                            }
                        },
                        "selectors": {
                            "type": "array",
                            "description": "Content selectors for extraction (legacy - prefer using get_text/get_html actions)",
                            "items": {
                                "type": "object",
                                "required": ["name", "selector"],
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "description": "Friendly name for the extracted content"
                                    },
                                    "selector": {
                                        "type": "string",
                                        "description": "CSS selector for the content"
                                    },
                                    "selector_type": {
                                        "type": "string",
                                        "enum": ["css", "xpath", "tag"],
                                        "description": "Type of selector"
                                    },
                                    "extract_type": {
                                        "type": "string",
                                        "enum": ["text", "html", "attribute"],
                                        "description": "What to extract from matched elements"
                                    },
                                    "attribute": {
                                        "type": "string",
                                        "description": "Attribute name (when extract_type is 'attribute')"
                                    },
                                    "multiple": {
                                        "type": "boolean",
                                        "description": "Extract from all matching elements"
                                    }
                                }
                            }
                        },
                        "base_url": {
                            "type": "string",
                            "description": "Base URL for resolving relative links"
                        },
                        "browser_config": {
                            "type": "object",
                            "description": "Browser configuration overrides",
                            "properties": {
                                "browser": {
                                    "type": "string",
                                    "enum": ["chrome", "firefox", "edge", "safari", "undetected"],
                                    "description": "Browser to use"
                                },
                                "headless": {
                                    "type": "boolean",
                                    "description": "Run browser in headless mode"
                                },
                                "mobile": {
                                    "type": "boolean",
                                    "description": "Emulate mobile device"
                                },
                                "mobile_device": {
                                    "type": "string",
                                    "description": "Specific mobile device to emulate"
                                }
                            }
                        }
                    },
                    "required": ["steps"]
                }
            }
        }

    def _substitute_template_vars(
        self,
        value: Any,
        iteration: int,
        start_index: int = 0,
        current_value: Any = None
    ) -> Any:
        """
        Recursively substitute template variables in strings.

        Supported variables:
        - {i}, {index}, {iteration} - Current iteration (0-based by default)
        - {i+1}, {index+1}, {iteration+1} - Current iteration + 1 (1-based)
        - {i-1}, {index-1} - Current iteration - 1
        - {value} - Current value from values list (if provided)
        - Any arithmetic expression: {i*2}, {i+5}, etc.

        Args:
            value: Value to substitute (can be str, dict, list, or other)
            iteration: Current iteration number (internal, 0-based counter)
            start_index: Starting index for display (default 0)
            current_value: Current value from the values list (if iterating over values)

        Returns:
            Value with substituted variables
        """
        if isinstance(value, str):
            # Actual index to expose to user (respects start_index)
            actual_index = start_index + iteration

            # Replace simple variables first
            value = value.replace('{i}', str(actual_index))
            value = value.replace('{index}', str(actual_index))
            value = value.replace('{iteration}', str(actual_index))

            # Replace {value} with current value from list
            if current_value is not None:
                value = value.replace('{value}', str(current_value))

            # Handle arithmetic expressions like {i+1}, {i-1}, {i*2}, etc.
            def eval_expr(match):
                expr = match.group(1)
                # Replace variable names with actual value
                expr = expr.replace('i', str(actual_index))
                expr = expr.replace('index', str(actual_index))
                expr = expr.replace('iteration', str(actual_index))
                try:
                    # Safe evaluation of arithmetic
                    result = eval(expr, {"__builtins__": {}}, {})
                    return str(result)
                except:
                    # If evaluation fails, return original
                    return match.group(0)

            # Pattern to match {expression} where expression contains i/index/iteration
            pattern = r'\{([^}]*(?:i|index|iteration)[^}]*)\}'
            value = re.sub(pattern, eval_expr, value)

            return value

        elif isinstance(value, dict):
            return {k: self._substitute_template_vars(v, iteration, start_index, current_value) for k, v in value.items()}

        elif isinstance(value, list):
            return [self._substitute_template_vars(item, iteration, start_index, current_value) for item in value]
        else:
            # Return as-is for other types (int, bool, None, etc.)
            return value

    def _substitute_action_vars(
        self,
        action: BrowserAction,
        iteration: int,
        start_index: int = 0,
        current_value: Any = None
    ) -> BrowserAction:
        """
        Create a copy of the action with template variables substituted.

        Args:
            action: Original action
            iteration: Current iteration number (0-based internally)
            start_index: Starting index for display
            current_value: Current value from values list (if provided)

        Returns:
            New action instance with substituted values
        """
        # Get the action as a dictionary
        action_dict = action.model_dump()

        # Substitute variables in all string fields
        substituted_dict = self._substitute_template_vars(
            action_dict,
            iteration,
            start_index,
            current_value
        )

        # Create new action instance from substituted dict
        action_class = type(action)
        return action_class(**substituted_dict)

    def _collect_cookies(self) -> Dict[str, str]:
        if not self.driver:
            raise RuntimeError(
                "Selenium driver not available after scraping flow"
            )
        cookies: Dict[str, str] = {}
        with contextlib.suppress(Exception):
            cookies = self.driver.execute_cdp_cmd("Network.getAllCookies", {})["cookies"]
        if not cookies:
            for cookie in self.driver.get_cookies():
                name = cookie.get("name")
                if name:
                    cookies[name] = cookie.get("value", "")
        return cookies

    def _extract_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if not self.driver:
            return headers

        # for Selenium Wire, this path:
        try:
            for req in self.driver.requests:
                for key, value in req.headers.items():
                    headers[key] = value
            return headers
        except Exception:
            pass

        try:
            performance_logs = self.driver.get_log("performance")
        except Exception:
            performance_logs = []

        for entry in reversed(performance_logs):
            try:
                message = json.loads(entry.get("message", "{}"))
                log = message.get("message", {})
                if log.get("method") != "Network.requestWillBeSent":
                    continue
                req_headers = log.get("params", {}).get("request", {}).get("headers", {})
                for key, value in req_headers.items():
                    if key not in headers:
                        headers[key] = value
            except (ValueError, TypeError):
                continue

        return headers

    def _extract_authorization(self) -> Optional[str]:
        if not self.driver:
            return None

        # Check first if Authorization is in headers:
        if 'Authorization' in self.extracted_headers:
            return self.extracted_headers['Authorization']
        if 'authorization' in self.extracted_headers:
            return self.extracted_headers['authorization']

        # Attempt to capture from performance logs first
        try:
            self.driver.execute_cdp_cmd("Network.enable", {})
        except Exception:  # pragma: no cover - command may not exist
            pass

        try:
            performance_logs = self.driver.get_log("performance")
        except Exception:
            performance_logs = []

        for entry in reversed(performance_logs):
            try:
                message = json.loads(entry.get("message", "{}"))
                log = message.get("message", {})
                if log.get("method") != "Network.requestWillBeSent":
                    continue
                headers = log.get("params", {}).get("request", {}).get("headers", {})
                authorization = headers.get("Authorization") or headers.get("authorization")
                if authorization:
                    return authorization
            except (ValueError, TypeError):
                continue

        # Fallback: check localStorage/sessionStorage for tokens
        script_templates = [
            "return window.sessionStorage.getItem('authorization');",
            "return window.localStorage.getItem('authorization');",
            "return window.sessionStorage.getItem('authToken');",
            "return window.localStorage.getItem('authToken');",
            "return window.localStorage.getItem('token');",
        ]
        for script in script_templates:
            try:
                token = self.driver.execute_script(script)
            except Exception:
                token = None
            if token:
                if not token.lower().startswith("bearer"):
                    token = f"Bearer {token}".strip()
                return token

        return None
