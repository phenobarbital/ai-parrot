import sys

import aiohttp
import click
import pytest
import yaml
from aiohttp import web
from pydantic import ValidationError

from parrot.knowledge.wiki.actor import current_actor
from parrot.knowledge.wiki.serve import (
    WikiServerConfig,
    _import_server_stack,
    actor_middleware,
    build_key_store,
)


def test_config_validation(tmp_path):
    p = tmp_path / "server.yaml"
    p.write_text(yaml.safe_dump({"wikis": {"parrot": {"root": "/srv/p"}, "issues": {"root": "/srv/i"}}}))
    assert set(WikiServerConfig.from_yaml(p).wikis) == {"parrot", "issues"}
    with pytest.raises(ValidationError):
        WikiServerConfig(wikis={"bad name": {"root": "/x"}})
    with pytest.raises(ValidationError):
        WikiServerConfig(default_actor="nobody", wikis={"w": {"root": "/x"}})


def test_missing_server_stack(monkeypatch):
    monkeypatch.setitem(sys.modules, "parrot.mcp.transports.streamable_http", None)
    with pytest.raises(click.ClickException, match=r"ai-parrot\[wikitoolkit-server\]"):
        _import_server_stack()


async def test_actor_middleware():
    async def echo(request):
        return web.json_response({"actor": current_actor()})

    app = web.Application(middlewares=[actor_middleware])
    app["wiki_default_actor"] = "agent:unknown"
    app.router.add_get("/", echo)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    base = f"http://127.0.0.1:{runner.addresses[0][1]}/"
    try:
        async with aiohttp.ClientSession() as s:
            assert (await (await s.get(base)).json())["actor"] == "agent:unknown"
            r = await s.get(base, headers={"X-Wiki-Actor": "human:alice"})
            assert (await r.json())["actor"] == "human:alice"
            assert (await s.get(base, headers={"X-Wiki-Actor": "bad"})).status == 400
        assert current_actor() == "agent:mcp"
    finally:
        await runner.cleanup()


def test_key_store():
    pytest.importorskip("parrot.mcp.transports.streamable_http")
    ks = build_key_store("t0k3n")
    assert ks.validate_key("Bearer t0k3n").user_id.startswith("token:") and ks.validate_key("t0k3n")
    assert ks.validate_key("Bearer nope") is None
