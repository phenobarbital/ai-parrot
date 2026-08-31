"""E2E CRUD round-trip test for the Admin UI agent-management form
(FEAT-475, TASK-2589).

Exercises the REAL `ChatbotHandler.put`/`get`/`post`/`delete` code paths
(slugify/dedup, `include_disabled` filtering, diff-style update, delete)
against an in-memory `BotModel` persistence stand-in — infra-free, no
live Postgres/Redis, following the same pattern as
`tests/test_admin_status.py` and TASK-2583's
`tests/test_bots_include_disabled.py`:

- `ChatbotHandler.handler` (the `ConnectionHandler` class attribute set
  by `configure()`) is replaced by a stub async-context-manager factory,
  so `async with await db(self.request) as conn:` never attempts a real
  connection.
- `BotModel.insert`/`update`/`delete` are monkeypatched to mutate an
  in-memory dict keyed by name, instead of executing SQL against
  `Meta.connection`.
- `ChatbotHandler._get_db_agents`/`_get_db_agent` are monkeypatched to
  read from that same in-memory dict (mirrors TASK-2583's test harness).
- `ChatbotHandler._register_bot_into_manager` is monkeypatched to a
  no-op stub bot — the FEAT-133 reranker/parent_searcher factory
  sequence and `BotManager.create_bot`/`configure` machinery are out of
  scope for this UI-payload round-trip. `_provision_vector_store` needs
  no patch: with an empty `vector_store_config` (never set by this
  test's payloads) it returns ``{"status": "none"}`` without touching
  anything (handlers/bots.py:923-947).
- `ChatbotHandler._registry` is overridden to always return `None`, so
  every registry-existence check (`_check_duplicate`, `delete()`) short-
  circuits — there is no registry-backed agent in this test.

Every response body is validated against the codegen descriptors in
`parrot.server.ui.models` (`BotMutationResponse`, `BotsListResponse`) —
the exact shapes the Admin UI's `$lib/api/agents.ts` wrappers expect.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from parrot.handlers.bots import ChatbotHandler
from parrot.handlers.models.bots import BotModel
from parrot.server.ui.models import BotMutationResponse, BotsListResponse


class _StubConnCtx:
    """Stands in for the real DB connection's async context manager."""

    async def __aenter__(self):
        return SimpleNamespace()

    async def __aexit__(self, *exc):
        return False


class _StubConnFactory:
    """Stands in for `ChatbotHandler.handler` (a `ConnectionHandler`).

    `_put_database`/`_post_database`/`delete()` all do
    ``async with await db(self.request) as conn:`` — `db` must itself be
    an async callable returning an async context manager.
    """

    async def __call__(self, request):
        return _StubConnCtx()


@pytest.fixture
def db_store() -> dict[str, dict]:
    """In-memory {name: field-dict} standing in for the `ai_bots` table."""
    return {}


@pytest.fixture
def app_with_bots(monkeypatch, db_store):
    """aiohttp app wired to `ChatbotHandler` with an in-memory persistence
    stand-in — see module docstring for the full monkeypatch list."""

    async def _fake_insert(self):
        if not getattr(self, "chatbot_id", None):
            self.chatbot_id = uuid.uuid4()
        db_store[self.name] = self.to_dict()

    async def _fake_update(self):
        db_store[self.name] = self.to_dict()

    async def _fake_delete(self):
        db_store.pop(self.name, None)

    monkeypatch.setattr(BotModel, "insert", _fake_insert)
    monkeypatch.setattr(BotModel, "update", _fake_update)
    monkeypatch.setattr(BotModel, "delete", _fake_delete)

    async def _fake_get_db_agents(self, include_disabled: bool = False):
        agents = [BotModel(**data) for data in db_store.values()]
        if include_disabled:
            return agents
        return [a for a in agents if a.enabled]

    async def _fake_get_db_agent(self, name: str):
        data = db_store.get(name)
        return BotModel(**data) if data else None

    monkeypatch.setattr(ChatbotHandler, "_get_db_agents", _fake_get_db_agents)
    monkeypatch.setattr(ChatbotHandler, "_get_db_agent", _fake_get_db_agent)

    async def _fake_register_bot(self, bot_data, app):
        return SimpleNamespace(store=None)

    monkeypatch.setattr(
        ChatbotHandler, "_register_bot_into_manager", _fake_register_bot
    )
    # No registry-backed agent in this test — every existence/delete check
    # against the registry short-circuits.
    monkeypatch.setattr(ChatbotHandler, "_registry", property(lambda self: None))

    async def _fake_get_session(request, new=False):
        return {"session": {}}

    monkeypatch.setattr(
        "navigator.views.abstract.get_session", _fake_get_session
    )

    @web.middleware
    async def _mark_authenticated(request: web.Request, handler):
        request["authenticated"] = True
        return await handler(request)

    app = web.Application(middlewares=[_mark_authenticated])
    bot_manager = MagicMock()
    bot_manager.remove_bot = MagicMock()
    app["bot_manager"] = bot_manager
    ChatbotHandler.configure(app, "/api/v1/bots")
    # configure() sets cls.handler = ConnectionHandler(...) — override it
    # with the stub only after configure() has run (the attribute does
    # not exist on the class before that).
    monkeypatch.setattr(ChatbotHandler, "handler", _StubConnFactory())
    return app


CREATE_PAYLOAD = {
    "storage": "database",
    "name": "My Bot",
    "goal": "Resolve support tickets quickly.",
    "backstory": "I help users with support tickets.",
    "rationale": "I stay calm and professional.",
}


async def test_admin_ui_agent_crud_roundtrip(aiohttp_client, app_with_bots):
    """The full create -> list -> update -> list(include_disabled) ->
    delete -> 404 round-trip, validating every response shape against the
    codegen descriptors."""
    client = await aiohttp_client(app_with_bots)

    # 1. PUT: name "My Bot" -> slugified "my-bot", 201, BotMutationResponse.
    resp = await client.put("/api/v1/bots", json=CREATE_PAYLOAD)
    assert resp.status == 201
    body = await resp.json()
    mutation = BotMutationResponse.model_validate(body)
    assert mutation.name == "my-bot"
    assert mutation.message
    assert mutation.chatbot_id

    # 2. GET /api/v1/bots lists it.
    resp = await client.get("/api/v1/bots")
    assert resp.status == 200
    body = await resp.json()
    listing = BotsListResponse.model_validate(body)
    assert any(a.name == "my-bot" for a in listing.agents)

    # POST /api/v1/bots/my-bot {enabled: false} -> 200, diff-only update.
    resp = await client.post("/api/v1/bots/my-bot", json={"enabled": False})
    assert resp.status == 200
    body = await resp.json()
    mutation = BotMutationResponse.model_validate(body)
    assert mutation.name == "my-bot"

    # 3. GET /api/v1/bots hides the now-disabled agent by default...
    resp = await client.get("/api/v1/bots")
    body = await resp.json()
    listing = BotsListResponse.model_validate(body)
    assert not any(a.name == "my-bot" for a in listing.agents)

    # ...but ?include_disabled=true shows it, with enabled: false.
    resp = await client.get("/api/v1/bots?include_disabled=true")
    body = await resp.json()
    listing = BotsListResponse.model_validate(body)
    by_name = {a.name: a for a in listing.agents}
    assert by_name["my-bot"].enabled is False  # type: ignore[attr-defined]

    # 4. DELETE -> 200; subsequent GET by name -> 404.
    resp = await client.delete("/api/v1/bots/my-bot")
    assert resp.status == 200
    body = await resp.json()
    mutation = BotMutationResponse.model_validate(body)
    assert mutation.name == "my-bot"

    resp = await client.get("/api/v1/bots/my-bot")
    assert resp.status == 404


async def test_create_slugifies_and_returns_final_name(aiohttp_client, app_with_bots):
    """The response `name` is the slug the UI must navigate to
    (`/admin/agents/<response.name>`), not the raw typed name."""
    client = await aiohttp_client(app_with_bots)

    resp = await client.put(
        "/api/v1/bots", json={**CREATE_PAYLOAD, "name": "  Weird!!  Name  "}
    )
    assert resp.status == 201
    body = await resp.json()
    assert body["name"] == "weird-name"
    assert body["name"] != "  Weird!!  Name  "


async def test_create_deduplicates_a_colliding_slug(aiohttp_client, app_with_bots, db_store):
    """A second agent whose name slugifies to an existing one gets a
    numeric suffix (deduplicate_name), never silently overwrites."""
    client = await aiohttp_client(app_with_bots)

    resp = await client.put("/api/v1/bots", json=CREATE_PAYLOAD)
    assert resp.status == 201
    assert (await resp.json())["name"] == "my-bot"

    resp = await client.put("/api/v1/bots", json=CREATE_PAYLOAD)
    assert resp.status == 201
    body = await resp.json()
    assert body["name"] == "my-bot-2"
    assert set(db_store.keys()) == {"my-bot", "my-bot-2"}
