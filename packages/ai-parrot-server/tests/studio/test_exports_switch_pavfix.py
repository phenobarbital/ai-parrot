"""PA-11: ``app[STUDIO_EXPORTS_STORE_ONLY]`` is the host opt-in of the export tools' store-only mode (default off)."""

from __future__ import annotations

import pytest
from aiohttp import web

import parrot.tools.exports_mode as exports_mode
from parrot.handlers.studio import setup_studio_routes
from parrot.handlers.studio.hooks import STUDIO_EXPORTS_STORE_ONLY

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset():
    yield
    exports_mode.configure(False)


async def _start(app: web.Application) -> None:
    from parrot.handlers.studio import _apply_exports_mode

    assert _apply_exports_mode in app.on_startup
    await _apply_exports_mode(app)


async def test_the_host_key_turns_the_mode_on_at_startup():
    app = web.Application()
    setup_studio_routes(app)
    app[STUDIO_EXPORTS_STORE_ONLY] = True
    await _start(app)
    assert exports_mode.is_enabled() is True


async def test_without_the_key_the_mode_stays_off():
    exports_mode.configure(True)  # a previous host: a fresh app without the key turns it off again
    app = web.Application()
    setup_studio_routes(app)
    await _start(app)
    assert exports_mode.is_enabled() is False


async def test_the_boot_probe_is_importable():
    assert STUDIO_EXPORTS_STORE_ONLY == "studio_exports_store_only"
    assert "exports_store_only" in exports_mode.FEATURES
