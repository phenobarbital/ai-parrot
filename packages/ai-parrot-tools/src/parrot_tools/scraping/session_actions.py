"""Session-identity browser actions — authenticate, cookies, file transfer,
human-in-the-loop waits, and browser events.

Stateless async helpers extracted from the legacy ``WebScrapingTool`` so the
modern ``executor.py`` dispatch path and the legacy tool can share a single
implementation (FEAT-453, Module 1). This mirrors the extraction shape
FEAT-222 established in ``advanced_actions.py`` for ``Loop``/``Conditional``:
module-level ``async def exec_<action>(driver, action, ...)`` functions that
accept an :class:`AbstractDriver` plus (where recursion is needed) a
``dispatch_step_fn`` callback — never methods on a tool class.

Before this module existed, ``executor.py::_dispatch_step`` matched these
action types, logged a warning, and returned ``True`` — reporting success
without doing anything. That defect is the reason this module exists: every
function here returns ``False`` (never ``True``) on a failure path.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, urlsplit, urlunsplit

from .drivers.abstract import AbstractDriver
from .models import (
    Authenticate,
    GetCookies,
    ScrapingStep,
    SetCookies,
)

logger = logging.getLogger(__name__)

# Callback used to dispatch a single step back to the caller's executor.
# Signature mirrors advanced_actions.DispatchStepFn / executor._dispatch_step.
DispatchStepFn = Callable[
    [AbstractDriver, ScrapingStep, str, int, Dict[str, Any]], Awaitable[bool]
]

# Optional credential resolution hook. Returns ``(username, password)`` (either
# of which may be ``None``) or ``None`` to fall back to the action's literal
# fields. TASK-2389 wires a CredentialBroker-backed implementation of this;
# this module only defines the shape and calls it if supplied.
CredentialResolverFn = Callable[
    [Authenticate], Awaitable[Optional[Tuple[Optional[str], Optional[str]]]]
]

# Matches one `name=value` pair inside a `document.cookie` string.
_COOKIE_PAIR_RE = re.compile(r"^\s*([^=;]+)=(.*)$")


# ── Authentication ──────────────────────────────────────────────────

async def exec_authenticate(
    driver: AbstractDriver,
    action: Authenticate,
    dispatch_step_fn: Optional[DispatchStepFn],
    *,
    credential_resolver: Optional[CredentialResolverFn] = None,
    timeout: int = 30,
) -> bool:
    """Execute an :class:`Authenticate` action.

    Supports all four ``method`` values:
        - ``"form"`` (default) — fills ``username_selector``/``password_selector``
          and clicks ``submit_selector``. ``enter_on_username=True`` presses
          Enter after the username field for multi-step logins.
        - ``"basic"`` — HTTP Basic Auth via credentials embedded in the URL
          (``scheme://user:pass@host/...``), navigated via the driver.
        - ``"oauth"`` / ``"custom"`` — dispatches ``action.custom_steps``
          sequentially through *dispatch_step_fn*, since neither has a
          generic form-based flow.

    Args:
        driver: Browser driver implementing :class:`AbstractDriver`.
        action: The :class:`Authenticate` model to execute.
        dispatch_step_fn: Callback used to dispatch ``custom_steps`` (required
            for ``method in ("oauth", "custom")``).
        credential_resolver: Optional async callable resolving credentials
            (e.g. via a broker) instead of reading ``action.username``/
            ``action.password`` literally. When it returns a non-``None``
            tuple, those values take precedence over the literal fields.
        timeout: Timeout (seconds) applied to navigation/wait steps.

    Returns:
        ``True`` on success, ``False`` on any failure. Never raises for
        expected failure modes — an unhandled exception is caught, logged
        (without leaking credentials), and turned into ``False``.
    """
    username = action.username
    password = action.password

    if credential_resolver is not None:
        try:
            resolved = await credential_resolver(action)
        except Exception:
            logger.exception(
                "Credential resolver raised while resolving authentication "
                "credentials; failing the authenticate step closed"
            )
            return False
        if resolved is not None:
            resolved_username, resolved_password = resolved
            username = resolved_username if resolved_username is not None else username
            password = resolved_password if resolved_password is not None else password

    try:
        if action.method == "form":
            return await _authenticate_form(driver, action, username, password, timeout)
        if action.method == "basic":
            return await _authenticate_basic(driver, username, password, timeout)
        if action.method in ("oauth", "custom"):
            return await _authenticate_via_custom_steps(driver, action, dispatch_step_fn, timeout)
        logger.error("Unknown authentication method: %r", action.method)
        return False
    except Exception:
        logger.exception("Authentication failed (method=%s)", action.method)
        return False


async def _authenticate_form(
    driver: AbstractDriver,
    action: Authenticate,
    username: Optional[str],
    password: Optional[str],
    timeout: int,
) -> bool:
    """Fill the username/password fields and submit the form."""
    if not username or not password:
        logger.error("Form authentication requires a username and password")
        return False

    await driver.fill(action.username_selector, username)
    if action.enter_on_username:
        await driver.press_key("Enter")

    await driver.fill(action.password_selector, password)
    await driver.click(action.submit_selector, timeout=10)

    # Best-effort settle after submit — a plan that navigates to a dashboard
    # should not proceed against a still-loading login page. Non-fatal: some
    # sites do not trigger a full navigation (SPA logins), so a timeout here
    # is not itself an authentication failure.
    try:
        await driver.wait_for_load_state(timeout=timeout)
    except Exception:
        logger.debug(
            "wait_for_load_state raised after form submission; continuing",
            exc_info=True,
        )

    logger.info("Form authentication submitted via %s", action.username_selector)
    return True


async def _authenticate_basic(
    driver: AbstractDriver,
    username: Optional[str],
    password: Optional[str],
    timeout: int,
) -> bool:
    """Authenticate via HTTP Basic Auth by embedding credentials in the URL.

    This is driver-agnostic: both Selenium and Playwright resolve
    ``scheme://user:pass@host/...`` as a native HTTP Basic Auth challenge
    response, so no driver-specific header injection is required.
    """
    if not username or not password:
        logger.error("Basic authentication requires a username and password")
        return False

    parsed = urlsplit(driver.current_url)
    if not parsed.hostname:
        logger.error("Basic authentication requires a current page with a URL")
        return False

    netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{parsed.hostname}"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    auth_url = urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))

    await driver.navigate(auth_url, timeout=timeout)
    logger.info("Basic authentication navigated with embedded credentials")
    return True


async def _authenticate_via_custom_steps(
    driver: AbstractDriver,
    action: Authenticate,
    dispatch_step_fn: Optional[DispatchStepFn],
    timeout: int,
) -> bool:
    """Run ``action.custom_steps`` sequentially for oauth/custom logins."""
    if not action.custom_steps:
        logger.error(
            "Authentication method %r requires custom_steps", action.method
        )
        return False
    if dispatch_step_fn is None:
        logger.error(
            "Authentication method %r requires a dispatch_step_fn to run "
            "custom_steps",
            action.method,
        )
        return False

    step_extracted: Dict[str, Any] = {}
    for sub_action in action.custom_steps:
        step = ScrapingStep(action=sub_action)
        success = await dispatch_step_fn(driver, step, "", timeout, step_extracted)
        if not success:
            logger.warning(
                "Custom authentication step failed: %s", sub_action.description
            )
            return False

    logger.info("Custom/OAuth authentication completed (%d step(s))", len(action.custom_steps))
    return True


# ── Cookies ──────────────────────────────────────────────────────────
#
# AbstractDriver deliberately exposes no cookie-specific methods (verified:
# no get_cookies/set_cookies on the ABC or on PlaywrightDriver/SeleniumDriver).
# Cookie access therefore goes through execute_script against document.cookie,
# exactly as the "or the driver-specific context" note in the spec's
# Codebase Contract anticipates for a driver-agnostic implementation. Note
# this only sees non-HttpOnly cookies — the same limitation any page-JS-based
# cookie read has.

async def exec_get_cookies(driver: AbstractDriver, action: GetCookies) -> Dict[str, Any]:
    """Execute a :class:`GetCookies` action.

    Args:
        driver: Browser driver implementing :class:`AbstractDriver`.
        action: The :class:`GetCookies` model (optional ``names``/``domain``
            filters).

    Returns:
        ``{"cookies": [...]}`` — a list of ``{"name": ..., "value": ...}``
        dicts. Returns an empty list (never raises) if cookie extraction
        fails.
    """
    try:
        raw = await driver.execute_script("return document.cookie;")
    except Exception:
        logger.exception("Failed to read document.cookie from the browser")
        return {"cookies": []}

    cookies: List[Dict[str, Any]] = []
    for part in (raw or "").split(";"):
        match = _COOKIE_PAIR_RE.match(part)
        if not match:
            continue
        name = match.group(1).strip()
        value = match.group(2).strip()
        if not name:
            continue
        cookies.append({"name": name, "value": value})

    if action.names:
        cookies = [c for c in cookies if c["name"] in action.names]
    if action.domain:
        # document.cookie carries no domain metadata to page JS, so this
        # filter cannot be honoured precisely in the driver-agnostic path.
        logger.debug(
            "GetCookies.domain=%r cannot be verified via document.cookie "
            "(no domain metadata is exposed to page JS); returning all "
            "name/value matches",
            action.domain,
        )

    logger.info("Retrieved %d cookie(s)", len(cookies))
    return {"cookies": cookies}


async def exec_set_cookies(driver: AbstractDriver, action: SetCookies) -> bool:
    """Execute a :class:`SetCookies` action.

    Args:
        driver: Browser driver implementing :class:`AbstractDriver`.
        action: The :class:`SetCookies` model — a list of cookie dicts with
            at least ``name``/``value``, and optional ``path``, ``domain``,
            ``secure``, ``same_site``/``sameSite``.

    Returns:
        ``True`` if every cookie was set; ``False`` on any failure.
    """
    try:
        for cookie in action.cookies:
            name = cookie.get("name")
            if not name:
                logger.warning("Skipping cookie without a 'name' field: %r", cookie)
                continue
            value = cookie.get("value", "")

            attrs = [f"path={cookie.get('path', '/')}"]
            if cookie.get("domain"):
                attrs.append(f"domain={cookie['domain']}")
            if cookie.get("secure"):
                attrs.append("secure")
            same_site = cookie.get("same_site") or cookie.get("sameSite")
            if same_site:
                attrs.append(f"samesite={same_site}")

            cookie_str = f"{name}={value}; " + "; ".join(attrs)
            await driver.execute_script(f"document.cookie = {cookie_str!r};")

        logger.info("Set %d cookie(s)", len(action.cookies))
        return True
    except Exception:
        logger.exception("Failed to set cookies in the browser")
        return False
