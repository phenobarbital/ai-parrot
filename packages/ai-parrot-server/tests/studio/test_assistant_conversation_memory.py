"""The Studio assistant keeps its conversation when a turn lands on a worker without its instance.

Real app, real assistant handler, session and Redis conversation backend; only the LLM client is test-owned.
"""

from __future__ import annotations

import os

import pytest
from parrot.bots.studio import AgentStudioAgent
from parrot.clients.factory import SUPPORTED_CLIENTS
from parrot.handlers.studio import meta_agent
from parrot.handlers.studio.conversation import KEY_PREFIX
from redis.asyncio import Redis

from ._scripted_llm import PROVIDER, ScriptedClient, history_seen
from .test_agents_db_mode import BASE, pool  # noqa: F401  (pool is a fixture)
from .test_assistant_partition import partition_app

REDIS_URL = os.environ.get("TEST_STUDIO_REDIS_URL", "")  # a DEDICATED db: the fixture deletes only its own prefix


@pytest.fixture
async def shared_redis(monkeypatch):
    if not REDIS_URL:
        pytest.skip("TEST_STUDIO_REDIS_URL not set; the redis conversation backend needs a Redis")
    monkeypatch.setenv("STUDIO_CONVERSATION_BACKEND", "redis")
    monkeypatch.setenv("STUDIO_CONVERSATION_REDIS_URL", REDIS_URL)
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    yield client
    keys = [k async for k in client.scan_iter(match=f"{KEY_PREFIX}*")]
    if keys:
        await client.delete(*keys)
    await client.aclose()


@pytest.fixture
def assistant(monkeypatch):
    """The assistant built on the scripted LLM (everything else — configure, tools, memory — is real)."""
    monkeypatch.setitem(SUPPORTED_CLIENTS, PROVIDER, ScriptedClient)
    monkeypatch.setattr(
        meta_agent, "AgentStudioAgent", lambda **kw: AgentStudioAgent(llm=f"{PROVIDER}:m", **kw)
    )


async def _say(client, text):
    resp = await client.post(f"{BASE}/assistant", json={"query": text, "use_byok": False})
    body = await resp.json()
    assert resp.status == 200, body
    return history_seen(body["response"])


def _drop_instances(app) -> None:
    """What a turn landing on another worker looks like: this process holds no assistant instance."""
    app[meta_agent._ASSISTANTS_APP_KEY].clear()


async def test_same_worker_second_turn_sees_the_first(aiohttp_client, pool, assistant):  # noqa: F811
    client = await aiohttp_client(partition_app(pool, resolver=False))
    assert await _say(client, "one") == 0
    assert await _say(client, "two") == 2


async def test_another_worker_keeps_the_conversation(aiohttp_client, pool, assistant, shared_redis):  # noqa: F811
    app = partition_app(pool, resolver=False)
    client = await aiohttp_client(app)
    assert await _say(client, "one") == 0
    session = app["_sessions"]["u1"][meta_agent.SESSION_KEY]
    (entry,) = session.values()
    _drop_instances(app)
    assert await _say(client, "two") == 2  # the rebuilt instance continues the same conversation
    (entry_after,) = app["_sessions"]["u1"][meta_agent.SESSION_KEY].values()
    assert entry_after["session_id"] == entry["session_id"]  # not re-minted
    assert entry_after["instance"] != entry["instance"]  # a new instance did serve it
    assert await _say(client, "three") == 4
