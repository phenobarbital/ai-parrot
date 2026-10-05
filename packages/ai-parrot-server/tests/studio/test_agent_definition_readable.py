"""B1 — readable Studio agent definition (FEAT-634 AC1-AC4). Real aiohttp app, real Postgres, no mocks."""
from __future__ import annotations

from .test_agents_db_mode import BASE, _offline, pool  # noqa: F401  (fixtures)
from .test_agents_visibility import create, tenant_app, who

DEFINITION_KEYS = {"bot_class", "llm", "description", "category", "model_params", "system_prompt", "tools"}


async def _seed(client, visibility: str = "tenant"):
    owner = who("u1")
    resp, body = await create(
        client, "alpha", owner, llm="openai:gpt-4o", description="the desc", category="ops", visibility=visibility,
        config={"system_prompt": "be brief", "temperature": 0.3},
    )
    assert resp.status == 201, body
    return owner


async def test_owner_gets_definition(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    owner = await _seed(client)
    resp = await client.get(f"{BASE}/agents/alpha", headers=owner)
    item = await resp.json()
    assert resp.status == 200
    assert set(item["definition"]) == DEFINITION_KEYS
    assert item["definition"]["bot_class"] == "BasicBot"
    assert item["definition"]["llm"] == "openai:gpt-4o"
    assert item["definition"]["description"] == "the desc"
    assert item["definition"]["category"] == "ops"
    assert item["definition"]["system_prompt"] == "be brief"
    assert item["definition"]["model_params"]["temperature"] == 0.3
    assert item["definition"]["tools"] == []
    assert (item["llm"], item["description"], item["category"]) == ("openai:gpt-4o", "the desc", "ops")


async def test_viewer_gets_flat_keys_without_definition(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    await _seed(client)
    resp = await client.get(f"{BASE}/agents/alpha", headers=who("u2"))
    item = await resp.json()
    assert resp.status == 200 and item["can_manage"] is False
    assert "definition" not in item
    assert (item["llm"], item["description"], item["category"]) == ("openai:gpt-4o", "the desc", "ops")
    assert "be brief" not in str(item)


async def test_list_has_flat_keys_never_definition(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    owner = await _seed(client)
    for caller in (owner, who("u2")):
        items = (await (await client.get(f"{BASE}/agents", headers=caller)).json())["agents"]
        assert len(items) == 1
        assert "definition" not in items[0]
        assert items[0]["llm"] == "openai:gpt-4o" and items[0]["category"] == "ops"


async def test_patch_and_visibility_return_definition_and_version(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    owner = await _seed(client)
    resp = await client.patch(f"{BASE}/agents/alpha", json={"description": "new", "system_prompt": "p2"},
                              headers=owner)
    body = await resp.json()
    assert resp.status == 200 and body["version"] == 2
    assert body["definition"]["description"] == "new" and body["definition"]["system_prompt"] == "p2"
    assert body["description"] == "new"
    resp = await client.patch(f"{BASE}/agents/alpha/visibility", json={"visibility": "private"}, headers=owner)
    body = await resp.json()
    assert resp.status == 200 and "definition" in body and body["definition"]["system_prompt"] == "p2"
    assert body["visibility"] == "private"


async def test_no_config_or_schema_version_and_no_key_lost(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    owner = await _seed(client)
    item = await (await client.get(f"{BASE}/agents/alpha", headers=owner)).json()
    for forbidden in ("config", "schema_version"):
        assert forbidden not in item and forbidden not in item["definition"]
    for key in ("name", "source", "origin", "owner", "enabled", "agent_id", "tenant", "version", "updated_at",
                "visibility", "allowed_groups", "class_name", "module", "file_path", "tags", "priority",
                "at_startup", "can_manage"):
        assert key in item, key
