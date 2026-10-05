"""B1 — readable Studio agent definition (FEAT-634 AC1-AC4). Real aiohttp app, no mocks."""

from __future__ import annotations

from .test_agents_db_mode import BASE, _offline, pool  # noqa: F401
from .test_agents_visibility import create, tenant_app, who


class TestDefinitionReadable:
    """Readability rules for Studio agent definitions."""

    async def test_owner_gets_definition(self, aiohttp_client, pool):
        """A manager receives the full allowed definition on GET detail."""
        client = await aiohttp_client(tenant_app(pool))
        owner = who("owner")
        resp, created = await create(
            client,
            "readable",
            owner,
            llm="openai:gpt-4o",
            description="Readable agent",
            category="support",
            config={"system_prompt": "Be helpful.", "temperature": 0.4},
        )
        assert resp.status == 201, created

        resp = await client.get(f"{BASE}/agents/readable", headers=owner)
        body = await resp.json()

        assert resp.status == 200, body
        assert body["definition"] == {
            "bot_class": "BasicBot",
            "llm": "openai:gpt-4o",
            "description": "Readable agent",
            "category": "support",
            "model_params": {"temperature": 0.4, "max_tokens": None, "top_k": None, "top_p": None},
            "system_prompt": "Be helpful.",
            "tools": [],
        }

    async def test_viewer_gets_flat_keys_without_definition(self, aiohttp_client, pool):
        """A visible non-manager receives card fields but never sensitive definition data."""
        client = await aiohttp_client(tenant_app(pool))
        owner = who("owner")
        resp, created = await create(
            client,
            "shared",
            owner,
            llm="anthropic:claude",
            description="Shared agent",
            category="operations",
            visibility="tenant",
            config={"system_prompt": "Owner-only prompt."},
        )
        assert resp.status == 201, created

        resp = await client.get(f"{BASE}/agents/shared", headers=who("viewer"))
        body = await resp.json()

        assert resp.status == 200, body
        assert {key: body[key] for key in ("llm", "description", "category")} == {
            "llm": "anthropic:claude",
            "description": "Shared agent",
            "category": "operations",
        }
        assert body["can_manage"] is False
        assert "definition" not in body

    async def test_list_has_flat_keys_never_definition(self, aiohttp_client, pool):
        """List cards expose only non-sensitive readable fields for every viewer."""
        client = await aiohttp_client(tenant_app(pool))
        owner = who("owner")
        resp, created = await create(
            client,
            "listed",
            owner,
            llm="google:gemini",
            description="Listable agent",
            category="analysis",
            visibility="tenant",
            config={"system_prompt": "Never list this."},
        )
        assert resp.status == 201, created

        resp = await client.get(f"{BASE}/agents", headers=who("viewer"))
        body = await resp.json()
        item = next(agent for agent in body["agents"] if agent["name"] == "listed")

        assert resp.status == 200, body
        assert {key: item[key] for key in ("llm", "description", "category")} == {
            "llm": "google:gemini",
            "description": "Listable agent",
            "category": "analysis",
        }
        assert "definition" not in item

    async def test_patch_and_visibility_return_definition_and_version(self, aiohttp_client, pool):
        """Manager PATCH responses return updated definitions and their bumped versions."""
        client = await aiohttp_client(tenant_app(pool))
        owner = who("owner", groups="editors")
        resp, created = await create(
            client,
            "updated",
            owner,
            llm="openai:gpt-4o-mini",
            description="Before patch",
            category="general",
        )
        assert resp.status == 201, created

        resp = await client.patch(
            f"{BASE}/agents/updated",
            headers=owner,
            json={"description": "After patch", "system_prompt": "Updated prompt.", "model_params": {"top_k": 7}},
        )
        patched = await resp.json()

        assert resp.status == 200, patched
        assert patched["version"] == created["version"] + 1
        assert patched["definition"]["description"] == "After patch"
        assert patched["definition"]["system_prompt"] == "Updated prompt."
        assert patched["definition"]["model_params"]["top_k"] == 7

        resp = await client.patch(
            f"{BASE}/agents/updated/visibility",
            headers=owner,
            json={"visibility": "groups", "allowed_groups": ["editors"]},
        )
        visible = await resp.json()

        assert resp.status == 200, visible
        assert visible["version"] == patched["version"] + 1
        assert visible["definition"] == patched["definition"]

    async def test_no_config_or_schema_version_and_no_key_lost(self, aiohttp_client, pool):
        """Readable definitions exclude internal fields while retaining every legacy item key."""
        client = await aiohttp_client(tenant_app(pool))
        owner = who("owner")
        resp, created = await create(
            client,
            "additive",
            owner,
            llm="openai:gpt-4o",
            description="Additive response",
            category="support",
            config={"system_prompt": "Private prompt.", "custom_setting": "retained internally"},
        )
        assert resp.status == 201, created

        body = await (await client.get(f"{BASE}/agents/additive", headers=owner)).json()

        assert {"config", "schema_version"}.isdisjoint(body)
        assert {"config", "schema_version"}.isdisjoint(body["definition"])
        assert {
            "name",
            "source",
            "origin",
            "owner",
            "enabled",
            "agent_id",
            "tenant",
            "version",
            "updated_at",
            "visibility",
            "allowed_groups",
            "class_name",
            "module",
            "file_path",
            "tags",
            "priority",
            "at_startup",
        } <= body.keys()
