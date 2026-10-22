"""FEAT-605 W1.5 — D3: replace over an ownerless or foreign agent is refused, without disclosure."""
from __future__ import annotations

import textwrap
from types import SimpleNamespace

import parrot.registry as registry_pkg
import pytest
from aiohttp import web
from navigator_session.data import SessionData
from parrot.bots.basic import BasicBot
from parrot.handlers.studio import drafts as drafts_module
from parrot.handlers.studio import setup_studio_routes
from parrot.registry.registry import AgentRegistry, BotConfig

DRAFT_SRC = textwrap.dedent("""
    from parrot.registry import agent_registry
    from parrot.bots.basic import BasicBot


    @agent_registry.register_bot_decorator(name="x", replace=True)
    class XDraftAgent(BasicBot):
        \"\"\"Activated draft agent.\"\"\"
        pass
    """)


@web.middleware
async def _session_mw(request, handler):
    uid = request.headers["X-Uid"]
    request["NAV_SESSION"] = SessionData(
        data={"session": {"user_id": uid, "groups": [], "superuser": uid == "root"}}
    )
    request["authenticated"] = True
    return await handler(request)


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Real registry + on-disk draft owned by 'B'; draft rows are an in-memory data layer."""
    monkeypatch.setattr(drafts_module, "AGENTS_DIR", tmp_path)
    registry = AgentRegistry(agents_dir=tmp_path)
    monkeypatch.setattr(registry_pkg, "agent_registry", registry)

    draft_dir = tmp_path / drafts_module.DRAFTS_SUBDIR
    draft_dir.mkdir()
    draft_file = draft_dir / "x.py"
    draft_file.write_text(DRAFT_SRC)
    table = {
        "x": SimpleNamespace(
            name="x", file_path=str(draft_file), owner_user_id="B", base_class="BasicBot", status="validated"
        )
    }

    async def get_row(self, name):
        return table.get(name)

    async def upsert(self, **fields):
        row = table.get(fields["name"])
        for key, value in fields.items():
            setattr(row, key, value)
        return row

    monkeypatch.setattr(drafts_module._StudioDraftsMixin, "_get_draft_row", get_row)
    monkeypatch.setattr(drafts_module._StudioDraftsMixin, "_upsert_draft_row", upsert)

    app = web.Application(middlewares=[_session_mw])
    app["bot_manager"] = SimpleNamespace(registry=registry)
    setup_studio_routes(app)
    return SimpleNamespace(app=app, registry=registry, draft_file=draft_file)


def _register_existing(registry: AgentRegistry, created_by: str | None) -> None:
    config = {} if created_by is None else {"created_by": created_by}
    registry.register(
        "x", BasicBot, bot_config=BotConfig(name="x", class_name="BasicBot", module="parrot.bots.basic", config=config)
    )


async def _activate(client, uid: str, replace: bool = True):
    return await client.post("/api/v1/astudio/drafts/x/activate", json={"replace": replace}, headers={"X-Uid": uid})


async def test_replace_ownerless_refused(aiohttp_client, env):
    _register_existing(env.registry, None)
    client = await aiohttp_client(env.app)
    resp = await _activate(client, "B")
    body = await resp.json()
    assert resp.status == 409 and body["code"] == "name_taken"
    assert env.draft_file.exists()  # nothing moved


async def test_replace_foreign_refused(aiohttp_client, env):
    _register_existing(env.registry, "A")
    client = await aiohttp_client(env.app)
    resp = await _activate(client, "B")
    body = await resp.json()
    assert resp.status == 409 and body["code"] == "name_taken"
    text = str(body)
    assert "owner" not in text.lower() and "'A'" not in text


async def test_replace_without_flag_is_name_taken(aiohttp_client, env):
    _register_existing(env.registry, "B")
    client = await aiohttp_client(env.app)
    resp = await _activate(client, "B", replace=False)
    assert resp.status == 409 and (await resp.json())["code"] == "name_taken"


async def test_owner_replace_still_works(aiohttp_client, env):
    _register_existing(env.registry, "B")
    client = await aiohttp_client(env.app)
    resp = await _activate(client, "B")
    assert resp.status == 200, await resp.text()
    assert (await resp.json())["activated"] is True
