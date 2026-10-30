"""FEAT-772 contract test for the inline /autonomous/admin login page (passkey sign-in markers)."""
from __future__ import annotations

from aiohttp import web
from parrot.autonomous.admin import admin_login_page


async def _page(aiohttp_client) -> str:
    app = web.Application()
    app.router.add_get("/autonomous/admin", admin_login_page)
    client = await aiohttp_client(app)
    resp = await client.get("/autonomous/admin")
    assert resp.status == 200
    assert resp.content_type == "text/html"
    return await resp.text()


async def test_page_keeps_basic_auth_login(aiohttp_client) -> None:
    body = await _page(aiohttp_client)
    assert "'X-Auth-Method': 'BasicAuth'" in body


async def test_page_offers_passkey_sign_in(aiohttp_client) -> None:
    body = await _page(aiohttp_client)
    assert 'autocomplete="username webauthn"' in body
    assert "/api/v1/auth/passkey/login/options" in body
    assert "'X-Auth-Method':'PasskeyAuth'" in body.replace(" ", "")
    assert 'id="passkeyBtn" hidden' in body
    assert 'href="/account/security"' in body
    assert "Sign in with a passkey" in body
    assert "Manage passkeys" in body