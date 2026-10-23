"""Tests for the ``local_fixture_site`` fixture (FEAT-455, Module 1).

Plain ``aiohttp.ClientSession`` round-trips only — no browser involved.
This proves the fixture site itself works BEFORE any real-browser test
(TASK-2408/2409) relies on it.
"""

import aiohttp

from .fixtures.local_site import (
    DOWNLOAD_CONTENT,
    TEST_PASSWORD,
    TEST_USERNAME,
    local_fixture_site,
)

__all__ = ["local_fixture_site"]  # re-exported fixture, used as a parameter below


class TestLoginFlow:
    async def test_login_page_renders_form(self, local_fixture_site):
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
            resp = await session.get(local_fixture_site.make_url("/login"))
            assert resp.status == 200
            text = await resp.text()
            assert 'id="username"' in text
            assert 'id="password"' in text

    async def test_login_success_sets_cookie_and_redirects(self, local_fixture_site):
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
            resp = await session.post(
                local_fixture_site.make_url("/login"),
                data={"username": TEST_USERNAME, "password": TEST_PASSWORD},
            )
            assert resp.status == 200  # aiohttp ClientSession follows the 302 by default
            assert resp.url.path == "/dashboard"
            text = await resp.text()
            assert f"Welcome, {TEST_USERNAME}" in text

    async def test_login_failure_shows_error(self, local_fixture_site):
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
            resp = await session.post(
                local_fixture_site.make_url("/login"),
                data={"username": "wrong", "password": "wrong"},
            )
            text = await resp.text()
            assert "error" in text.lower()

    async def test_dashboard_requires_session(self, local_fixture_site):
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
            resp = await session.get(local_fixture_site.make_url("/dashboard"))
            assert resp.status in (401, 403, 302)

    async def test_session_survives_a_second_request(self, local_fixture_site):
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
            await session.post(
                local_fixture_site.make_url("/login"),
                data={"username": TEST_USERNAME, "password": TEST_PASSWORD},
            )
            # A second, separate GET using the SAME session's cookie jar
            # proves the session mechanism itself (not just the redirect
            # response body) actually persists the login.
            resp = await session.get(local_fixture_site.make_url("/dashboard"))
            assert resp.status == 200
            text = await resp.text()
            assert f"Welcome, {TEST_USERNAME}" in text


class TestUpload:
    async def test_upload_echoes_filename_and_size(self, local_fixture_site):
        payload = b"hello acme-books"
        form = aiohttp.FormData()
        form.add_field("file", payload, filename="notes.txt", content_type="text/plain")

        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
            resp = await session.post(local_fixture_site.make_url("/upload"), data=form)
            assert resp.status == 200
            body = await resp.json()
            assert body["filename"] == "notes.txt"
            assert body["bytes"] == len(payload)


class TestDownload:
    async def test_download_is_deterministic(self, local_fixture_site):
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
            a = await (await session.get(local_fixture_site.make_url("/download/report.pdf"))).read()
            b = await (await session.get(local_fixture_site.make_url("/download/report.pdf"))).read()
            assert a == b
            assert a == DOWNLOAD_CONTENT

    async def test_download_sets_content_disposition(self, local_fixture_site):
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
            resp = await session.get(local_fixture_site.make_url("/download/report.pdf"))
            assert "attachment" in resp.headers.get("Content-Disposition", "")


class TestCookieCheck:
    async def test_echoes_cookie_header(self, local_fixture_site):
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
            await session.post(
                local_fixture_site.make_url("/login"),
                data={"username": TEST_USERNAME, "password": TEST_PASSWORD},
            )
            resp = await session.get(local_fixture_site.make_url("/cookie-check"))
            text = await resp.text()
            assert "acme_session" in text

    async def test_no_cookie_when_never_logged_in(self, local_fixture_site):
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
            resp = await session.get(local_fixture_site.make_url("/cookie-check"))
            text = await resp.text()
            assert text == ""


class TestNoThirdPartyContact:
    def test_all_routes_are_local(self, local_fixture_site):
        """Sanity guard: the fixture site's own bound URL must be a local
        loopback address — this fixture must never resolve to a real host."""
        host = local_fixture_site.make_url("/").host
        assert host in ("127.0.0.1", "localhost", "::1")
