"""
Step Executor — standalone scraping plan execution.

Extracts the step-execution pipeline from ``WebScrapingTool._execute`` into a
reusable async function. Both ``WebScrapingToolkit.scrape()`` and ``CrawlEngine``
can share this execution logic without duplication.

All driver interactions use the ``AbstractDriver`` interface exclusively;
no Selenium-specific imports live in this module.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .drivers.abstract import AbstractDriver
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
    driver: AbstractDriver,
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
        driver: Browser driver instance implementing ``AbstractDriver``.
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
    # Populated by in-step ``extract`` actions. Merged into the final
    # ``extracted_data`` alongside top-level selector results.
    step_extracted: Dict[str, Any] = {}

    for idx, step in enumerate(scraping_steps):
        step_desc = step.description or step.action.get_action_type()
        logger.info("Executing step %d/%d: %s", idx + 1, len(scraping_steps), step_desc)

        try:
            success = await _dispatch_step(driver, step, url, timeout, step_extracted)
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

    extracted_data: Dict[str, Any] = dict(step_extracted)
    if scraping_selectors:
        selector_data = _apply_selectors(soup, scraping_selectors)
        # Step-level extracts win on key collision — they ran earlier
        # against possibly different DOM state (between clicks/scrolls).
        for k, v in selector_data.items():
            extracted_data.setdefault(k, v)

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
# Private async polling helper
# ═══════════════════════════════════════════════════════════════════════

async def _wait_until(predicate: Any, timeout: int, poll: float = 0.25) -> None:
    """Poll *predicate* until it returns ``True`` or the timeout elapses.

    *predicate* may be a plain callable or a coroutine function; both are
    supported.  Raises ``asyncio.TimeoutError`` if the condition is never
    met within *timeout* seconds.

    Args:
        predicate: Callable (sync or async) returning truthy when done.
        timeout: Maximum polling duration in seconds.
        poll: Poll interval in seconds (default 0.25, matching the old
            ``WebDriverWait(poll_frequency=0.25)`` behaviour).

    Raises:
        asyncio.TimeoutError: When the timeout elapses without success.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        result = predicate()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return
        if asyncio.get_event_loop().time() >= deadline:
            raise asyncio.TimeoutError(
                f"_wait_until timed out after {timeout}s"
            )
        await asyncio.sleep(poll)


# ═══════════════════════════════════════════════════════════════════════
# Action dispatch
# ═══════════════════════════════════════════════════════════════════════

async def _dispatch_step(
    driver: AbstractDriver,
    step: ScrapingStep,
    base_url: str,
    timeout: int,
    step_extracted: Dict[str, Any],
) -> bool:
    """Dispatch a single ``ScrapingStep`` to the appropriate action handler.

    Args:
        driver: Browser driver instance implementing ``AbstractDriver``.
        step: Parsed scraping step.
        base_url: Base URL for resolving relative URLs.
        timeout: Default timeout in seconds.
        step_extracted: Shared dict collecting results from ``extract`` steps.

    Returns:
        ``True`` if the step succeeded.
    """
    action = step.action
    action_type = action.get_action_type()

    if action_type == "navigate":
        return await _action_navigate(driver, action, base_url)
    elif action_type == "wait":
        return await _action_wait(driver, action, timeout)
    elif action_type == "click":
        return await _action_click(driver, action, timeout)
    elif action_type == "fill":
        return await _action_fill(driver, action, timeout)
    elif action_type == "scroll":
        return await _action_scroll(driver, action)
    elif action_type == "evaluate":
        return await _action_evaluate(driver, action)
    elif action_type == "refresh":
        return await _action_refresh(driver, action)
    elif action_type == "back":
        return await _action_back(driver, action)
    elif action_type == "extract":
        return await _action_extract(driver, action, step, step_extracted)
    elif action_type == "get_text":
        return await _action_get_text(driver, action)
    elif action_type == "get_html":
        return await _action_get_html(driver, action)
    elif action_type == "screenshot":
        return await _action_screenshot(driver, action)
    elif action_type == "press_key":
        return await _action_press_key(driver, action)
    elif action_type == "select":
        return await _action_select(driver, action, timeout)
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

async def _action_navigate(
    driver: AbstractDriver, action: Any, base_url: str
) -> bool:
    """Navigate to a URL."""
    target = urljoin(base_url, action.url) if base_url else action.url
    timeout = getattr(action, "timeout", None) or 30
    await driver.navigate(target, timeout=timeout)
    return True


async def _action_wait(
    driver: AbstractDriver, action: Any, default_timeout: int
) -> bool:
    """Wait for a condition."""
    wait_timeout = action.timeout or default_timeout
    condition_type = getattr(action, "condition_type", "simple")
    condition = getattr(action, "condition", None)

    if condition_type == "simple" or condition is None:
        await asyncio.sleep(wait_timeout)
        return True

    if condition_type == "selector":
        native_css = _strip_soup_only_pseudos(condition)
        if native_css != condition:
            logger.warning(
                "wait selector %r contains BeautifulSoup-only pseudo-classes "
                "(:contains / :-soup-contains / :has) that the native "
                "CSS engine doesn't support; waiting on the stripped form %r "
                "instead. To wait on text, anchor on a nearby id/class.",
                condition, native_css,
            )
        if not native_css.strip():
            logger.warning(
                "wait selector %r reduced to empty after stripping; "
                "falling back to plain sleep(%ds).",
                condition, wait_timeout,
            )
            await asyncio.sleep(wait_timeout)
            return True

        await driver.wait_for_selector(native_css, timeout=wait_timeout, state="attached")
        return True

    if condition_type == "url_contains":
        await _wait_until(
            lambda: condition in driver.current_url,
            timeout=wait_timeout,
        )
        return True

    if condition_type == "title_contains":
        async def _title_contains() -> bool:
            title = await driver.evaluate("document.title")
            return condition in str(title)

        await _wait_until(_title_contains, timeout=wait_timeout)
        return True

    # Fallback: simple sleep
    await asyncio.sleep(wait_timeout)
    return True


async def _action_click(
    driver: AbstractDriver, action: Any, default_timeout: int
) -> bool:
    """Click an element.

    Handles the ``:-soup-contains`` text filter by falling back to a JS
    dispatch when a CSS text-contains pseudo-class is present, preserving
    the CSS specificity prefix.
    """
    selector = action.selector
    selector_type = getattr(action, "selector_type", "css")
    timeout = action.timeout or default_timeout

    js_text_filter: Optional[str] = None
    if selector_type == "css" and selector:
        m = _SOUP_CONTAINS_TEXT_RE.search(selector)
        if m:
            js_text_filter = m.group(1)
            css_prefix = selector[:m.start()].rstrip() or "*"
            css_prefix = _strip_soup_only_pseudos(css_prefix) or "*"
            logger.warning(
                "click selector %r uses text-contains; running as CSS "
                "%r + JS textContent filter for %r",
                selector, css_prefix, js_text_filter,
            )
            selector = css_prefix
        else:
            stripped = _strip_soup_only_pseudos(selector)
            if stripped != selector:
                logger.warning(
                    "click selector %r contains BS4-only pseudo-classes; "
                    "stripped to %r for CSS.",
                    selector, stripped,
                )
                selector = stripped
            if not selector.strip():
                logger.warning("click selector reduced to empty; skipping step")
                return False

    if js_text_filter is not None:
        # CSS prefix + JS text match — preserves specificity. Uses
        # dispatchEvent so React's synthetic-event system catches it.
        script = (
            "const els = document.querySelectorAll(arguments[0]);"
            " const needle = arguments[1].toLowerCase();"
            " for (const el of els) {"
            "   if ((el.textContent || '').toLowerCase().includes(needle)) {"
            "     el.scrollIntoView({block:'center'});"
            "     el.dispatchEvent(new MouseEvent('click', "
            "       {bubbles: true, cancelable: true, view: window}));"
            "     return true;"
            "   }"
            " }"
            " return false;"
        )
        hit = await driver.execute_script(script, selector, js_text_filter)
        if not hit:
            raise RuntimeError(
                f"No element matching CSS {selector!r} contained text "
                f"{js_text_filter!r}"
            )
        return True

    if selector_type == "xpath":
        locator = selector
    elif selector_type == "text":
        locator = f"//*[contains(text(), '{selector}')]"
    else:
        locator = selector

    await driver.click(locator, timeout)
    return True


async def _action_fill(
    driver: AbstractDriver, action: Any, default_timeout: int
) -> bool:
    """Fill an input field."""
    selector = action.selector
    value = action.value
    timeout = action.timeout or default_timeout

    await driver.fill(selector, value, timeout)
    if getattr(action, "press_enter", False):
        await driver.press_key("Enter")
    return True


async def _action_scroll(driver: AbstractDriver, action: Any) -> bool:
    """Scroll the page.

    For ``direction='bottom'`` we scroll in chunks with short pauses
    between steps so intersection-observer-driven lazy loads (FAQ
    accordions, image carousels, infinite lists) actually fire.
    """
    direction = action.direction
    amount = getattr(action, "amount", None)

    if direction == "top":
        await driver.execute_script("window.scrollTo(0, 0);")
        return True

    if direction == "bottom":
        height_script = (
            "return Math.max(document.body.scrollHeight,"
            " document.documentElement.scrollHeight);"
        )
        height = int(await driver.execute_script(height_script) or 0)
        if height <= 0:
            return True
        chunks = 6
        for i in range(1, chunks + 1):
            y = min(height * i // chunks, height)
            await driver.execute_script(f"window.scrollTo(0, {y});")
            await asyncio.sleep(0.4)
            new_height = int(await driver.execute_script(height_script) or 0)
            height = max(height, new_height)
        return True

    if direction == "down":
        pixels = amount or 500
        script = f"window.scrollBy(0, {pixels});"
    elif direction == "up":
        pixels = amount or 500
        script = f"window.scrollBy(0, -{pixels});"
    else:
        return False

    await driver.execute_script(script)
    return True


async def _action_evaluate(driver: AbstractDriver, action: Any) -> bool:
    """Execute JavaScript."""
    script = action.script
    if not script and hasattr(action, "script_file") and action.script_file:
        with open(action.script_file) as f:
            script = f.read()
    if not script:
        logger.warning("No script provided for evaluate action")
        return False

    await driver.execute_script(script)
    return True


async def _action_refresh(driver: AbstractDriver, action: Any) -> bool:
    """Refresh the page.

    When ``hard=True``, falls back to a JS ``location.reload(true)`` call
    for Selenium parity (forced reload bypassing cache).
    """
    hard = getattr(action, "hard", False)
    if hard:
        await driver.execute_script("location.reload(true)")
    else:
        await driver.reload()
    return True


async def _action_back(driver: AbstractDriver, action: Any) -> bool:
    """Navigate back."""
    for _ in range(getattr(action, "steps", 1)):
        await driver.go_back()
    return True


async def _action_get_text(driver: AbstractDriver, action: Any) -> bool:
    """Extract text (result captured via page_source at end)."""
    return True


async def _action_get_html(driver: AbstractDriver, action: Any) -> bool:
    """Extract HTML (captured via page_source at end)."""
    return True


async def _action_extract(
    driver: AbstractDriver,
    action: Any,
    step: ScrapingStep,
    step_extracted: Dict[str, Any],
) -> bool:
    """Run an ``extract`` step against the current DOM.

    Captures ``driver.get_page_source()`` at the step's position in the plan
    so data that only exists after intermediate ``click`` / ``scroll`` / JS
    mutations is preserved.
    """
    html = await driver.get_page_source()
    soup = BeautifulSoup(html, "html.parser")

    key = (
        getattr(action, "extract_name", "")
        or getattr(action, "name", "")
        or step.description
        or "extracted_data"
    )
    if key == "extract":
        key = "extracted_data"

    selector = _normalize_bs4_selector(action.selector)
    multiple = getattr(action, "multiple", False)
    fields = getattr(action, "fields", None)

    try:
        rows = soup.select(selector)
    except Exception as exc:
        logger.warning("Extract selector %r invalid: %s", selector, exc)
        step_extracted[key] = [] if multiple else None
        return True

    if not rows:
        logger.info("Extract %r: no elements matched selector %r", key, selector)
        step_extracted[key] = [] if multiple else None
        return True

    target_rows = rows if multiple else rows[:1]

    if fields:
        records: List[Dict[str, Any]] = []
        for row in target_rows:
            record: Dict[str, Any] = {}
            for field_name, spec in fields.items():
                record[field_name] = _apply_field(row, spec)
            records.append(record)
        new_value: Any = records if multiple else (records[0] if records else None)
    else:
        values = [_extract_node_value(el, action) for el in target_rows]
        new_value = values if multiple else (values[0] if values else None)

    existing = step_extracted.get(key)
    if existing is not None and isinstance(existing, list) and isinstance(new_value, list):
        seen: List[Any] = list(existing)
        for row in new_value:
            if row not in seen:
                seen.append(row)
        step_extracted[key] = seen
        logger.info(
            "Extract %r: appended %d new row(s) (total %d)",
            key, len(new_value), len(seen),
        )
    else:
        step_extracted[key] = new_value
        count = len(new_value) if isinstance(new_value, list) else (1 if new_value is not None else 0)
        logger.info(
            "Extract %r: captured %s %s",
            key, count, "rows" if fields else "values",
        )
    return True


def _extract_node_value(node: Any, action: Any) -> Any:
    """Extract a single value from a BeautifulSoup node per an Extract action."""
    extract_type = getattr(action, "extract_type", "text")
    if extract_type == "text":
        return node.get_text(" ", strip=True)
    if extract_type == "html":
        return str(node)
    if extract_type == "attribute":
        attr = getattr(action, "attribute", None)
        if not attr:
            return None
        return node.get(attr)
    return node.get_text(" ", strip=True)


def _apply_field(row: Any, spec: Any) -> Any:
    """Run one ``FieldSpec`` against a row element."""
    if isinstance(spec, dict):
        sel = spec.get("selector")
        extract_type = spec.get("extract_type") or (
            "text" if spec.get("attribute") in (None, "text") else
            "html" if spec.get("attribute") == "html" else
            "attribute"
        )
        attribute = spec.get("attribute")
        if attribute in ("text", "html"):
            attribute = None
        multi = bool(spec.get("multiple", False))
    else:
        sel = spec.selector
        extract_type = spec.extract_type
        attribute = spec.attribute
        multi = spec.multiple

    if not sel:
        return None

    sel = _normalize_bs4_selector(sel)
    try:
        matches = row.select(sel)
    except Exception as exc:
        logger.debug("Field selector %r failed: %s", sel, exc)
        return [] if multi else None

    if not matches:
        return [] if multi else None

    def extract(node: Any) -> Any:
        if extract_type == "text":
            return node.get_text(" ", strip=True)
        if extract_type == "html":
            return str(node)
        if extract_type == "attribute" and attribute:
            return node.get(attribute)
        return node.get_text(" ", strip=True)

    if multi:
        return [extract(m) for m in matches]
    return extract(matches[0])


async def _action_screenshot(driver: AbstractDriver, action: Any) -> bool:
    """Take a screenshot."""
    output_path = getattr(action, "output_path", None) or "."
    filename = action.get_filename() if hasattr(action, "get_filename") else f"screenshot_{int(time.time())}.png"
    full_path = f"{output_path}/{filename}"

    await driver.screenshot(full_path)
    logger.info("Screenshot saved: %s", full_path)
    return True


async def _action_press_key(driver: AbstractDriver, action: Any) -> bool:
    """Press keyboard keys."""
    for key in action.keys:
        await driver.press_key(key)
    return True


async def _action_select(
    driver: AbstractDriver, action: Any, default_timeout: int
) -> bool:
    """Select from a dropdown.

    The ``by`` mode is taken from ``action.by`` when explicitly set;
    otherwise inferred from which of ``value``, ``text``, or ``index``
    is populated on the action.
    """
    selector = action.selector
    timeout = action.timeout or default_timeout

    by = getattr(action, "by", None) or (
        "value" if getattr(action, "value", None)
        else "text" if getattr(action, "text", None)
        else "index" if getattr(action, "index", None) is not None
        else "value"
    )
    raw = (
        action.value if by == "value"
        else getattr(action, "text", None) if by == "text"
        else str(getattr(action, "index", 0))
    )
    await driver.select_option(selector, raw, by=by, timeout=timeout)
    return True


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

import re as _re

# jQuery-style ``:contains("text")`` → soupsieve ``:-soup-contains("text")``.
_CONTAINS_RE = _re.compile(r"(?<!-soup)(?<!:):contains\(")


def _normalize_bs4_selector(selector: Optional[str]) -> str:
    """Fix common CSS-selector mistakes before passing to BeautifulSoup.

    - ``:contains(...)`` → ``:-soup-contains(...)`` (deprecated in soupsieve).
    - Leaves selectors without those patterns untouched.
    """
    if not selector:
        return selector or ""
    return _CONTAINS_RE.sub(":-soup-contains(", selector)


_SOUP_PSEUDO_RE = _re.compile(
    r"\s*:(?:-soup-contains|contains|has)\((?:[^()]|\([^()]*\))*\)",
    _re.IGNORECASE,
)

_SOUP_CONTAINS_TEXT_RE = _re.compile(
    r":(?:-soup-contains|contains)\(\s*['\"]([^'\"]+)['\"]\s*\)",
    _re.IGNORECASE,
)


def _strip_soup_only_pseudos(selector: str) -> str:
    """Remove ``:contains(...)``, ``:-soup-contains(...)``, ``:has(...)``
    clauses from a CSS selector and collapse empty comma alternatives.
    """
    if not selector:
        return ""
    cleaned = _SOUP_PSEUDO_RE.sub("", selector)
    parts = [p.strip() for p in cleaned.split(",")]
    parts = [p for p in parts if p]
    return ", ".join(parts)


async def _get_current_url(driver: AbstractDriver) -> str:
    """Get the current URL from the driver (sync property)."""
    return driver.current_url


async def _get_page_source(driver: AbstractDriver) -> str:
    """Get the page source from the driver."""
    return await driver.get_page_source()


# Common banner/overlay ids or selectors that intercept clicks. Kept for
# reference but overlay cleanup is now the driver's responsibility.
_COMMON_OVERLAY_SELECTORS = (
    "#gpc-banner-container",
    "#onetrust-consent-sdk",
    "#onetrust-banner-sdk",
    "#truste-consent-track",
    ".cc-window", ".cookie-banner",
    "[id*='cookie-banner']",
    "[class*='cookie-banner']",
    "[id*='consent-banner']",
    "[role='dialog'][aria-label*='cookie' i]",
    "[role='dialog'][aria-label*='privacy' i]",
)


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
                try:
                    from lxml import etree

                    tree = etree.HTML(str(soup))
                    elements_xml = tree.xpath(sel.selector)
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
