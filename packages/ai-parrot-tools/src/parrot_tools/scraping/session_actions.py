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

import asyncio
import logging
import os
import re
import select
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, urlsplit, urlunsplit

from .drivers.abstract import AbstractDriver
from .models import (
    Authenticate,
    AwaitBrowserEvent,
    AwaitHuman,
    AwaitKeyPress,
    GetCookies,
    ScrapingStep,
    SetCookies,
    UploadFile,
    WaitForDownload,
)

if TYPE_CHECKING:
    # Soft dependency (Decision D2): parrot.human.channels.base.HumanChannel
    # lives in core ai-parrot, but is only imported for typing so a
    # core-only install of parrot_tools never pays for it at runtime.
    from parrot.human.channels.base import HumanChannel

logger = logging.getLogger(__name__)

# Recipient label used for HITL notifications/interactions raised from a
# mid-plan await_human step. The caller supplies *which* HumanChannel
# instance to use; this module does not resolve routing beyond that.
_DEFAULT_HUMAN_RECIPIENT = "operator"

# Callback used to dispatch a single step back to the caller's executor.
# Signature mirrors advanced_actions.DispatchStepFn / executor._dispatch_step.
DispatchStepFn = Callable[[AbstractDriver, ScrapingStep, str, int, Dict[str, Any]], Awaitable[bool]]

# Optional credential resolution hook. Returns ``(username, password)`` (either
# of which may be ``None``) or ``None`` to fall back to the action's literal
# fields. TASK-2389 wires a CredentialBroker-backed implementation of this;
# this module only defines the shape and calls it if supplied.
CredentialResolverFn = Callable[[Authenticate], Awaitable[Optional[Tuple[Optional[str], Optional[str]]]]]

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
            (e.g. via a ``CredentialBroker``) instead of reading
            ``action.username``/``action.password`` literally.

            When ``action.credential_provider`` is set (TASK-2389, Decision
            G3 — "no credentials in plan JSON"), *only* the resolver is
            consulted: a missing resolver, a resolver exception, a ``None``
            result (broker miss), or an incomplete credential all fail the
            step closed — the literal fields are **never** read in this
            case, even as a fallback.

            When ``action.credential_provider`` is unset, *credential_resolver*
            is an optional soft override (pre-TASK-2389 behaviour, kept for
            back-compat): a non-``None`` result overrides the literal fields
            field-by-field; a ``None`` result or no resolver at all falls
            back to the literal fields.
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

        if action.credential_provider:
            # Broker-backed resolution — literal fields must NEVER be used,
            # not even as a fallback (TASK-2389, Goal G3).
            if resolved is None:
                logger.error(
                    "Credential broker resolution failed for provider=%r; "
                    "failing closed rather than falling back to literal "
                    "fields",
                    action.credential_provider,
                )
                return False
            resolved_username, resolved_password = resolved
            if not resolved_username or not resolved_password:
                logger.error(
                    "Credential broker returned an incomplete credential " "for provider=%r; failing closed",
                    action.credential_provider,
                )
                return False
            username, password = resolved_username, resolved_password
        elif resolved is not None:
            # No provider configured — soft override path (pre-TASK-2389
            # behaviour): only overrides the fields the resolver supplied.
            resolved_username, resolved_password = resolved
            username = resolved_username if resolved_username is not None else username
            password = resolved_password if resolved_password is not None else password
    elif action.credential_provider:
        logger.error(
            "Authenticate.credential_provider=%r requires a credential_resolver; "
            "failing closed (never falling back to literal fields)",
            action.credential_provider,
        )
        return False

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
        logger.error("Authentication method %r requires custom_steps", action.method)
        return False
    if dispatch_step_fn is None:
        logger.error(
            "Authentication method %r requires a dispatch_step_fn to run " "custom_steps",
            action.method,
        )
        return False

    step_extracted: Dict[str, Any] = {}
    for sub_action in action.custom_steps:
        step = ScrapingStep(action=sub_action)
        success = await dispatch_step_fn(driver, step, "", timeout, step_extracted)
        if not success:
            logger.warning("Custom authentication step failed: %s", sub_action.description)
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


# ── Human-in-the-loop waits ─────────────────────────────────────────
#
# Decision D2: the human approving a plan is typically watching Telegram,
# not the browser. A DOM-only wait is therefore not sufficient — when a
# HumanChannel is injected, these functions notify it so the pause actually
# reaches a person, and condition_type="manual" (which has no DOM condition
# to poll) *requires* a channel, failing closed without one rather than
# blocking for the full timeout.


async def exec_await_human(
    driver: AbstractDriver,
    action: AwaitHuman,
    *,
    channel: Optional[HumanChannel] = None,
) -> bool:
    """Execute an :class:`AwaitHuman` action.

    Args:
        driver: Browser driver implementing :class:`AbstractDriver`.
        action: The :class:`AwaitHuman` model — one of four
            ``condition_type`` values (``selector``, ``url_contains``,
            ``title_contains``, ``manual``).
        channel: Optional injected :class:`HumanChannel` (parrot.human —
            not a bespoke notifier, Decision D2). DOM-based condition types
            notify it when supplied; ``condition_type="manual"`` requires it.

    Returns:
        ``True`` once the condition is satisfied (or a manual confirmation
        is received); ``False`` on timeout, missing condition, or a
        ``manual`` wait with no channel (fails closed immediately).
    """
    timeout = int(action.timeout or 300)

    if action.condition_type == "manual":
        return await _await_human_manual(action, channel, timeout)

    target = action.target
    if not target:
        logger.error("await_human requires at least one condition " "(selector, url_contains, title_contains)")
        return False

    if channel is not None:
        try:
            await channel.send_notification(
                _DEFAULT_HUMAN_RECIPIENT,
                f"{action.message} (waiting on {action.condition_type}={target!r})",
            )
        except Exception:
            logger.warning(
                "Failed to notify human channel about a pending await_human step",
                exc_info=True,
            )

    logger.info("%s in the browser window (condition_type=%s)", action.message, action.condition_type)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await _check_human_condition(driver, action.condition_type, target):
            logger.info("Human step condition satisfied; resuming automation")
            return True
        await asyncio.sleep(0.5)

    logger.warning("await_human timed out waiting for condition_type=%s", action.condition_type)
    return False


async def _check_human_condition(driver: AbstractDriver, condition_type: str, target: str) -> bool:
    """Evaluate one of the DOM-based await_human conditions."""
    try:
        if condition_type == "selector":
            count = await driver.execute_script("return document.querySelectorAll(arguments[0]).length;", target)
            return bool(count) and int(count) > 0
        if condition_type == "url_contains":
            return target in driver.current_url
        if condition_type == "title_contains":
            title = await driver.evaluate("document.title")
            return target in (title or "")
    except Exception:
        # Debug-only: this runs on every poll iteration, so logging at a
        # higher level would spam a multi-minute wait's log output.
        logger.debug("await_human condition check raised", exc_info=True)
        return False
    return False


async def _await_human_manual(
    action: AwaitHuman,
    channel: Optional[HumanChannel],
    timeout: int,
) -> bool:
    """Handle ``condition_type="manual"`` — requires an injected channel.

    There is no DOM condition to poll for a manual step, so this fails
    closed immediately when no channel is supplied (Decision D2) rather than
    blocking for the full timeout. With a channel, a confirmation request is
    sent and this waits (bounded by *timeout*) for any response delivered
    through :meth:`HumanChannel.register_response_handler`.
    """
    if channel is None:
        logger.error(
            "await_human condition_type='manual' requires a HumanChannel; "
            "failing closed rather than blocking for %ds",
            timeout,
        )
        return False

    # Local import: parrot.human.models is core (not the integrations
    # satellite), but this keeps the cost lazy and scoped to the one
    # condition_type that actually needs it.
    from parrot.human.models import HumanInteraction

    resume_event = asyncio.Event()

    async def _on_response(_response: Any) -> None:
        resume_event.set()

    try:
        await channel.register_response_handler(_on_response)
        interaction = HumanInteraction(question=action.message, timeout=float(timeout))
        delivered = await channel.send_interaction(interaction, _DEFAULT_HUMAN_RECIPIENT)
    except Exception:
        logger.exception("Failed to request manual human confirmation")
        return False

    if not delivered:
        logger.warning("Manual await_human interaction was not delivered to any recipient")
        return False

    try:
        await asyncio.wait_for(resume_event.wait(), timeout=timeout)
    except TimeoutError:
        logger.warning("Manual await_human step timed out waiting for a human response")
        return False

    logger.info("Manual await_human step resumed after a human response")
    return True


# ── Console keypress wait ────────────────────────────────────────────


async def exec_await_keypress(driver: AbstractDriver, action: AwaitKeyPress) -> bool:
    """Execute an :class:`AwaitKeyPress` action.

    Pauses until the operator presses a key in the console (stdin). Useful
    when there is no reliable selector to wait on. ``driver`` is accepted
    (unused) for signature parity with the other ``exec_*`` functions.

    Args:
        driver: Browser driver implementing :class:`AbstractDriver` (unused).
        action: The :class:`AwaitKeyPress` model — ``expected_key`` (``None``
            means any key), ``message``, and ``timeout`` (default 300s).

    Returns:
        ``True`` once the expected key (or any key, if unset) is pressed;
        ``False`` on timeout.
    """
    timeout = int(action.timeout or 300)
    prompt = action.message or "Press any key to continue..."
    expected_key = action.expected_key

    logger.info(prompt)
    start = time.monotonic()
    loop = asyncio.get_running_loop()

    while time.monotonic() - start < timeout:
        ready, _, _ = await loop.run_in_executor(None, lambda: select.select([sys.stdin], [], [], 0.5))
        if ready:
            try:
                keypress = sys.stdin.readline().strip()
            except Exception:
                logger.debug("Failed reading a keypress from stdin", exc_info=True)
                continue
            if expected_key is None or keypress == expected_key:
                logger.info("Continuing after keypress")
                return True

    logger.warning("await_keypress timed out after %ds", timeout)
    return False


# ── Browser-side resume event ────────────────────────────────────────

_BROWSER_EVENT_JS = """
(function() {{
if (window.__scrapeSignal && window.__scrapeSignal._bound) return 0;
window.__scrapeSignal = window.__scrapeSignal || {{ ready:false, _bound:false }};
function signal() {{
    try {{ localStorage.setItem('{ls_key}', '1'); }} catch(e) {{}}
    window.__scrapeSignal.ready = true;
    var btn = document.getElementById('__scrapeResumeBtn');
    if (btn) {{ btn.remove(); }}
}}
window.addEventListener('keydown', function(e) {{
    try {{
    var k = '{key_combo}';
    if (k === 'ctrl_enter' && (e.ctrlKey || e.metaKey) && e.key === 'Enter') {{ e.preventDefault(); signal(); }}
    else if (k === 'cmd_enter' && e.metaKey && e.key === 'Enter') {{ e.preventDefault(); signal(); }}
    else if (k === 'alt_shift_s' && e.altKey && e.shiftKey && (e.key.toLowerCase() === 's')) {{ e.preventDefault(); signal(); }}
    }} catch(_e) {{}}
}}, true);
try {{
    window.addEventListener('{custom_event}', function() {{ signal(); }}, false);
}} catch(_e) {{}}
if ({overlay_flag}) {{
    try {{
    if (!document.getElementById('__scrapeResumeBtn')) {{
        var btn = document.createElement('button');
        btn.id = '__scrapeResumeBtn';
        btn.textContent = 'Resume scraping';
        Object.assign(btn.style, {{
        position: 'fixed', right: '16px', bottom: '16px', zIndex: 2147483647,
        padding: '10px 14px', fontSize: '14px', borderRadius: '8px', border: 'none',
        cursor: 'pointer', background: '#10b981', color: '#fff',
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


async def exec_await_browser_event(driver: AbstractDriver, action: AwaitBrowserEvent) -> bool:
    """Execute an :class:`AwaitBrowserEvent` action.

    Pauses automation until a user triggers a browser-side event: pressing
    a configured key combo, clicking an optional floating "Resume" button,
    dispatching a custom DOM event, or setting a localStorage flag —
    whichever is configured via ``action.wait_condition``/``action.target``.

    Args:
        driver: Browser driver implementing :class:`AbstractDriver`.
        action: The :class:`AwaitBrowserEvent` model.

    Returns:
        ``True`` once the event is received; ``False`` on timeout.
    """
    cfg: Dict[str, Any] = {}
    if isinstance(action.wait_condition, dict) and action.wait_condition:
        cfg = action.wait_condition
    elif isinstance(action.target, dict):
        cfg = action.target
    elif isinstance(action.target, str):
        cfg = {"key_combo": action.target}

    key_combo = str(cfg.get("key_combo") or "ctrl_enter").lower()
    show_overlay = bool(cfg.get("show_overlay_button", False))
    ls_key = cfg.get("local_storage_key", "__scrapeResume")
    predicate_js = cfg.get("predicate_js")
    custom_event = cfg.get("custom_event_name", "scrape-resume")
    timeout = int(action.timeout or 300)

    inject_script = _BROWSER_EVENT_JS.format(
        ls_key=ls_key,
        key_combo=key_combo,
        custom_event=custom_event,
        overlay_flag="true" if show_overlay else "false",
    )

    try:
        await driver.execute_script(inject_script)
    except Exception:
        logger.debug("Failed injecting the await_browser_event listener script", exc_info=True)

    logger.info(
        "Awaiting browser event: key combo, floating button, custom event, " "or localStorage flag will resume."
    )

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await _check_browser_event_ready(driver, predicate_js, ls_key):
            try:
                await driver.execute_script(
                    f"try{{localStorage.removeItem('{ls_key}')}}catch(e){{}}; "
                    "if(window.__scrapeSignal){window.__scrapeSignal.ready=false}"
                )
            except Exception:
                logger.debug("Failed clearing the browser-event signal", exc_info=True)
            logger.info("Browser event received; resuming automation")
            return True
        await asyncio.sleep(0.3)

    logger.warning("await_browser_event timed out after %ds", timeout)
    return False


async def _check_browser_event_ready(driver: AbstractDriver, predicate_js: Optional[str], ls_key: str) -> bool:
    """Check whether any of the browser-event resume signals has fired."""
    try:
        if predicate_js:
            ok = await driver.execute_script(predicate_js)
            if ok:
                return True
        val = await driver.execute_script(f"try{{return localStorage.getItem('{ls_key}')}}catch(e){{return null}}")
        if val == "1":
            return True
        ready = await driver.execute_script("return !!(window.__scrapeSignal && window.__scrapeSignal.ready);")
        return bool(ready)
    except Exception:
        # Debug-only: this runs on every poll iteration, so logging at a
        # higher level would spam a multi-minute wait's log output.
        logger.debug("await_browser_event readiness check raised", exc_info=True)
        return False


# ── File transfer (upload / download) ───────────────────────────────
#
# Paths handled here will eventually be authored outside this repository (the
# private plans directory, spec §3 Deliverable X), so they are treated as
# untrusted input: existence is checked before any browser interaction, and
# an opt-in root guard (PARROT_SCRAPING_FILES_ROOT) rejects path traversal.

#: Environment variable naming a directory every upload/download/move_to path
#: must resolve inside. Unset by default (back-compat for local/dev use) —
#: set it to sandbox this module's filesystem access in production.
_FILE_ROOT_ENV_VAR = "PARROT_SCRAPING_FILES_ROOT"

#: Suffixes indicating a file is still mid-download (browser temp files).
_INCOMPLETE_DOWNLOAD_SUFFIXES = {".tmp", ".crdownload", ".part", ".download"}


def _resolve_within_root(raw_path: str) -> Optional[Path]:
    """Resolve *raw_path*, rejecting it if it escapes the configured root.

    The root is opt-in via the ``PARROT_SCRAPING_FILES_ROOT`` environment
    variable: unset, any resolved path is accepted; set, any path resolving
    outside that root is rejected and logged.

    Returns:
        The resolved :class:`Path`, or ``None`` if it escapes the root.
    """
    path = Path(raw_path).expanduser().resolve()
    root = os.environ.get(_FILE_ROOT_ENV_VAR)
    if root:
        root_path = Path(root).expanduser().resolve()
        try:
            path.relative_to(root_path)
        except ValueError:
            logger.error("Rejecting path outside the configured root %s: %s", root_path, path)
            return None
    return path


async def exec_upload_file(driver: AbstractDriver, action: UploadFile) -> bool:
    """Execute an :class:`UploadFile` action.

    Uploads via ``driver.fill(selector, path)`` — the only file-input
    interaction available through :class:`AbstractDriver` (neither the ABC
    nor its concrete drivers expose an ``upload_file``/``set_input_files``
    method). This is the same mechanism Selenium's ``send_keys`` on a file
    input uses under the hood; Playwright's ``fill()`` does not support file
    inputs, so this action is effectively Selenium-oriented until a native
    per-driver upload hook exists.

    Args:
        driver: Browser driver implementing :class:`AbstractDriver`.
        action: The :class:`UploadFile` model — single ``file_path`` or,
            with ``multiple_files=True``, the ``file_paths`` list.

    Returns:
        ``True`` on success; ``False`` if a path is missing, escapes the
        configured root, or the driver interaction fails.
    """
    if action.multiple_files and action.file_paths:
        raw_paths = action.file_paths
    else:
        raw_paths = [action.file_path]

    resolved_paths: List[Path] = []
    for raw_path in raw_paths:
        path = _resolve_within_root(raw_path)
        if path is None:
            return False
        if not path.exists():
            logger.error("Upload file not found: %s", path)
            return False
        resolved_paths.append(path)

    value = "\n".join(str(p) for p in resolved_paths)
    try:
        await driver.fill(action.selector, value)
    except Exception:
        logger.exception("Failed to upload file(s) via selector %s", action.selector)
        return False

    logger.info("Uploaded %d file(s) via %s", len(resolved_paths), action.selector)

    if action.wait_after_upload:
        try:
            await driver.wait_for_selector(action.wait_after_upload, timeout=action.wait_timeout)
            logger.info("Post-upload element found: %s", action.wait_after_upload)
        except Exception:  # noqa: BLE001 — a missing post-upload element is a warning, not an upload failure
            logger.warning(
                "Post-upload element not found within %ds: %s",
                action.wait_timeout,
                action.wait_after_upload,
            )

    return True


async def exec_wait_for_download(driver: AbstractDriver, action: WaitForDownload) -> bool:
    """Execute a :class:`WaitForDownload` action.

    Polls the filesystem for a file matching ``filename_pattern`` that has
    stabilised (size unchanged across a short interval and non-zero) —
    downloads are a driver-external filesystem event, so there is no
    :class:`AbstractDriver` method for this; ``driver`` is accepted (unused)
    for signature parity with the other ``exec_*`` functions.

    Args:
        driver: Browser driver implementing :class:`AbstractDriver` (unused).
        action: The :class:`WaitForDownload` model — ``filename_pattern``,
            ``download_path``, ``timeout``, ``move_to``, ``delete_after``.

    Returns:
        ``True`` once a matching, stable download is found (and moved, if
        ``move_to`` is set); ``False`` on timeout or a rejected path.
    """
    if action.download_path:
        download_dir = _resolve_within_root(action.download_path)
        if download_dir is None:
            return False
    else:
        download_dir = Path.home() / "Downloads"

    download_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Monitoring for downloads in: %s", download_dir)

    timeout = action.timeout
    deadline = time.monotonic() + timeout
    downloaded_file: Optional[Path] = None

    while time.monotonic() < deadline:
        candidates = [f for f in download_dir.glob("*") if f.is_file()]
        if action.filename_pattern:
            candidates = [f for f in candidates if f.match(action.filename_pattern)]
        candidates = [f for f in candidates if f.suffix.lower() not in _INCOMPLETE_DOWNLOAD_SUFFIXES]

        for candidate in candidates:
            try:
                size1 = candidate.stat().st_size
                await asyncio.sleep(0.2)
                size2 = candidate.stat().st_size
            except OSError:
                continue
            if size1 == size2 and size1 > 0:
                downloaded_file = candidate
                break

        if downloaded_file:
            break
        await asyncio.sleep(0.3)

    if downloaded_file is None:
        logger.error("Download not detected within %ds", timeout)
        return False

    logger.info("Download complete: %s", downloaded_file.name)

    if action.move_to:
        move_target = _resolve_within_root(action.move_to)
        if move_target is None:
            return False
        final_path = move_target / downloaded_file.name if move_target.is_dir() else move_target
        final_path.parent.mkdir(parents=True, exist_ok=True)
        downloaded_file.rename(final_path)
        logger.info("Moved download to: %s", final_path)
        downloaded_file = final_path

    if action.delete_after:
        downloaded_file.unlink()
        logger.info("Deleted file: %s", downloaded_file.name)

    return True
