"""FEAT-622 M8 (R7 regression): ``/tools/{slug}/execute`` cannot run a host write tool."""

from __future__ import annotations

from aiohttp import web
from parrot.handlers.studio.testing import StudioToolExecuteHandler

from ._host_probe import host_plugins, probe_counters  # noqa: F401
from .test_testing_surface import _decode, _make_handler, _unwrap


def _execute(slug: str):
    return _make_handler(
        StudioToolExecuteHandler,
        web.Application(),
        method="POST",
        match_info={"slug": slug},
        json_body={"args": {}},
    )


async def test_execute_refuses_host_write(host_plugins):  # noqa: F811
    handler = _execute("tp_probe_tool_write")
    response = await _unwrap(StudioToolExecuteHandler.post)(handler)
    assert response.status == 403 and (await _decode(response))["code"] == "confirmation_required"
    assert probe_counters()["written"] == 0


async def test_execute_still_runs_host_read_tool(host_plugins):  # noqa: F811
    handler = _execute("tp_probe_tool")
    response = await _unwrap(StudioToolExecuteHandler.post)(handler)
    assert response.status == 200
