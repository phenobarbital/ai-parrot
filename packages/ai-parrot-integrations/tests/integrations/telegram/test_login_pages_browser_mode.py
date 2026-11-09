"""FEAT-854 M6: executable round-trip checks for the dual-mode Telegram login pages."""

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from parrot.integrations.telegram.browser_login import BROWSER_COMPLETE_PATH, new_browser_state

async_playwright = pytest.importorskip(
    "playwright.async_api", reason="playwright is required for login-page browser tests"
).async_playwright

STATIC = Path(__file__).resolve().parents[3] / "src/parrot/integrations/telegram/static"
PAGE_ORIGIN = "https://login.example.test"
PARROT_ORIGIN = "https://parrot.example.test"
NAV_ORIGIN = "https://nav.example.test"
INIT_SCRIPT = """
window.__sendData = [];
window.Telegram = { WebApp: { ready(){}, expand(){}, close(){},
  sendData(d){ window.__sendData.push(d); }, initData: '' } };
"""


async def _fill_credentials(page, username="testuser", password="testpass"):
    """Set form credentials via JS (page.fill is unreliable on route-fulfilled pages)."""
    await page.evaluate(
        """([u, p]) => {
            document.getElementById('username').value = u;
            document.getElementById('password').value = p;
        }""",
        [username, password],
    )


@pytest.fixture
async def browser_page():
    """Create a browser page with mocked Telegram WebApp and static file routing."""
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium unavailable: {exc}")
        page = await browser.new_page()
        await page.add_init_script(INIT_SCRIPT)

        # Route static file requests (** matches query strings containing /)
        async def route_static(route):
            raw = route.request.url.split("/static/")[-1]
            fname = raw.split("?")[0]
            file_path = STATIC / fname
            if file_path.exists():
                await route.fulfill(path=str(file_path))
            else:
                await route.fulfill(status=404, body="Not Found")

        await page.route(f"{PAGE_ORIGIN}/static/**", route_static)

        # Route Telegram.org to avoid real network requests
        async def route_telegram(route):
            await route.fulfill(body="")

        await page.route("https://telegram.org/**", route_telegram)

        # Route Navigator auth endpoint (basic credentials)
        async def route_auth(route):
            await route.fulfill(
                json={
                    "user_id": "test-user-1",
                    "token": "test.jwt.token",
                    "display_name": "Test User",
                    "email": "test@example.com",
                },
                status=200,
            )

        await page.route(f"{NAV_ORIGIN}/api/v1/login**", route_auth)

        # Track POST requests to browser-complete
        page.complete_posts = []

        async def route_complete(route):
            if route.request.method == "POST":
                page.complete_posts.append(
                    {
                        "url": route.request.url,
                        "post_data": route.request.post_data,
                    }
                )
            await route.fulfill(
                json={"ok": True, "redirect_url": "https://t.me/TestBot"},
                status=200,
            )

        await page.route(f"{PAGE_ORIGIN}{BROWSER_COMPLETE_PATH}", route_complete)

        yield page
        await browser.close()


async def test_basic_browser_mode_posts_payload_not_senddata(browser_page):
    """Browser mode: POST to complete_url, no sendData, success panel with t.me link."""
    state = new_browser_state()
    complete_url = f"{PAGE_ORIGIN}{BROWSER_COMPLETE_PATH}"

    url = (
        f"{PAGE_ORIGIN}/static/login.html"
        f"?auth_url={NAV_ORIGIN}/api/v1/login"
        f"&return_mode=browser"
        f"&state={state}"
        f"&complete_url={complete_url}"
    )

    page = browser_page
    await page.goto(url)

    await _fill_credentials(page)
    await page.click("#submit-btn")

    # Wait for the POST to complete
    await page.wait_for_timeout(1000)

    # Should have exactly one POST to browser-complete
    assert len(page.complete_posts) == 1, f"Expected 1 POST, got {len(page.complete_posts)}"

    post = page.complete_posts[0]
    assert BROWSER_COMPLETE_PATH in post["url"]

    import json

    data = json.loads(post["post_data"])
    assert data["state"] == state
    assert data["auth_method"] == "basic"
    assert "token" in data

    # sendData should NOT have been called
    send_data = await page.evaluate("window.__sendData")
    assert send_data == [], f"Expected no sendData calls, got {send_data}"

    # Should show success panel with t.me link
    content = await page.content()
    assert "Success" in content
    assert "https://t.me/TestBot" in content


async def test_basic_legacy_mode_uses_senddata(browser_page):
    """Legacy mode (no browser params): use sendData, no POST."""
    page = browser_page

    url = f"{PAGE_ORIGIN}/static/login.html?auth_url={NAV_ORIGIN}/api/v1/login"
    await page.goto(url)

    await _fill_credentials(page)
    await page.click("#submit-btn")

    # Wait for the request to complete
    await page.wait_for_timeout(1000)

    # Should have zero POSTs to browser-complete
    assert len(page.complete_posts) == 0, f"Expected 0 POSTs, got {len(page.complete_posts)}"

    # sendData should have been called exactly once
    send_data = await page.evaluate("window.__sendData")
    assert len(send_data) == 1, f"Expected 1 sendData call, got {len(send_data)}"

    import json

    payload = json.loads(send_data[0])
    assert payload["auth_method"] == "basic"


async def test_browser_mode_sso_redirect_round_trip(browser_page):
    """Azure/Google SSO preserves return_mode/state/complete_url in redirect_uri."""
    page = browser_page
    state = new_browser_state()
    complete_url = f"{PAGE_ORIGIN}{BROWSER_COMPLETE_PATH}"

    # Track the Navigator redirect
    nav_requests = []

    async def handle_nav(route):
        nav_requests.append(route.request.url)
        # Simulate Navigator redirecting back with token
        redirect_uri = route.request.url.split("redirect_uri=")[1]
        from urllib.parse import unquote

        redirect_uri = unquote(redirect_uri)
        await route.fulfill(
            status=302,
            headers={"Location": f"{redirect_uri}&token=test.jwt.token"},
        )

    await page.route(f"{NAV_ORIGIN}/api/v1/auth/azure**", handle_nav)

    # Test Azure button
    url = (
        f"{PAGE_ORIGIN}/static/azure_login.html"
        f"?azure_auth_url={NAV_ORIGIN}/api/v1/auth/azure"
        f"&return_mode=browser"
        f"&state={state}"
        f"&complete_url={complete_url}"
    )
    await page.goto(url)

    # Click the Azure button
    await page.click(".btn-azure")
    await page.wait_for_timeout(1000)

    # Should have captured a Navigator request
    assert len(nav_requests) >= 1
    nav_url = nav_requests[0]

    # The redirect_uri should contain browser params
    parsed = urlsplit(nav_url)
    params = parse_qs(parsed.query)
    assert "redirect_uri" in params
    redirect_uri = params["redirect_uri"][0]

    # Parse the redirect_uri and verify browser params are preserved
    redirect_parsed = urlsplit(redirect_uri)
    redirect_params = parse_qs(redirect_parsed.query)

    assert redirect_params.get("return_mode") == ["browser"]
    assert redirect_params.get("state") == [state]
    assert redirect_params.get("complete_url") == [complete_url]

    # Now simulate the return with token
    return_url = f"{redirect_uri}&token=test.jwt.token"
    await page.goto(return_url)
    await page.wait_for_timeout(1000)

    # Should have POSTed to browser-complete
    assert len(page.complete_posts) == 1

    # sendData should NOT have been called
    send_data = await page.evaluate("window.__sendData")
    assert send_data == []


async def test_browser_mode_sso_context_failure(browser_page):
    """Missing/corrupt context or disallowed origin shows error, no POST, no sendData."""
    page = browser_page

    # Test (a): browser state but no return_mode
    state = new_browser_state()
    url = (
        f"{PAGE_ORIGIN}/static/login.html"
        f"?auth_url={NAV_ORIGIN}/api/v1/login"
        f"&state={state}"  # Has state but no return_mode
    )
    await page.goto(url)
    await _fill_credentials(page)
    await page.click("#submit-btn")
    await page.wait_for_timeout(500)

    # Should show error, no POST, no sendData
    content = await page.content()
    assert "Error" in content or "Invalid" in content
    assert len(page.complete_posts) == 0
    send_data = await page.evaluate("window.__sendData")
    assert send_data == []

    # Reset for next test
    page.complete_posts = []

    # Test (b): complete_url on non-allowed origin
    state = new_browser_state()
    bad_complete_url = f"{PARROT_ORIGIN}{BROWSER_COMPLETE_PATH}"
    url = (
        f"{PAGE_ORIGIN}/static/login.html"
        f"?auth_url={NAV_ORIGIN}/api/v1/login"
        f"&return_mode=browser"
        f"&state={state}"
        f"&complete_url={bad_complete_url}"
    )
    await page.goto(url)
    await _fill_credentials(page)
    await page.click("#submit-btn")
    await page.wait_for_timeout(500)

    # Should show error (origin not allowed)
    content = await page.content()
    assert "Error" in content or "Origin" in content or "Invalid" in content
    assert len(page.complete_posts) == 0
    send_data = await page.evaluate("window.__sendData")
    assert send_data == []

    # Reset for next test
    page.complete_posts = []

    # Test (c): wrong path in complete_url
    state = new_browser_state()
    bad_complete_url = f"{PAGE_ORIGIN}/api/auth/wrong"
    url = (
        f"{PAGE_ORIGIN}/static/login.html"
        f"?auth_url={NAV_ORIGIN}/api/v1/login"
        f"&return_mode=browser"
        f"&state={state}"
        f"&complete_url={bad_complete_url}"
    )
    await page.goto(url)
    await _fill_credentials(page)
    await page.click("#submit-btn")
    await page.wait_for_timeout(500)

    # Should show error (invalid endpoint)
    content = await page.content()
    assert "Error" in content or "Invalid" in content
    assert len(page.complete_posts) == 0
    send_data = await page.evaluate("window.__sendData")
    assert send_data == []
