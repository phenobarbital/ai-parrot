"""Unit tests for ``GET /api/v1/bots?include_disabled`` (FEAT-475, TASK-2583).

Covers the two behaviours the Admin UI agent-management form depends on:

- Default ``GET /api/v1/bots`` continues to hide ``enabled=False`` DB
  agents (regression guard — behaviour must stay byte-identical to
  today).
- ``GET /api/v1/bots?include_disabled=true`` (and the ``1``/``yes``
  spellings) returns every DB agent regardless of ``enabled``.

Follows the same infra-free testing pattern established by
``tests/test_admin_status.py``: ``request["authenticated"]`` short-circuit
middleware plus a monkeypatched data-access method — no live Postgres/Redis
required.  ``ChatbotHandler._get_db_agents``/``_get_db_agent`` are
monkeypatched with in-memory ``BotModel``-shaped stand-ins per the spec's
Test Data / Fixtures section (`sdd/specs/ui-agent-management.spec.md` §4).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from aiohttp import web
from parrot.handlers.bots import ChatbotHandler


def _bot(name: str, *, enabled: bool) -> SimpleNamespace:
    """Minimal BotModel-shaped stand-in for list/dict conversion.

    ``ChatbotHandler._bot_model_to_dict`` calls ``agent.to_dict()`` — the
    stand-in's ``to_dict`` returns the same field dict driving the
    response, so ``name``/``enabled`` survive the round-trip.
    """
    fields = {
        "chatbot_id": "00000000-0000-0000-0000-000000000000",
        "name": name,
        "description": None,
        "avatar": None,
        "enabled": enabled,
        "timezone": "UTC",
        "role": "AI Assistant",
        "goal": "goal",
        "backstory": "backstory",
        "rationale": "rationale",
        "capabilities": None,
        "system_prompt_template": None,
        "human_prompt_template": None,
        "pre_instructions": [],
        "prompt_config": {},
        "llm": "google",
        "model_config": {},
        "tools_enabled": True,
        "auto_tool_detection": True,
        "tool_threshold": 0.7,
        "tools": [],
        "operation_mode": "adaptive",
        "use_kb": False,
        "kb": [],
        "custom_kbs": None,
        "use_vector": False,
        "vector_store_config": {},
        "reranker_config": {},
        "parent_searcher_config": {},
        "context_search_limit": 10,
        "context_score_threshold": 0.7,
        "memory_type": "memory",
        "memory_config": {},
        "max_context_turns": 5,
        "use_conversation_history": True,
        "bot_class": "BasicBot",
        "permissions": {},
        "language": "en",
        "disclaimer": None,
        "created_at": None,
        "created_by": None,
        "updated_at": None,
    }
    stand_in = SimpleNamespace(**fields)
    stand_in.to_dict = lambda: dict(fields)
    return stand_in


@pytest.fixture
def db_agents():
    """In-memory BotModel-shaped stand-ins: one enabled, one disabled."""
    return [
        _bot("helpdesk", enabled=True),
        _bot("archived-bot", enabled=False),
    ]


@pytest.fixture
def app_with_bots(monkeypatch, db_agents):
    """aiohttp app: ChatbotHandler wired with a stubbed DB layer.

    ``_get_db_agents(include_disabled=...)`` is monkeypatched directly so
    the test never touches a real database connection; the real
    ``_get_all``/``get`` code path (query-param parsing, response shape)
    still runs unmodified.
    """

    async def _fake_get_db_agents(self, include_disabled: bool = False):
        if include_disabled:
            return list(db_agents)
        return [a for a in db_agents if a.enabled]

    monkeypatch.setattr(
        ChatbotHandler, "_get_db_agents", _fake_get_db_agents
    )
    # No registry configured -> _get_all's registry merge step is a no-op.
    monkeypatch.setattr(
        ChatbotHandler, "_registry", property(lambda self: None)
    )
    # No app['abac'] -> _get_pbac_evaluator() naturally returns None
    # (fail-open branch is skipped without needing a monkeypatch).

    # `ChatbotHandler.get()` starts with `await self.session()`; on
    # `AbstractModel` (navigator/views/abstract.py) that delegates to
    # `navigator_session.get_session` — which requires a real session-storage
    # backend wired into the app. No test in this suite exercises session
    # contents, so stub it with a truthy stand-in (mirrors the `get_session`
    # monkeypatch pattern in test_admin_status.py, applied at the
    # `navigator.views.abstract` import site `AbstractModel.session()`
    # actually uses).
    async def _fake_get_session(request, *args, **kwargs):
        return {"session": {}}

    monkeypatch.setattr(
        "navigator.views.abstract.get_session", _fake_get_session
    )

    @web.middleware
    async def _mark_authenticated(request: web.Request, handler):
        request["authenticated"] = True
        return await handler(request)

    app = web.Application(middlewares=[_mark_authenticated])
    ChatbotHandler.configure(app, "/api/v1/bots")
    return app


class TestIncludeDisabled:
    async def test_get_all_default_hides_disabled(
        self, aiohttp_client, app_with_bots
    ):
        client = await aiohttp_client(app_with_bots)
        resp = await client.get("/api/v1/bots")
        assert resp.status == 200
        body = await resp.json()
        names = {a["name"] for a in body["agents"]}
        assert names == {"helpdesk"}
        assert body["total"] == 1

    @pytest.mark.parametrize("value", ["true", "1", "yes", "TRUE", "Yes"])
    async def test_get_all_include_disabled(
        self, aiohttp_client, app_with_bots, value
    ):
        client = await aiohttp_client(app_with_bots)
        resp = await client.get(f"/api/v1/bots?include_disabled={value}")
        assert resp.status == 200
        body = await resp.json()
        names = {a["name"] for a in body["agents"]}
        assert names == {"helpdesk", "archived-bot"}
        assert body["total"] == 2
        # `enabled` field must be present so the UI can render the toggle.
        by_name = {a["name"]: a for a in body["agents"]}
        assert by_name["archived-bot"]["enabled"] is False
        assert by_name["helpdesk"]["enabled"] is True

    async def test_get_all_include_disabled_false_values_hide_disabled(
        self, aiohttp_client, app_with_bots
    ):
        client = await aiohttp_client(app_with_bots)
        resp = await client.get("/api/v1/bots?include_disabled=false")
        assert resp.status == 200
        body = await resp.json()
        names = {a["name"] for a in body["agents"]}
        assert names == {"helpdesk"}
