"""
Step Executor — standalone scraping plan execution.

Extracts the step-execution pipeline from ``WebScrapingTool._execute`` into a
reusable async function. Both ``WebScrapingToolkit.scrape()`` and ``CrawlEngine``
can share this execution logic without duplication.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .models import (
    ScrapingResult,
    ScrapingSelector,
    ScrapingStep,
)
from .plan import ScrapingPlan
from .toolkit_models import DriverConfig

logger = logging.getLogger(__name__)

# Default settings when no DriverConfig is provided.
_DEFAULT_DELAY = 1.0
_DEFAULT_TIMEOUT = 10


async def execute_plan_steps(
    driver: Any,
    plan: Optional[ScrapingPlan] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    selectors: Optional[List[Dict[str, Any]]] = None,
    config: Optional[DriverConfig] = None,
    base_url: Optional[str] = None,
) -> ScrapingResult:
    """Execute a scraping plan's steps against a browser driver.

    Accepts either a full ``ScrapingPlan`` or a raw ``steps`` list for ad-hoc
    usage.  Steps are executed sequentially; selectors are applied after all
    steps complete.

    Args:
        driver: Browser driver instance (e.g. Selenium ``WebDriver``).
        plan: Full ``ScrapingPlan`` (takes priority if provided).
        steps: Raw steps list for ad-hoc usage (used when *plan* is ``None``).
        selectors: Content extraction selectors (used when *plan* is ``None``).
        config: Driver configuration for delay/timeout settings.
        base_url: Fallback base URL for relative link resolution.

    Returns:
        ``ScrapingResult`` with extracted data and metadata.
    """
    cfg = config or DriverConfig()
    delay = cfg.delay_between_actions if cfg.delay_between_actions is not None else _DEFAULT_DELAY
    timeout = cfg.default_timeout if cfg.default_timeout is not None else _DEFAULT_TIMEOUT

    # ── Resolve inputs from plan or raw args ──────────────────────────
    if plan is not None:
        raw_steps = plan.steps or []
        raw_selectors = plan.selectors
        url = plan.url or base_url or ""
    else:
        raw_steps = steps or []
        raw_selectors = selectors
        url = base_url or ""

    # ── Convert dicts → ScrapingStep / ScrapingSelector ───────────────
    scraping_steps: List[ScrapingStep] = []
    for raw in raw_steps:
        if isinstance(raw, dict):
            scraping_steps.append(ScrapingStep.from_dict(raw))
        else:
            scraping_steps.append(raw)

    scraping_selectors: Optional[List[ScrapingSelector]] = None
    if raw_selectors:
        scraping_selectors = [
            ScrapingSelector(**sel) if isinstance(sel, dict) else sel
            for sel in raw_selectors
        ]

    # ── Execute steps ─────────────────────────────────────────────────
    step_errors: List[Dict[str, Any]] = []
    aborted = False

    for idx, step in enumerate(scraping_steps):
        step_desc = step.description or step.action.get_action_type()
        logger.info("Executing step %d/%d: %s", idx + 1, len(scraping_steps), step_desc)

        try:
            success = await _dispatch_step(driver, step, url, timeout)
        except Exception as exc:
            logger.error("Step %d failed: %s — %s", idx + 1, step_desc, exc)
            step_errors.append({
                "step_index": idx,
                "action": step.action.get_action_type(),
                "error": str(exc),
            })
            # Critical actions abort the remaining plan
            action_type = step.action.get_action_type()
            if action_type in ("navigate", "authenticate"):
                aborted = True
                break
            continue

        if not success:
            logger.warning("Step %d returned failure: %s", idx + 1, step_desc)
            step_errors.append({
                "step_index": idx,
                "action": step.action.get_action_type(),
                "error": "step returned False",
            })
            action_type = step.action.get_action_type()
            if action_type in ("navigate", "authenticate"):
                aborted = True
                break

        # Inter-step delay
        if delay > 0 and idx < len(scraping_steps) - 1:
            await asyncio.sleep(delay)

    # ── Extract content ───────────────────────────────────────────────
    try:
        current_url = await _get_current_url(driver)
        page_source = await _get_page_source(driver)
    except Exception as exc:
        logger.error("Failed to retrieve page source: %s", exc)
        return ScrapingResult(
            url=url,
            content="",
            bs_soup=BeautifulSoup("", "html.parser"),
            success=False,
            error_message=f"Failed to retrieve page after step execution: {exc}",
            metadata={"step_errors": step_errors},
        )

    soup = BeautifulSoup(page_source, "html.parser")

    extracted_data: Dict[str, Any] = {}
    if scraping_selectors:
        extracted_data = _apply_selectors(soup, scraping_selectors)

    # ── Build result ──────────────────────────────────────────────────
    has_errors = bool(step_errors)
    success = not aborted

    return ScrapingResult(
        url=current_url or url,
        content=page_source,
        bs_soup=soup,
        extracted_data=extracted_data,
        metadata={
            "total_steps": len(scraping_steps),
            "executed_steps": len(scraping_steps) - (1 if aborted else 0),
            "step_errors": step_errors,
            "had_failures": has_errors,
            "aborted": aborted,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        success=success,
        error_message=(
            f"{len(step_errors)} step(s) failed"
            if has_errors else None
        ),
    )


# ═══════════════════════════════════════════════════════════════════════
# Action dispatch
# ═══════════════════════════════════════════════════════════════════════

async def _dispatch_step(
    driver: Any,
    step: ScrapingStep,
    base_url: str,
    timeout: int,
) -> bool:
    """Dispatch a single ``ScrapingStep`` to the appropriate action handler.

    Args:
        driver: Browser driver instance.
        step: Parsed scraping step.
        base_url: Base URL for resolving relative URLs.
        timeout: Default timeout in seconds.

    Returns:
        ``True`` if the step succeeded.
    """
    action = step.action
    action_type = action.get_action_type()
    loop = asyncio.get_running_loop()

    if action_type == "navigate":
        return await _action_navigate(driver, action, base_url, loop)
    elif action_type == "wait":
        return await _action_wait(driver, action, timeout, loop)
    elif action_type == "click":
        return await _action_click(driver, action, timeout, loop)
    elif action_type == "fill":
        return await _action_fill(driver, action, timeout, loop)
    elif action_type == "scroll":
        return await _action_scroll(driver, action, loop)
    elif action_type == "evaluate":
        return await _action_evaluate(driver, action, loop)
    elif action_type == "refresh":
        return await _action_refresh(driver, action, loop)
    elif action_type == "back":
        return await _action_back(driver, action, loop)
    elif action_type == "get_text":
        return await _action_get_text(driver, action, loop)
    elif action_type == "get_html":
        return await _action_get_html(driver, action, loop)
    elif action_type == "screenshot":
        return await _action_screenshot(driver, action, loop)
    elif action_type == "press_key":
        return await _action_press_key(driver, action, loop)
    elif action_type == "select":
        return await _action_select(driver, action, timeout, loop)
    elif action_type in (
        "get_cookies", "set_cookies", "authenticate",
        "await_human", "await_keypress", "await_browser_event",
        "upload_file", "wait_for_download", "loop", "conditional",
    ):
        # These advanced actions require the full WebScrapingTool context.
        # Log a warning and return True to not block the pipeline.
        logger.warning(
            "Action '%s' requires the full WebScrapingTool; "
            "skipping in standalone executor.",
            action_type,
        )
        return True
    else:
        logger.warning("Unknown action type: %s", action_type)
        return False


# ── Individual action handlers ────────────────────────────────────────

async def _action_navigate(driver: Any, action: Any, base_url: str, loop: asyncio.AbstractEventLoop) -> bool:
    """Navigate to a URL."""
    target = urljoin(base_url, action.url) if base_url else action.url
    await loop.run_in_executor(None, driver.get, target)
    return True


async def _action_wait(driver: Any, action: Any, default_timeout: int, loop: asyncio.AbstractEventLoop) -> bool:
    """Wait for a condition."""
    wait_timeout = action.timeout or default_timeout
    condition_type = getattr(action, "condition_type", "simple")
    condition = getattr(action, "condition", None)

    if condition_type == "simple" or condition is None:
        await asyncio.sleep(wait_timeout)
        return True

    if condition_type == "selector":
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        def wait_sync():
            WebDriverWait(driver, wait_timeout, poll_frequency=0.25).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, condition))
            )

        await loop.run_in_executor(None, wait_sync)
        return True

    if condition_type == "url_contains":
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        def wait_url():
            WebDriverWait(driver, wait_timeout, poll_frequency=0.25).until(
                EC.url_contains(condition)
            )

        await loop.run_in_executor(None, wait_url)
        return True

    if condition_type == "title_contains":
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        def wait_title():
            WebDriverWait(driver, wait_timeout, poll_frequency=0.25).until(
                EC.title_contains(condition)
            )

        await loop.run_in_executor(None, wait_title)
        return True

    # Fallback: simple sleep
    await asyncio.sleep(wait_timeout)
    return True


async def _action_click(driver: Any, action: Any, default_timeout: int, loop: asyncio.AbstractEventLoop) -> bool:
    """Click an element."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    selector = action.selector
    selector_type = getattr(action, "selector_type", "css")
    timeout = action.timeout or default_timeout

    def click_sync():
        if selector_type == "xpath":
            by_type = By.XPATH
            locator = selector
        elif selector_type == "text":
            by_type = By.XPATH
            locator = f"//*[contains(text(), '{selector}')]"
        else:
            by_type = By.CSS_SELECTOR
            locator = selector

        wait = WebDriverWait(driver, timeout, poll_frequency=0.25)
        element = wait.until(EC.presence_of_element_located((by_type, locator)))
        try:
            element = wait.until(EC.element_to_be_clickable((by_type, locator)))
            element.click()
        except Exception:
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'}); arguments[0].click();",
                element,
            )
        return True

    await loop.run_in_executor(None, click_sync)
    return True


async def _action_fill(driver: Any, action: Any, default_timeout: int, loop: asyncio.AbstractEventLoop) -> bool:
    """Fill an input field."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    selector = action.selector
    value = action.value
    timeout = action.timeout or default_timeout

    def fill_sync():
        wait = WebDriverWait(driver, timeout, poll_frequency=0.25)
        element = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
        )
        if getattr(action, "clear_first", True):
            element.clear()
        element.send_keys(value)
        if getattr(action, "press_enter", False):
            element.send_keys(Keys.ENTER)
        return True

    await loop.run_in_executor(None, fill_sync)
    return True


async def _action_scroll(driver: Any, action: Any, loop: asyncio.AbstractEventLoop) -> bool:
    """Scroll the page."""
    direction = action.direction
    amount = getattr(action, "amount", None)

    if direction == "top":
        script = "window.scrollTo(0, 0);"
    elif direction == "bottom":
        script = "window.scrollTo(0, document.body.scrollHeight);"
    elif direction == "down":
        pixels = amount or 500
        script = f"window.scrollBy(0, {pixels});"
    elif direction == "up":
        pixels = amount or 500
        script = f"window.scrollBy(0, -{pixels});"
    else:
        return False

    await loop.run_in_executor(None, driver.execute_script, script)
    return True


async def _action_evaluate(driver: Any, action: Any, loop: asyncio.AbstractEventLoop) -> bool:
    """Execute JavaScript."""
    script = action.script
    if not script and hasattr(action, "script_file") and action.script_file:
        with open(action.script_file) as f:
            script = f.read()
    if not script:
        logger.warning("No script provided for evaluate action")
        return False

    await loop.run_in_executor(None, driver.execute_script, script)
    return True


async def _action_refresh(driver: Any, action: Any, loop: asyncio.AbstractEventLoop) -> bool:
    """Refresh the page."""
    hard = getattr(action, "hard", False)
    if hard:
        await loop.run_in_executor(
            None, driver.execute_script, "location.reload(true)"
        )
    else:
        await loop.run_in_executor(None, driver.refresh)
    return True


async def _action_back(driver: Any, action: Any, loop: asyncio.AbstractEventLoop) -> bool:
    """Navigate back."""
    for _ in range(getattr(action, "steps", 1)):
        await loop.run_in_executor(None, driver.back)
    return True


async def _action_get_text(driver: Any, action: Any, loop: asyncio.AbstractEventLoop) -> bool:
    """Extract text from elements (result stored in driver-side, captured via page_source)."""
    # The text extraction happens via selectors in _apply_selectors; this action
    # is a no-op in the standalone executor — content is captured at the end.
    return True


async def _action_get_html(driver: Any, action: Any, loop: asyncio.AbstractEventLoop) -> bool:
    """Extract HTML from elements (captured via page_source)."""
    return True


async def _action_screenshot(driver: Any, action: Any, loop: asyncio.AbstractEventLoop) -> bool:
    """Take a screenshot."""
    output_path = getattr(action, "output_path", None) or "."
    filename = action.get_filename() if hasattr(action, "get_filename") else f"screenshot_{int(time.time())}.png"
    full_path = f"{output_path}/{filename}"

    def screenshot_sync():
        driver.save_screenshot(full_path)

    await loop.run_in_executor(None, screenshot_sync)
    logger.info("Screenshot saved: %s", full_path)
    return True


async def _action_press_key(driver: Any, action: Any, loop: asyncio.AbstractEventLoop) -> bool:
    """Press keyboard keys."""
    from selenium.webdriver.common.keys import Keys

    def press_sync():
        for key in action.keys:
            key_obj = getattr(Keys, key.upper(), key)
            driver.switch_to.active_element.send_keys(key_obj)

    await loop.run_in_executor(None, press_sync)
    return True


async def _action_select(driver: Any, action: Any, default_timeout: int, loop: asyncio.AbstractEventLoop) -> bool:
    """Select from dropdown."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select, WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    selector = action.selector
    timeout = action.timeout or default_timeout

    def select_sync():
        wait = WebDriverWait(driver, timeout, poll_frequency=0.25)
        element = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
        )
        sel = Select(element)
        by = getattr(action, "by", "value")
        if by == "value" and action.value:
            sel.select_by_value(action.value)
        elif by == "text" and action.text:
            sel.select_by_visible_text(action.text)
        elif by == "index" and action.index is not None:
            sel.select_by_index(action.index)

    await loop.run_in_executor(None, select_sync)
    return True


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

async def _get_current_url(driver: Any) -> str:
    """Get the current URL from the driver."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: driver.current_url)


async def _get_page_source(driver: Any) -> str:
    """Get the page source from the driver."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: driver.page_source)


def _apply_selectors(
    soup: BeautifulSoup,
    selectors: List[ScrapingSelector],
) -> Dict[str, Any]:
    """Apply extraction selectors to a parsed page.

    Args:
        soup: Parsed ``BeautifulSoup`` object.
        selectors: List of extraction selectors.

    Returns:
        Dictionary mapping selector names to extracted values.
    """
    extracted: Dict[str, Any] = {}
    for sel in selectors:
        try:
            if sel.selector_type == "css":
                elements = soup.select(sel.selector)
            elif sel.selector_type == "xpath":
                # BeautifulSoup doesn't support XPath natively; try lxml
                try:
                    from lxml import etree

                    tree = etree.HTML(str(soup))
                    elements_xml = tree.xpath(sel.selector)
                    # Convert lxml elements to text
                    if sel.extract_type == "text":
                        texts = [
                            el.text_content() if hasattr(el, "text_content") else str(el)
                            for el in elements_xml
                        ]
                        extracted[sel.name] = texts if sel.multiple else (texts[0] if texts else "")
                    elif sel.extract_type == "html":
                        htmls = [
                            etree.tostring(el, encoding="unicode")
                            if hasattr(el, "tag") else str(el)
                            for el in elements_xml
                        ]
                        extracted[sel.name] = htmls if sel.multiple else (htmls[0] if htmls else "")
                    elif sel.extract_type == "attribute" and sel.attribute:
                        vals = [
                            el.get(sel.attribute, "")
                            if hasattr(el, "get") else ""
                            for el in elements_xml
                        ]
                        extracted[sel.name] = vals if sel.multiple else (vals[0] if vals else "")
                    continue
                except ImportError:
                    logger.warning("lxml not available for XPath selector: %s", sel.name)
                    extracted[sel.name] = None
                    continue
            elif sel.selector_type == "tag":
                elements = soup.find_all(sel.selector)
            else:
                elements = []

            if sel.extract_type == "text":
                texts = [el.get_text(strip=True) for el in elements]
                extracted[sel.name] = texts if sel.multiple else (texts[0] if texts else "")
            elif sel.extract_type == "html":
                htmls = [str(el) for el in elements]
                extracted[sel.name] = htmls if sel.multiple else (htmls[0] if htmls else "")
            elif sel.extract_type == "attribute" and sel.attribute:
                vals = [el.get(sel.attribute, "") for el in elements]
                extracted[sel.name] = vals if sel.multiple else (vals[0] if vals else "")
            else:
                extracted[sel.name] = None
        except Exception as exc:
            logger.error("Selector '%s' failed: %s", sel.name, exc)
            extracted[sel.name] = None

    return extracted
