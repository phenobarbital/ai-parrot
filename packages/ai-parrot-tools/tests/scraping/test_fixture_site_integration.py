"""Real-browser integration tests for FEAT-453's session_actions dispatch
path (FEAT-455, Module 2).

Proves the SAME dispatch path FEAT-453 Module 2 closed against a real
headless Chromium instance and the real ``local_fixture_site`` — the class
of regression a mocked ``AbstractDriver`` can never catch.

Of the original 8 formerly-stubbed action types, only 2
(``authenticate``, ``set_cookies``) were found to produce a genuine, real
effect through ``PlaywrightDriver`` specifically. The other 6 fall into
three distinct, empirically-verified (not assumed) incompatibility
classes — none of them fixed here, per this task's explicit non-scope:

1. **A single systemic root cause** affects `get_cookies`, `await_human`
   (selector condition), and `await_browser_event`:
   ``TestSeleniumStyleScriptIncompatibilityWithPlaywright`` consolidates
   all three into one test class with one shared explanation, rather than
   three near-duplicate "known limitation" classes (see that class's
   docstring for the full root-cause description).
2. `upload_file` — a *different*, unrelated incompatibility (Playwright
   rejects ``.fill()`` on file inputs): ``TestUploadFileKnownLimitation``.
3. `wait_for_download` — a *third*, unrelated incompatibility
   (``PlaywrightDriver`` has no download-handling wiring at all):
   ``TestWaitForDownloadKnownLimitation``.

`await_keypress` is architecturally not a browser action at all (reads OS
stdin) — ``TestAwaitKeypressIsNotABrowserAction`` proves `driver` plays no
role, it is not a "limitation" to document.

See ``sdd/tasks/completed/TASK-2408-*.md``'s Codebase Contract "SCOPE
CORRECTION" for the full, empirically-verified rationale behind every
class in this module.
"""

from __future__ import annotations

import os
import shutil

import pytest
from parrot_tools.browsing.toolkit import WebBrowsingToolkit
from parrot_tools.business_automation.toolkit import _credential_resolver_from_broker
from parrot_tools.scraping import session_actions
from parrot_tools.scraping.drivers.playwright_config import PlaywrightConfig
from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver
from parrot_tools.scraping.executor import execute_plan_steps
from parrot_tools.scraping.models import (
    AwaitBrowserEvent,
    AwaitHuman,
    AwaitKeyPress,
    GetCookies,
    UploadFile,
    WaitForDownload,
)
from parrot_tools.scraping.plan import ScrapingPlan
from parrot_tools.scraping.session_actions import (
    exec_await_browser_event,
    exec_await_human,
    exec_await_keypress,
    exec_get_cookies,
    exec_upload_file,
    exec_wait_for_download,
)

from tests.business_automation.fixtures.broker import fake_broker
from tests.scraping.fixtures.local_site import (
    SESSION_COOKIE_NAME,
    TEST_PASSWORD,
    TEST_USERNAME,
    local_fixture_site,
)
from tests.scraping.fixtures.real_driver import real_playwright_driver

__all__ = ["fake_broker", "local_fixture_site", "real_playwright_driver"]  # re-exported fixtures


# ── Obscura opt-in fixture (FEAT-530, TASK-2880) ────────────────────


@pytest.fixture
async def real_obscura_driver(unused_tcp_port):
    """Yield a real, started :class:`PlaywrightDriver` connected over CDP
    to a real, supervised Obscura v0.2.2 process.

    Skips (never fails) the requesting test when no Obscura binary is
    configured — via the ``OBSCURA_BINARY`` environment variable or a
    ``obscura`` executable resolvable on ``PATH`` — or when the real
    process fails to start/connect. This mirrors ``real_playwright_driver``
    exactly, but for the Obscura-backed CDP connection mode instead of a
    launched Chromium (spec's Test Data/Fixtures: "operator-provided
    binary pinned to v0.2.2 ... ordinary unit tests must mock process and
    Playwright APIs").
    """
    binary = os.environ.get("OBSCURA_BINARY") or shutil.which("obscura")
    if not binary:
        pytest.skip(
            "No Obscura binary configured (set OBSCURA_BINARY or install "
            "'obscura' on PATH) — opt-in real-Obscura fixture skipped."
        )

    from parrot.mcp.obscura import ObscuraProcessConfig, ObscuraProcessManager

    manager = ObscuraProcessManager(
        ObscuraProcessConfig(
            binary_path=binary,
            port=unused_tcp_port,
            # Required for the local fixture site (loopback, non-standard
            # port) — never enabled by default in general deployments.
            allow_private_network=True,
        )
    )
    try:
        endpoint = await manager.start()
    except RuntimeError as exc:
        pytest.skip(f"Real Obscura process failed to start: {exc}")
        return

    driver = PlaywrightDriver(
        PlaywrightConfig(engine="obscura", cdp_endpoint_url=endpoint)
    )
    try:
        await driver.start()
    except Exception as exc:  # noqa: BLE001 — any connection failure means "skip", not "fail"
        await manager.stop()
        pytest.skip(f"Real Obscura CDP connection failed: {exc}")
        return

    try:
        yield driver
    finally:
        await driver.quit()
        await manager.stop()


class TestFakeBroker:
    """Fixture-level check — no browser, no network."""

    async def test_resolves_deterministically(self, fake_broker):
        resolver = _credential_resolver_from_broker(fake_broker, "test-user-id")

        class _FakeAction:
            credential_provider = "acme"

        result = await resolver(_FakeAction())
        assert result == (TEST_USERNAME, "testpass123")


class TestAuthenticatedFlowEndToEnd:
    """AC-17: ``test_authenticated_flow_end_to_end`` — login survives
    across the plan's steps, against a real browser and a real broker."""

    async def test_login_survives_across_flow_nodes(self, local_fixture_site, fake_broker, real_playwright_driver):
        resolver = _credential_resolver_from_broker(fake_broker, "test-user-id")
        plan = ScrapingPlan(
            url=str(local_fixture_site.make_url("/")),
            objective="Log into acme-books and reach the dashboard",
            steps=[
                {"action": "navigate", "url": "/login"},
                {"action": "authenticate", "method": "form", "credential_provider": "acme"},
            ],
            selectors=[{"name": "welcome", "selector": "body", "extract_type": "text"}],
        )

        result = await execute_plan_steps(
            real_playwright_driver,
            plan=plan,
            credential_resolver=resolver,
        )

        assert result.success, result.error_message
        assert f"Welcome, {TEST_USERNAME}" in result.extracted_data.get("welcome", "")


class TestStubRegressionFullPlan:
    """AC-17: ``test_stub_regression_full_plan``, scaled to the **2**
    action types that genuinely produce a real, independently-verifiable
    effect through ``PlaywrightDriver`` — ``authenticate`` and
    ``set_cookies``. ``set_cookies`` is verified via the fixture site's
    own ``/cookie-check`` HTTP route (the real `Cookie` header the browser
    actually sends on its next request) rather than via ``get_cookies``,
    which is itself one of the broken action types this module documents
    separately below."""

    async def test_two_actions_produce_real_effects(self, local_fixture_site, fake_broker, real_playwright_driver):
        resolver = _credential_resolver_from_broker(fake_broker, "test-user-id")
        plan = ScrapingPlan(
            url=str(local_fixture_site.make_url("/")),
            objective="Exercise authenticate and set_cookies for real",
            steps=[
                {"action": "navigate", "url": "/login"},
                {"action": "authenticate", "method": "form", "credential_provider": "acme"},
                {"action": "set_cookies", "cookies": [{"name": "test_flag", "value": "1"}]},
                {"action": "navigate", "url": "/cookie-check"},
            ],
            selectors=[{"name": "cookie_header", "selector": "body", "extract_type": "text"}],
        )

        result = await execute_plan_steps(
            real_playwright_driver,
            plan=plan,
            credential_resolver=resolver,
        )

        assert result.success, result.error_message
        assert not result.metadata.get("step_errors")

        cookie_header = result.extracted_data.get("cookie_header", "")
        # authenticate: the real session cookie our own login set is still
        # sent by the browser on this later, unrelated request.
        assert "acme_session" in cookie_header
        # set_cookies: the custom cookie written via document.cookie is
        # actually observed server-side on the browser's next request —
        # verified through a real HTTP round trip, not the broken
        # get_cookies mechanism.
        assert "test_flag=1" in cookie_header


class TestSeleniumStyleScriptIncompatibilityWithPlaywright:
    """ONE root cause, empirically confirmed, manifesting in 3 of the
    original 8 formerly-stubbed action types: ``get_cookies``,
    ``await_human`` (selector condition), and ``await_browser_event``.

    Each calls ``driver.execute_script()`` with a JS snippet written in a
    Selenium-oriented style:

    - A **bare, unwrapped top-level ``return`` statement** — e.g.
      ``exec_get_cookies``'s ``"return document.cookie;"``
      (session_actions.py:302), ``_check_human_condition``'s ``"return
      document.querySelectorAll(...).length;"`` (session_actions.py:444),
      and ``_check_browser_event_ready``'s
      ``"try{return ...}catch(e){return ...}"`` (session_actions.py:672).
      Selenium's ``execute_script`` implicitly wraps *any* script body in
      a function, so a bare ``return`` is legal there — Playwright's
      ``page.evaluate()`` does not, and raises
      ``SyntaxError: Illegal return statement``, reproduced directly
      against a real page for every one of the three snippets above.
    - **Selenium's ``arguments[N]`` convention** for passing extra
      arguments — ``_check_human_condition``'s script additionally uses
      ``arguments[0]``, which Playwright's ``evaluate(script, arg)`` does
      not support at all (it expects a function taking a parameter, not a
      bare-script ``arguments`` array).

    None of the three functions crash: each wraps the call in
    ``try/except`` and returns its documented safe-failure value
    (``{"cookies": []}`` / ``False`` / ``False``) — so this is a silent,
    complete loss of functionality against ``PlaywrightDriver``, not a
    visible error, discovered here only because these tests run a real
    browser instead of a mock. `_BROWSER_EVENT_JS` (the *inject* script for
    `await_browser_event`) is, by contrast, correctly IIFE-wrapped and
    works fine — only the later polling/clear scripts in each of the three
    functions are missing that wrapper. See this task's Completion Note
    for the single recommended follow-up bug covering all three.
    """

    async def test_get_cookies_returns_empty_due_to_bare_return(self, local_fixture_site, real_playwright_driver):
        await real_playwright_driver.navigate(str(local_fixture_site.make_url("/dashboard")))

        result = await exec_get_cookies(real_playwright_driver, GetCookies())

        assert result == {"cookies": []}, (
            "exec_get_cookies unexpectedly returned real cookies via "
            "PlaywrightDriver — the known bare-return JS incompatibility "
            "may have been fixed; if so, update this test (and "
            "TestStubRegressionFullPlan, which currently verifies "
            "set_cookies via /cookie-check specifically to work around "
            "this) rather than leaving a stale assertion."
        )

    async def test_await_human_selector_times_out_due_to_bare_return_and_arguments(
        self, local_fixture_site, real_playwright_driver
    ):
        await real_playwright_driver.navigate(str(local_fixture_site.make_url("/dashboard")))
        action = AwaitHuman(target="h1", condition_type="selector", timeout=2)

        result = await exec_await_human(real_playwright_driver, action)

        assert result is False, (
            "exec_await_human(condition_type='selector') unexpectedly "
            "succeeded via PlaywrightDriver even though the target "
            "selector ('h1') is genuinely present on the page — the known "
            "bare-return/arguments[0] JS incompatibility may have been "
            "fixed; if so, update this test rather than leaving a stale "
            "assertion."
        )

    async def test_await_browser_event_times_out_due_to_bare_return(self, local_fixture_site, real_playwright_driver):
        await real_playwright_driver.navigate(str(local_fixture_site.make_url("/dashboard")))
        action = AwaitBrowserEvent(timeout=2)

        result = await exec_await_browser_event(real_playwright_driver, action)

        assert result is False, (
            "exec_await_browser_event unexpectedly succeeded via "
            "PlaywrightDriver — the known bare-return JS incompatibility "
            "in _check_browser_event_ready may have been fixed; if so, "
            "update this test rather than leaving a stale assertion."
        )


class TestUploadFileKnownLimitation:
    """Documents (does not fix) ``exec_upload_file``'s real, empirically-
    verified incompatibility with ``PlaywrightDriver`` — a *different*
    root cause from the bare-return class above: Playwright hard-rejects
    ``.fill()`` on file inputs. See this task's Completion Note for the
    recommended follow-up bug against ``PlaywrightDriver.fill()``."""

    async def test_upload_file_returns_false_with_playwright(
        self, local_fixture_site, real_playwright_driver, tmp_path
    ):
        upload_target = tmp_path / "notes.txt"
        upload_target.write_text("hello acme-books")

        await real_playwright_driver.navigate(str(local_fixture_site.make_url("/upload")))
        action = UploadFile(selector="#file-input", file_path=str(upload_target))

        result = await exec_upload_file(real_playwright_driver, action)

        assert result is False, (
            "exec_upload_file unexpectedly succeeded via PlaywrightDriver — "
            "the known Playwright file-input .fill() restriction may have "
            "been fixed; if so, update this test and this task's Completion "
            "Note rather than leaving a stale 'known limitation' assertion."
        )


class TestWaitForDownloadKnownLimitation:
    """Documents (does not fix) ``exec_wait_for_download``'s real,
    empirically-verified incompatibility with ``PlaywrightDriver`` — a
    *third*, unrelated root cause: the driver has no download-handling
    wiring, so nothing a real browser click/navigate does ever reaches the
    filesystem path this action polls. See this task's Completion Note for
    the recommended follow-up bug against ``PlaywrightDriver``."""

    async def test_wait_for_download_times_out_with_playwright(
        self, local_fixture_site, real_playwright_driver, tmp_path
    ):
        action = WaitForDownload(download_path=str(tmp_path), timeout=2)

        result = await exec_wait_for_download(real_playwright_driver, action)

        assert result is False, (
            "exec_wait_for_download unexpectedly succeeded via "
            "PlaywrightDriver — the known missing download-handling wiring "
            "may have been fixed; if so, update this test and this task's "
            "Completion Note rather than leaving a stale assertion."
        )
        assert list(tmp_path.iterdir()) == [], "no file should ever have reached the polled directory"


class TestAwaitKeypressIsNotABrowserAction:
    """Proves ``exec_await_keypress`` never touches ``driver`` — it is a
    console/stdin-only mechanism, architecturally unrelated to which
    browser (if any) is configured; not a "limitation" to document, just a
    scope mismatch with "real-browser regression test." Stdin is simulated
    via the exact monkeypatch pattern FEAT-453's own mocked-driver tests
    already use (``test_session_actions_waits.py``)."""

    async def test_driver_state_unchanged_after_keypress(self, local_fixture_site, real_playwright_driver, monkeypatch):
        await real_playwright_driver.navigate(str(local_fixture_site.make_url("/login")))
        url_before = real_playwright_driver.current_url

        monkeypatch.setattr(session_actions.select, "select", lambda *a, **kw: ([True], [], []))
        monkeypatch.setattr(session_actions.sys.stdin, "readline", lambda: "go\n")

        result = await exec_await_keypress(real_playwright_driver, AwaitKeyPress())

        assert result is True
        assert (
            real_playwright_driver.current_url == url_before
        ), "the real driver's page must be completely untouched by an action that is architecturally console-only"


class TestNoThirdPartyContact:
    def test_local_fixture_site_is_local(self, local_fixture_site):
        host = local_fixture_site.make_url("/").host
        assert host in ("127.0.0.1", "localhost", "::1")


# ── Obscura compatibility validation (FEAT-530, TASK-2880) ──────────
#
# Opt-in: every test below requires a real Linux Obscura v0.2.2 binary
# (`real_obscura_driver` fixture) and is skipped cleanly without one —
# these prove nothing is assumed from CDP protocol naming alone (spec
# Known Risks/Gotchas). See docs/obscura-headless-browser.md for the
# full compatibility matrix these exercise a representative slice of.


class TestObscuraPlaywrightFixtureSite:
    """`test_obscura_playwright_fixture_site`: the same navigation, DOM,
    waits, script, screenshot, and extraction calls the Playwright driver
    integration tests already exercise, run through the Obscura-backed
    `PlaywrightDriver` (CDP mode) instead of a launched Chromium."""

    async def test_obscura_playwright_fixture_site(self, local_fixture_site, real_obscura_driver, tmp_path):
        await real_obscura_driver.navigate(str(local_fixture_site.make_url("/login")))
        assert "acme-books" in await real_obscura_driver.get_page_source()

        await real_obscura_driver.fill("#username", TEST_USERNAME)
        await real_obscura_driver.fill("#password", TEST_PASSWORD)
        await real_obscura_driver.click("button[type=submit]")
        await real_obscura_driver.wait_for_load_state("load")

        assert TEST_USERNAME in await real_obscura_driver.get_text("body")

        screenshot_path = tmp_path / "obscura-dashboard.png"
        shot = await real_obscura_driver.screenshot(str(screenshot_path))
        assert shot, "screenshot() must return non-empty bytes"
        assert screenshot_path.exists()

        assert await real_obscura_driver.evaluate("1 + 1") == 2

        # Cookie check: the real session cookie our own login just set is
        # observable via document.cookie through the Obscura-backed page.
        cookies = await real_obscura_driver.evaluate("document.cookie")
        assert SESSION_COOKIE_NAME in cookies


class TestObscuraScrapingPlanDriverParity:
    """`test_obscura_scraping_plan_driver_parity`: runs the SAME
    authenticated scraping plan as `TestAuthenticatedFlowEndToEnd`
    (real Chromium) through the shared `execute_plan_steps` executor,
    but against the Obscura-backed driver — a driver-level parity
    comparison for the representative scraping-plan action set."""

    async def test_obscura_scraping_plan_driver_parity(
        self, local_fixture_site, fake_broker, real_obscura_driver
    ):
        resolver = _credential_resolver_from_broker(fake_broker, "test-user-id")
        plan = ScrapingPlan(
            url=str(local_fixture_site.make_url("/")),
            objective="Log into acme-books and reach the dashboard",
            steps=[
                {"action": "navigate", "url": "/login"},
                {"action": "authenticate", "method": "form", "credential_provider": "acme"},
            ],
            selectors=[{"name": "welcome", "selector": "body", "extract_type": "text"}],
        )

        result = await execute_plan_steps(
            real_obscura_driver, plan=plan, credential_resolver=resolver
        )

        assert result.success, result.error_message
        assert f"Welcome, {TEST_USERNAME}" in result.extracted_data.get("welcome", "")


class TestObscuraBrowsingToolkitCatalogFlow:
    """`test_obscura_browsing_toolkit_catalog_flow`: a representative
    catalogued `WebBrowsingToolkit` login flow against the Obscura-backed
    driver, injected directly via the toolkit's `_session_driver` seam —
    the same test-only injection pattern already used by
    `test_toolkit.py::test_start_creates_session_driver`.

    KNOWN GAP (documented, not fixed — out of this task's scope):
    `DriverRegistry` (`parrot_tools.scraping.driver_context`) has no
    ``"obscura"`` entry, so `WebBrowsingToolkit(driver_type="obscura")`
    cannot currently self-construct its own session driver via
    `start()`/`DriverRegistry.get()` end-to-end. This test validates
    catalogued execution against a real Obscura-backed driver directly;
    it does NOT exercise `DriverRegistry` dispatch. See this task's
    Completion Note for the full gap description and recommended
    follow-up task.
    """

    async def test_obscura_browsing_toolkit_catalog_flow(
        self, local_fixture_site, real_obscura_driver, tmp_path
    ):
        toolkit = WebBrowsingToolkit(catalog_dir=str(tmp_path / "catalog"))
        toolkit._session_driver = real_obscura_driver
        toolkit._session_based = True

        await toolkit.register_site(
            base_url=str(local_fixture_site.make_url("/")), name="acme-books"
        )
        await toolkit.save_site_action(
            site="acme-books",
            name="login",
            description="Log into acme-books",
            steps=[
                {"action": "navigate", "url": "/login"},
                {"action": "fill", "selector": "#username", "value": TEST_USERNAME},
                {"action": "fill", "selector": "#password", "value": TEST_PASSWORD},
                {"action": "click", "selector": "button[type=submit]"},
                {
                    "action": "extract",
                    "selector": "body",
                    "extract_type": "text",
                    "extract_name": "welcome",
                },
            ],
        )

        result = await toolkit.run_site_action(site="acme-books", action="login")

        assert result["success"], result
        assert TEST_USERNAME in result["extracted_data"].get("welcome", "")
