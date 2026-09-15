"""Tests for LoopbackRestChannel against the real library routes on a UnixSite (TASK-3202)."""

from __future__ import annotations

import pytest
from aiohttp import web

from parrot.flows.dev_loop.commands import register_command_routes
from parrot.integrations.devloop.bridge import LoopbackRestChannel

from .fake_child import _StubRunner, _auth


@pytest.fixture
async def child_site(tmp_path):
    """A real aiohttp UnixSite serving the library's own gate/cancel routes."""
    app = web.Application(middlewares=[_auth])
    runner = _StubRunner()
    register_command_routes(app, runner)
    app_runner = web.AppRunner(app)
    await app_runner.setup()
    sock = str(tmp_path / "c.sock")
    import os

    os.environ["PARROT_DEVLOOP_COMMAND_TOKEN"] = "tok"
    site = web.UnixSite(app_runner, sock)
    await site.start()
    try:
        yield sock
    finally:
        await app_runner.cleanup()
        os.environ.pop("PARROT_DEVLOOP_COMMAND_TOKEN", None)


@pytest.mark.asyncio
async def test_status_mapping(child_site):
    ch = LoopbackRestChannel(f"unix://{child_site}", token="tok")
    assert (await ch.resolve_gate("r", "g1", resolution="approved", resolved_by="slack:T:U")).ok
    assert (await ch.resolve_gate("r", "g1", resolution="approved", resolved_by="x")).reason == "already_resolved"
    assert (await ch.resolve_gate("r", "oq-1", resolution="approved", resolved_by="x")).reason == "answers_required"
    assert (await ch.cancel("r", requested_by="x")).ok
    assert await LoopbackRestChannel(f"unix://{child_site}", token="tok").probe()


@pytest.mark.asyncio
async def test_bad_token_is_unauthorized(child_site):
    result = await LoopbackRestChannel(f"unix://{child_site}", token="bad").cancel("r", requested_by="x")
    assert not result.ok and result.reason == "unauthorized" and result.status == 401


@pytest.mark.asyncio
async def test_answers_provided_resolves_open_questions_gate(child_site):
    ch = LoopbackRestChannel(f"unix://{child_site}", token="tok")
    result = await ch.resolve_gate("r", "oq-2", resolution="approved", resolved_by="x", answers={"q1": "a1"})
    assert result.ok


@pytest.mark.asyncio
async def test_unreachable(tmp_path):
    res = await LoopbackRestChannel(f"unix://{tmp_path}/none.sock", token="t").cancel("r", requested_by="x")
    assert not res.ok and res.reason == "unreachable" and res.status == 0


@pytest.mark.asyncio
async def test_probe_false_when_unreachable(tmp_path):
    assert not await LoopbackRestChannel(f"unix://{tmp_path}/none.sock", token="t").probe()
