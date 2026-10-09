"""PA-13: ``app[STUDIO_EGRESS_GUARD]`` is the host switch of the tools' egress guard."""

from __future__ import annotations

import pytest
from aiohttp import web

import parrot.tools.egress as egress
from parrot.handlers.studio import setup_studio_routes
from parrot.handlers.studio.hooks import STUDIO_EGRESS_GUARD

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset():
    yield
    egress.configure(False)


async def _start_hooks(app: web.Application) -> None:
    from parrot.handlers.studio import _apply_egress_guard

    assert _apply_egress_guard in app.on_startup
    await _apply_egress_guard(app)


async def test_the_host_key_turns_the_guard_on_at_startup():
    app = web.Application()
    setup_studio_routes(app)
    app[STUDIO_EGRESS_GUARD] = True
    await _start_hooks(app)
    assert egress.is_enabled() is True


async def test_without_the_key_the_guard_stays_off():
    egress.configure(True)  # a previous host: a fresh app without the key turns it off again
    app = web.Application()
    setup_studio_routes(app)
    await _start_hooks(app)
    assert egress.is_enabled() is False


async def test_the_boot_probe_is_importable():
    assert STUDIO_EGRESS_GUARD == "studio_egress_guard"
    assert "egress_guard" in egress.FEATURES
