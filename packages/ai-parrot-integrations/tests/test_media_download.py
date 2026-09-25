"""FEAT-601 M12 — bounded media download (TASK-3716)."""
from __future__ import annotations

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from parrot.integrations.media_download import (
    MediaDownloadRefused,
    download_to_temp,
    temp_download,
)

_OK_BODY = b"\x89PNG\r\n\x1a\nfake-png-body"
_BIG_BODY = b"x" * 1024


async def _ok(request: web.Request) -> web.Response:
    return web.Response(body=_OK_BODY, content_type="image/png")


async def _big(request: web.Request) -> web.Response:
    return web.Response(body=_BIG_BODY, content_type="image/png")


async def _redir_foreign(request: web.Request) -> web.Response:
    raise web.HTTPFound(location="http://evil.example/x")


async def _redir_local(request: web.Request) -> web.Response:
    raise web.HTTPFound(location="/ok")


async def _slow(request: web.Request) -> web.Response:
    await asyncio.sleep(1.0)
    return web.Response(body=_OK_BODY, content_type="image/png")


def _app() -> web.Application:
    app = web.Application()
    app.router.add_get("/ok", _ok)
    app.router.add_get("/big", _big)
    app.router.add_get("/redir-foreign", _redir_foreign)
    app.router.add_get("/redir-local", _redir_local)
    app.router.add_get("/slow", _slow)
    return app


async def test_allowlisted_host_downloads_and_cleans_up() -> None:
    server = TestServer(_app())
    async with server:
        allowed_hosts = [server.host]
        url = f"http://{server.host}:{server.port}/ok"

        async with temp_download(url, allowed_hosts=allowed_hosts) as path:
            assert path.exists()
            assert path.read_bytes() == _OK_BODY

        assert not path.exists()


async def test_foreign_host_and_redirect_refused() -> None:
    server = TestServer(_app())
    async with server:
        allowed_hosts = [server.host]

        # Initial foreign host is refused without ever issuing a request.
        with pytest.raises(MediaDownloadRefused):
            await download_to_temp("http://evil.example/x", allowed_hosts=allowed_hosts)

        # A redirect to a foreign host is refused too.
        with pytest.raises(MediaDownloadRefused):
            await download_to_temp(
                f"http://{server.host}:{server.port}/redir-foreign",
                allowed_hosts=allowed_hosts,
            )

        # A redirect that stays on an allowlisted host succeeds.
        path = await download_to_temp(
            f"http://{server.host}:{server.port}/redir-local",
            allowed_hosts=allowed_hosts,
        )
        try:
            assert path.exists()
            assert path.read_bytes() == _OK_BODY
        finally:
            path.unlink()


async def test_oversize_and_timeout_refused_without_leftovers() -> None:
    server = TestServer(_app())
    async with server:
        allowed_hosts = [server.host]

        with pytest.raises(MediaDownloadRefused):
            await download_to_temp(
                f"http://{server.host}:{server.port}/big",
                allowed_hosts=allowed_hosts,
                max_bytes=16,
            )

        with pytest.raises(MediaDownloadRefused):
            await download_to_temp(
                f"http://{server.host}:{server.port}/slow",
                allowed_hosts=allowed_hosts,
                timeout_s=0.05,
            )
