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
# Action dispatch
# ═══════════════════════════════════════════════════════════════════════

async def _dispatch_step(
    driver: Any,
    step: ScrapingStep,
    base_url: str,
    timeout: int,
    step_extracted: Dict[str, Any],
) -> bool:
    """Dispatch a single ``ScrapingStep`` to the appropriate action handler.

    Args:
        driver: Browser driver instance.
        step: Parsed scraping step.
        base_url: Base URL for resolving relative URLs.
        timeout: Default timeout in seconds.
        step_extracted: Shared dict collecting results from ``extract`` steps.

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
    elif action_type == "extract":
        return await _action_extract(driver, action, step, step_extracted, loop)
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

        native_css = _strip_soup_only_pseudos(condition)
        if native_css != condition:
            logger.warning(
                "wait selector %r contains BeautifulSoup-only pseudo-classes "
                "(:contains / :-soup-contains / :has) that Selenium's native "
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

        def wait_sync():
            WebDriverWait(driver, wait_timeout, poll_frequency=0.25).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, native_css))
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

    # Auto-rescue for BS4-only pseudos in a CSS selector.
    # ``:-soup-contains('X')`` expresses "element matching PREFIX whose
    # text contains X". We preserve the CSS prefix and apply the text
    # filter in JS so specificity (e.g. ``.btn-group[role='radiogroup']
    # button``) is retained — converting to a bare XPath would lose it.
    js_text_filter: Optional[str] = None
    if selector_type == "css" and selector:
        m = _SOUP_CONTAINS_TEXT_RE.search(selector)
        if m:
            js_text_filter = m.group(1)
            css_prefix = selector[:m.start()].rstrip() or "*"
            # Strip any further pseudos after the text-contains
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
                    "stripped to %r for Selenium CSS.",
                    selector, stripped,
                )
                selector = stripped
            if not selector.strip():
                logger.warning("click selector reduced to empty; skipping step")
                return False

    def click_sync():
        if js_text_filter is not None:
            # CSS prefix + JS text match — preserves specificity. Uses
            # dispatchEvent so React's synthetic-event system catches it;
            # HTMLElement.click() alone doesn't always fire onClick.
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
            hit = driver.execute_script(script, selector, js_text_filter)
            if not hit:
                raise RuntimeError(
                    f"No element matching CSS {selector!r} contained text "
                    f"{js_text_filter!r}"
                )
            return True

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
        except Exception as exc:
            # Common cause: a cookie/privacy banner is covering the
            # element. Try removing plausible overlay containers and
            # retry once, then fall through to a React-friendly JS
            # dispatchEvent (HTMLElement.click() skips React's
            # onClick in some setups).
            logger.info("click intercepted (%s); attempting overlay cleanup", type(exc).__name__)
            _dismiss_common_overlays(driver)
            try:
                element.click()
            except Exception:
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});"
                    " arguments[0].dispatchEvent(new MouseEvent('click',"
                    " {bubbles: true, cancelable: true, view: window}));",
                    element,
                )
        return True

    await loop.run_in_executor(None, click_sync)
    return True


# Common banner/overlay ids or selectors that intercept clicks. Removed
# before click retry — not ideal for pages that depend on them, but for
# scraping we just need them out of the way.
_COMMON_OVERLAY_SELECTORS = (
    "#gpc-banner-container",            # AT&T privacy banner
    "#onetrust-consent-sdk",            # OneTrust cookie banner
    "#onetrust-banner-sdk",
    "#truste-consent-track",            # TrustArc
    ".cc-window", ".cookie-banner",
    "[id*='cookie-banner']",
    "[class*='cookie-banner']",
    "[id*='consent-banner']",
    "[role='dialog'][aria-label*='cookie' i]",
    "[role='dialog'][aria-label*='privacy' i]",
)


def _dismiss_common_overlays(driver: Any) -> int:
    """Remove common cookie/privacy/consent overlays from the DOM.

    Returns the number of elements removed. Best-effort — ignores errors
    so a broken selector doesn't block the click retry.
    """
    script = (
        "let n = 0;"
        " const sels = arguments[0];"
        " for (const s of sels) {"
        "   try {"
        "     document.querySelectorAll(s).forEach(el => { el.remove(); n++; });"
        "   } catch (e) {}"
        " }"
        " return n;"
    )
    try:
        removed = driver.execute_script(script, list(_COMMON_OVERLAY_SELECTORS))
        if removed:
            logger.info("overlay cleanup: removed %d element(s)", removed)
        return removed or 0
    except Exception as exc:  # noqa: BLE001
        logger.debug("overlay cleanup failed: %s", exc)
        return 0


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
    """Scroll the page.

    For ``direction='bottom'`` we scroll in chunks with short pauses
    between steps so intersection-observer-driven lazy loads (FAQ
    accordions, image carousels, infinite lists) actually fire. A single
    jump to the bottom often skips those entirely because the observer
    never sees the target element transition from "not visible" to
    "visible" — it was never visible during the jump.
    """
    direction = action.direction
    amount = getattr(action, "amount", None)

    if direction == "top":
        await loop.run_in_executor(None, driver.execute_script, "window.scrollTo(0, 0);")
        return True

    if direction == "bottom":
        # Chunked sweep: 6 steps from current scroll position to the
        # page's full height, with small settle pauses so lazy content
        # hydrates between steps.
        def get_height() -> int:
            return int(
                driver.execute_script(
                    "return Math.max(document.body.scrollHeight,"
                    " document.documentElement.scrollHeight);"
                ) or 0
            )

        height = await loop.run_in_executor(None, get_height)
        if height <= 0:
            return True
        chunks = 6
        for i in range(1, chunks + 1):
            y = min(height * i // chunks, height)
            await loop.run_in_executor(
                None, driver.execute_script, f"window.scrollTo(0, {y});"
            )
            await asyncio.sleep(0.4)
            # Page may have grown as lazy content loaded — re-sample so
            # we don't stop short.
            height = max(height, await loop.run_in_executor(None, get_height))
        return True

    if direction == "down":
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


async def _action_extract(
    driver: Any,
    action: Any,
    step: ScrapingStep,
    step_extracted: Dict[str, Any],
    loop: asyncio.AbstractEventLoop,
) -> bool:
    """Run an ``extract`` step against the current DOM.

    Captures ``driver.page_source`` at the step's position in the plan so
    data that only exists after intermediate ``click`` / ``scroll`` / JS
    mutations is preserved. Results go into the shared ``step_extracted``
    dict under the extract step's chosen key.

    Supports two modes on the ``Extract`` action model:

    - **Flat**: no ``fields`` dict → returns a single value (or list when
      ``multiple=True``). Honors ``extract_type`` (text|html|attribute).
    - **Row-of-fields**: ``fields={name: FieldSpec}`` → the parent
      ``selector`` picks row elements; each field selector runs
      relative to its row. Returns a dict (or list of dicts) keyed by
      field name.
    """
    # Capture the DOM at this step
    html = await loop.run_in_executor(None, lambda: driver.page_source)
    soup = BeautifulSoup(html, "html.parser")

    key = (
        getattr(action, "extract_name", "")
        or getattr(action, "name", "")
        or step.description
        or "extracted_data"
    )
    # Guard against the action-type opcode leaking in as the key
    if key == "extract":
        key = "extracted_data"

    # Auto-upgrade deprecated ``:contains(...)`` to ``:-soup-contains(...)``
    # so the BS4 selector actually matches. The LLM tends to emit the old
    # jQuery-ish form; soupsieve deprecated it and returns empty matches.
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

    # Merge semantics: when a later step uses the same extract_name as an
    # earlier one, APPEND rather than overwrite. This lets a plan extract
    # the same kind of content in multiple DOM states (e.g. toggle-based
    # carousels) without needing per-state keys.
    existing = step_extracted.get(key)
    if existing is not None and isinstance(existing, list) and isinstance(new_value, list):
        # dedupe identical rows (dicts compared by content)
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
    """Run one ``FieldSpec`` against a row element.

    ``spec`` can be a ``FieldSpec`` pydantic model or a dict (when the
    plan was loaded without schema validation). Missing selectors return
    ``None``; multiple=True returns a list of string values.
    """
    # Dict fallback when the plan arrives unvalidated
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

import re as _re

# jQuery-style ``:contains("text")`` → soupsieve ``:-soup-contains("text")``.
# LLMs (and docs) lean on the old form; soupsieve deprecated it and now
# silently returns empty matches, so plans look like they ran cleanly
# while actually extracting nothing. We rewrite on the way in.
_CONTAINS_RE = _re.compile(r"(?<!-soup)(?<!:):contains\(")


def _normalize_bs4_selector(selector: Optional[str]) -> str:
    """Fix common CSS-selector mistakes before passing to BeautifulSoup.

    - ``:contains(...)`` → ``:-soup-contains(...)`` (deprecated in soupsieve).
    - Leaves selectors without those patterns untouched.
    """
    if not selector:
        return selector or ""
    return _CONTAINS_RE.sub(":-soup-contains(", selector)


# Strips soupsieve-only pseudo-classes so the remainder is plain CSS that
# Selenium's native engine can parse. Not perfect — mostly a rescue for
# cases where the LLM mixed :has/:contains into a selenium-side selector.
_SOUP_PSEUDO_RE = _re.compile(
    r"\s*:(?:-soup-contains|contains|has)\((?:[^()]|\([^()]*\))*\)",
    _re.IGNORECASE,
)

# Capture the text argument of the FIRST :-soup-contains('TEXT') /
# :contains('TEXT') pseudo in a selector, so click/wait can convert the
# intent into an XPath contains(text(), ...) locator.
_SOUP_CONTAINS_TEXT_RE = _re.compile(
    r":(?:-soup-contains|contains)\(\s*['\"]([^'\"]+)['\"]\s*\)",
    _re.IGNORECASE,
)


def _strip_soup_only_pseudos(selector: str) -> str:
    """Remove ``:contains(...)``, ``:-soup-contains(...)``, ``:has(...)``
    clauses from a CSS selector and collapse empty comma alternatives.

    These pseudo-classes are supported by BeautifulSoup/soupsieve but NOT
    by Selenium's native CSS engine; leaving them in makes ``wait`` /
    ``click`` silently time out. Stripping is imperfect but beats hanging.
    """
    if not selector:
        return ""
    cleaned = _SOUP_PSEUDO_RE.sub("", selector)
    # Drop comma-separated alternatives that ended up empty
    parts = [p.strip() for p in cleaned.split(",")]
    parts = [p for p in parts if p]
    return ", ".join(parts)


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
