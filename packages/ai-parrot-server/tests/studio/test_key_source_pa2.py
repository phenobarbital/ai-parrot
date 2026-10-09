"""PA-2: per-request llm-clients ``credentials``, ``key_source`` on test/ask and the assistant.

Real aiohttp app, real Studio routes, real Postgres BYOK store and vault keyring; the only test-owned part is the
LLM client (it echoes which key it was built with).
"""
from __future__ import annotations

import pytest
from navigator_session.vault import KeyRing

import parrot.security.vault_utils as vault_utils
from parrot.bots.studio import AgentStudioAgent
from parrot.clients.factory import SUPPORTED_CLIENTS
from parrot.handlers.studio import agents as agents_module
from parrot.handlers.studio import byok as byok_module
from parrot.handlers.studio import catalog as catalog_module
from parrot.handlers.studio import meta_agent
from parrot.handlers.studio.storage import byok_store as store_module
from parrot.registry import registry as registry_module
from parrot.handlers.studio.storage.byok_store import register_byok_store

from ._scripted_llm import KEYED_PROVIDER, SERVER_KEY_ENV, KeyEchoClient
from .test_testing_db_mode import BASE, _app, pool  # noqa: F401  (pool is a fixture)
from .test_assistant_partition import partition_app

KEYRING = KeyRing({1: b"1" * 32}, 1)
SERVER_ANTHROPIC = "sk-ant-SERVER-SECRET-0001"
USER_GOOGLE = "g-user-secret-7777"
LLM_ENV = ("ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", SERVER_KEY_ENV)


@pytest.fixture(autouse=True)
def _env(monkeypatch, pool, tmp_path):  # noqa: F811
    monkeypatch.setenv("STUDIO_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.setenv("STUDIO_SWEEP_INTERVAL_SECONDS", "3600")
    monkeypatch.setattr(agents_module, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(registry_module, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(store_module, "get_vault_keyring", lambda: KEYRING)
    monkeypatch.setattr(byok_module, "get_vault_keyring", lambda: KEYRING)
    monkeypatch.setattr(vault_utils, "get_vault_keyring", lambda: KEYRING)
    monkeypatch.setenv("BYOK_STORE", "postgres")
    monkeypatch.setattr(catalog_module, "_LLM_CLIENTS_CACHE", None)
    for name in LLM_ENV:
        monkeypatch.delenv(name, raising=False)
    yield
    register_byok_store(None)


@pytest.fixture
async def clean_keys(pool):  # noqa: F811
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE navigator.ai_user_llm_keys")
    yield
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE navigator.ai_user_llm_keys")


async def _providers(client, user="u1", query=""):
    resp = await client.get(f"{BASE}/catalog/llm-clients{query}", headers={"X-User": user})
    assert resp.status == 200
    text = await resp.text()
    return {r["provider"]: r["credentials"] for r in await _json(resp, text)}, text


async def _json(resp, text):
    import json

    return json.loads(text)


async def _store_key(client, provider, key, user="u1"):
    resp = await client.post(f"{BASE}/keys", json={"provider": provider, "api_key": key}, headers={"X-User": user})
    assert resp.status == 201, await resp.text()


async def test_server_key_only_lists_that_provider(aiohttp_client, pool, clean_keys, monkeypatch):  # noqa: F811
    monkeypatch.setenv("ANTHROPIC_API_KEY", SERVER_ANTHROPIC)
    client = await aiohttp_client(_app(pool))
    creds, text = await _providers(client)
    assert creds["anthropic"] == ["server"] and creds["claude"] == ["server"]
    assert "google" not in creds and "openai" not in creds
    assert SERVER_ANTHROPIC not in text and "ANTHROPIC_API_KEY" not in text  # no key material, no env names
    assert all(c for c in creds.values())  # rows with no credentials are omitted


async def test_byok_is_per_user_and_never_cached(aiohttp_client, pool, clean_keys):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    assert "google" not in (await _providers(client, "u1"))[0]
    await _store_key(client, "google", USER_GOOGLE, user="u1")
    creds_u1, text = await _providers(client, "u1")
    assert creds_u1["google"] == ["byok"]
    assert USER_GOOGLE not in text
    assert "google" not in (await _providers(client, "u2"))[0]  # another user, same process: not leaked via the cache
    assert (await _providers(client, "u1"))[0]["google"] == ["byok"]


async def test_both_sources_and_flip_without_restart(aiohttp_client, pool, clean_keys, monkeypatch):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    await _store_key(client, "anthropic", "sk-ant-user-own-1234")
    monkeypatch.setenv("ANTHROPIC_API_KEY", SERVER_ANTHROPIC)
    assert (await _providers(client))[0]["anthropic"] == ["byok", "server"]
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert (await _providers(client))[0]["anthropic"] == ["byok"]  # the server key is gone: the row flips live
    assert (await _providers(client, "u2"))[0].get("anthropic") is None


async def test_usable_zero_keeps_every_row(aiohttp_client, pool, clean_keys):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    assert (await _providers(client))[0] == {}
    all_rows, _ = await _providers(client, query="?usable=0")
    assert "anthropic" in all_rows and all(v == [] for v in all_rows.values())


# -- key_source on test/ask --------------------------------------------------------------------------------------


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setitem(SUPPORTED_CLIENTS, KEYED_PROVIDER, KeyEchoClient)


async def _keyed_client(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    resp = await client.post(
        f"{BASE}/agents", json={"name": "alpha", "bot_class": "BasicBot", "llm": f"{KEYED_PROVIDER}:m"}
    )
    assert resp.status == 201, await resp.text()
    return client


async def _ask(client, **body):
    resp = await client.post(f"{BASE}/agents/alpha/test/ask", json={"query": "hi", **body})
    return resp.status, await resp.json()


async def test_ask_both_keys_requires_a_choice(aiohttp_client, pool, clean_keys, keyed, monkeypatch):  # noqa: F811
    client = await _keyed_client(aiohttp_client, pool)
    await _store_key(client, KEYED_PROVIDER, "user-key-AAAA")
    monkeypatch.setenv(SERVER_KEY_ENV, "server-key-BBBB")
    status, body = await _ask(client)
    assert status == 409 and body["code"] == "key_source_required"
    assert body["details"] == {"provider": KEYED_PROVIDER, "options": ["server", "byok"]}
    assert "user-key-AAAA" not in str(body) and "server-key-BBBB" not in str(body)
    status, body = await _ask(client, key_source="byok")
    assert status == 200 and body["response"] == "key:user-key-AAAA" and body["key_source"] == "byok"
    status, body = await _ask(client, key_source="server")
    assert status == 200 and body["response"] == "key:None" and body["key_source"] == "server"
    status, body = await _ask(client, use_byok=False)  # the legacy opt-out never asks and never spends the key
    assert status == 200 and body["response"] == "key:None"


async def test_ask_single_source_is_used(aiohttp_client, pool, clean_keys, keyed, monkeypatch):  # noqa: F811
    client = await _keyed_client(aiohttp_client, pool)
    assert (await _ask(client))[1]["response"] == "key:None"  # neither stored nor in env: the bot's own client
    monkeypatch.setenv(SERVER_KEY_ENV, "server-key-BBBB")
    assert (await _ask(client))[1]["response"] == "key:None"  # server only
    monkeypatch.delenv(SERVER_KEY_ENV)
    await _store_key(client, KEYED_PROVIDER, "user-key-AAAA")
    status, body = await _ask(client)  # BYOK only
    assert status == 200 and body["response"] == "key:user-key-AAAA"


async def test_ask_explicit_source_that_does_not_exist(aiohttp_client, pool, clean_keys, keyed, monkeypatch):  # noqa: F811
    client = await _keyed_client(aiohttp_client, pool)
    status, body = await _ask(client, key_source="byok")
    assert status == 422 and body["code"] == "key_source_unavailable"
    assert body["details"] == {"provider": KEYED_PROVIDER, "requested": "byok"}
    status, body = await _ask(client, key_source="server")  # the client declares its env var and none is set
    assert status == 422 and body["code"] == "key_source_unavailable"
    assert (await _ask(client, key_source="nope"))[0] == 400


# -- the assistant -----------------------------------------------------------------------------------------------


@pytest.fixture
def assistant(monkeypatch):
    """The assistant on the key-echoing LLM (configure, tools, memory and the handler stay real)."""
    monkeypatch.setitem(SUPPORTED_CLIENTS, KEYED_PROVIDER, KeyEchoClient)
    monkeypatch.setattr(
        meta_agent, "AgentStudioAgent", lambda **kw: AgentStudioAgent(llm=f"{KEYED_PROVIDER}:m", **kw)
    )


async def _say(client, **body):
    resp = await client.post(f"{BASE}/assistant", json={"query": "hi", **body})
    return resp.status, await resp.json()


async def test_assistant_honours_key_source(aiohttp_client, pool, clean_keys, assistant, monkeypatch):  # noqa: F811
    client = await aiohttp_client(partition_app(pool, resolver=False))
    await _store_key(client, "anthropic", "sk-ant-user-own-1234")
    monkeypatch.setenv("ANTHROPIC_API_KEY", SERVER_ANTHROPIC)
    status, body = await _say(client)
    assert status == 409 and body["code"] == "key_source_required"
    assert body["details"] == {"provider": "anthropic", "options": ["server", "byok"]}
    status, body = await _say(client, key_source="byok")
    assert status == 200 and body["response"] == "key:sk-ant-user-own-1234"
    status, body = await _say(client, key_source="server")
    assert status == 200 and body["response"] == "key:None"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    status, body = await _say(client)  # only the personal key is left: used without asking
    assert status == 200 and body["response"] == "key:sk-ant-user-own-1234"
    status, body = await _say(client, key_source="server")
    assert status == 422 and body["code"] == "key_source_unavailable"
