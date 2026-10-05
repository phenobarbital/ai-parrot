"""B4/B5 host-toolkit allow-list coverage through real Studio routes."""

from __future__ import annotations

import sys
import textwrap

import pytest
from parrot.handlers import tools_catalog
from parrot.handlers.studio.agents import StudioAgentReloadHandler, StudioAgentsHandler
from parrot.handlers.studio.catalog import StudioCatalogHandler
from parrot.handlers.studio.drafts import StudioDraftActivateHandler, StudioDraftsHandler
from parrot.handlers.studio.storage.models import StudioPartition
from parrot.handlers.studio.testing import StudioToolExecuteHandler
from parrot.handlers.studio.toolkit_config import StudioAgentToolkitsHandler
from parrot.handlers.scope import RequestScope
from parrot.tools.tooling_policy import TenantToolingPolicy, set_tenant_tooling_policy

from .test_agents_db_mode import _app, _offline, pool  # noqa: F401

BASE = "/tenant"
_DETAILS = {"reason": "toolkit_unavailable", "item": "fs_stores"}


class _T1View:
    """Route view mixin that models a host request scoped to tenant ``t1``."""

    async def _studio_partition(self) -> StudioPartition:
        return StudioPartition("t1")

    async def _scope(self) -> RequestScope:
        user = await self._get_user()
        return RequestScope(user_id=user.user_id, tenant="t1", groups=frozenset(user.groups))


class _T2Catalog(_T1View, StudioCatalogHandler):
    """A caller whose host allow-list callback deliberately returns ``None``."""

    async def _studio_partition(self) -> StudioPartition:
        return StudioPartition("t2")

    async def _scope(self) -> RequestScope:
        user = await self._get_user()
        return RequestScope(user_id=user.user_id, tenant="t2", groups=frozenset(user.groups))


class _T1Agents(_T1View, StudioAgentsHandler):
    """Tenant ``t1`` agent routes."""


class _T1Reload(_T1View, StudioAgentReloadHandler):
    """Tenant ``t1`` reload route."""


class _T1Toolkits(_T1View, StudioAgentToolkitsHandler):
    """Tenant ``t1`` toolkit route."""


class _T1Catalog(_T1View, StudioCatalogHandler):
    """Tenant ``t1`` catalog route."""


class _T1Execute(_T1View, StudioToolExecuteHandler):
    """Tenant ``t1`` execution route."""


class _T1Drafts(_T1View, StudioDraftsHandler):
    """Tenant ``t1`` draft route."""


class _T1Activate(_T1View, StudioDraftActivateHandler):
    """Tenant ``t1`` draft activation route."""


@pytest.fixture
def fs_plugins(tmp_path, monkeypatch):
    """Register the two host toolkit slugs used by the FieldSync route contract."""
    from parrot.tools.resolver import get_toolkit_resolver

    package = tmp_path / "plugins" / "tools"
    package.mkdir(parents=True)
    (tmp_path / "plugins" / "__init__.py").write_text("")
    (package / "__init__.py").write_text(
        'HOST_TOOL_PREFIX = "fs_"\n'
        'TOOL_REGISTRY = {"fs_events": "plugins.tools.probe.EventsToolkit", '
        '"fs_stores": "plugins.tools.probe.StoresToolkit"}\n'
    )
    (package / "probe.py").write_text(
        textwrap.dedent(
            '''
            from parrot.tools.toolkit import AbstractToolkit


            class EventsToolkit(AbstractToolkit):
                """Allowed host toolkit."""

                tool_prefix = "fs"

                async def events(self) -> str:
                    """Return a deterministic event marker."""
                    return "events"


            class StoresToolkit(AbstractToolkit):
                """Host toolkit disabled for tenant ``t1`` in these tests."""

                tool_prefix = "fs"

                async def stores(self) -> str:
                    """Return a deterministic store marker."""
                    return "stores"
            '''
        )
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in [module for module in sys.modules if module == "plugins" or module.startswith("plugins.")]:
        monkeypatch.delitem(sys.modules, name)
    get_toolkit_resolver().reload()
    yield
    for name in [module for module in sys.modules if module == "plugins" or module.startswith("plugins.")]:
        sys.modules.pop(name, None)
    get_toolkit_resolver().reload()


@pytest.fixture(autouse=True)
def _reset_catalog(monkeypatch):
    """Avoid reusing a process-wide catalogue built before the host fixture."""
    monkeypatch.setattr(tools_catalog, "_CATALOG_CACHE", None)


async def _client(aiohttp_client, pool, enabled: set[str]):
    """Build a real Studio app with tenant-specific routes and a mutable host projection."""
    app = _app(pool)
    set_tenant_tooling_policy(
        app,
        TenantToolingPolicy(tenant_toolkits=lambda tenant: enabled if tenant == "t1" else None),
    )
    app.router.add_view(f"{BASE}/agents", _T1Agents)
    app.router.add_view(f"{BASE}/agents/{{name}}", _T1Agents)
    app.router.add_view(f"{BASE}/agents/{{name}}/reload", _T1Reload)
    app.router.add_view(f"{BASE}/agents/{{name}}/toolkits/{{slug}}", _T1Toolkits)
    app.router.add_view(f"{BASE}/catalog/{{kind}}", _T1Catalog)
    app.router.add_view("/unrestricted/catalog/{kind}", _T2Catalog)
    app.router.add_view(f"{BASE}/tools/{{slug}}/execute", _T1Execute)
    app.router.add_view(f"{BASE}/drafts", _T1Drafts)
    app.router.add_view(f"{BASE}/drafts/{{name}}", _T1Drafts)
    app.router.add_view(f"{BASE}/drafts/{{name}}/activate", _T1Activate)
    return await aiohttp_client(app)


async def _create(client, name: str, *, tools: list[str] | None = None):
    """Create a tenant Studio agent through its public route."""
    body = {"name": name, "bot_class": "BasicBot"}
    if tools is not None:
        body["config"] = {"tools": tools}
    return await client.post(f"{BASE}/agents", json=body)


def _bundle(name: str) -> dict:
    """Declarative draft payload containing the host toolkit under test."""
    return {
        "name": name,
        "bundle": {
            "name": name,
            "definition": {"bot_class": "BasicBot"},
            "toolkits": [{"slug": "fs_stores", "params": {}}],
        },
    }


class TestToolkitAllowlistRoutes:
    """AC6-AC8 and AC11 through actual aiohttp Studio routes and a real policy."""

    async def test_catalog_tools_filtered_for_t1(self, aiohttp_client, pool, fs_plugins):
        """AC6: only enabled host toolkits appear for a restricted tenant."""
        client = await _client(aiohttp_client, pool, {"fs_events"})
        restricted = {item["slug"] for item in await (await client.get(f"{BASE}/catalog/tools")).json()}
        unrestricted = {
            item["slug"] for item in await (await client.get("/unrestricted/catalog/tools")).json()
        }
        assert "fs_events" in restricted and "fs_stores" not in restricted
        assert {"fs_events", "fs_stores"} <= unrestricted

    async def test_put_toolkit_disabled_is_422_with_details(self, aiohttp_client, pool, fs_plugins):
        """AC7/AC11: persisted toolkit writes expose the policy's reason and item."""
        client = await _client(aiohttp_client, pool, {"fs_events"})
        assert (await _create(client, "put-target")).status == 201
        response = await client.put(f"{BASE}/agents/put-target/toolkits/fs_stores", json={"params": {}})
        assert response.status == 422
        body = await response.json()
        assert body["code"] == "tooling_not_permitted" and body["details"] == _DETAILS

    async def test_create_and_patch_with_disabled_toolkit_422(self, aiohttp_client, pool, fs_plugins):
        """AC7: create and PATCH both recheck the stored/declared final tooling."""
        enabled = {"fs_events", "fs_stores"}
        client = await _client(aiohttp_client, pool, enabled)
        assert (await _create(client, "patch-target", tools=["fs_stores"])).status == 201
        enabled.remove("fs_stores")
        create = await _create(client, "create-target", tools=["fs_stores"])
        patch = await client.patch(f"{BASE}/agents/patch-target", json={"description": "changed"})
        for response in (create, patch):
            body = await response.json()
            assert response.status == 422 and body["code"] == "tooling_not_permitted"
            assert body["details"] == _DETAILS

    async def test_draft_save_and_activation_422_with_details(self, aiohttp_client, pool, fs_plugins):
        """AC7/AC11: save and activation independently report the complete refusal shape."""
        enabled = {"fs_events", "fs_stores"}
        client = await _client(aiohttp_client, pool, enabled)
        saved = await client.post(f"{BASE}/drafts", json=_bundle("before-disable"))
        assert saved.status == 201
        enabled.remove("fs_stores")
        save = await client.post(f"{BASE}/drafts", json=_bundle("disabled-save"))
        activate = await client.post(f"{BASE}/drafts/before-disable/activate", json={})
        for response in (save, activate):
            body = await response.json()
            assert response.status == 422 and body["code"] == "tooling_not_permitted"
            assert body["details"] == _DETAILS

    async def test_execute_disabled_toolkit_is_403_same_shape(self, aiohttp_client, pool, fs_plugins):
        """AC7: execution differs only in status code, not the refusal body."""
        client = await _client(aiohttp_client, pool, {"fs_events"})
        response = await client.post(f"{BASE}/tools/fs_stores/execute", json={"args": {}})
        body = await response.json()
        assert response.status == 403 and body["code"] == "tooling_not_permitted"
        assert body["details"] == _DETAILS

    async def test_existing_agent_with_disabled_toolkit_still_builds(self, aiohttp_client, pool, fs_plugins):
        """AC8: phase ``build`` intentionally ignores the tenant's current toolkit allow-list."""
        enabled = {"fs_events", "fs_stores"}
        client = await _client(aiohttp_client, pool, enabled)
        assert (await _create(client, "build-target", tools=["fs_stores"])).status == 201
        enabled.remove("fs_stores")
        response = await client.post(f"{BASE}/agents/build-target/reload", json={})
        assert response.status == 200, await response.text()
