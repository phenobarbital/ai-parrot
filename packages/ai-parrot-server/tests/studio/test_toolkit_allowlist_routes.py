"""B4/B5 — host-toolkit allow-list through the Studio routes (FEAT-634 AC6-AC8, AC11). Real app, real policy.

The host toolkits are the ``tp_*`` probe entries of ``_host_probe`` (``tp_probe`` is enabled for tenant ``acme``,
``tp_tenant`` is not). Postgres via ``TEST_STUDIO_PG_DSN``.
"""
from __future__ import annotations

import pytest

from parrot.handlers import tools_catalog as tools_catalog_module
from parrot.handlers.studio import catalog as catalog_module
from parrot.handlers.studio.storage.models import StudioPartition, StudioToolingRefused
from parrot.handlers.studio.storage.services._common import StudioToolingGate
from parrot.tools import tooling_policy
from parrot.tools.spec import NormalizedTooling
from parrot.tools.tooling_policy import TenantToolingPolicy, set_tenant_tooling_policy

from ._host_probe import host_plugins  # noqa: F401
from .test_agents_db_mode import BASE, _offline, pool  # noqa: F401  (fixtures)
from .test_agents_visibility import create, tenant_app, who
from .test_drafts_tenant import _drafts_dir, activate, save  # noqa: F401  (fixtures)

ENABLED, DISABLED = "tp_probe", "tp_tenant"
EXPECTED = {"reason": "toolkit_unavailable", "item": DISABLED}


def _policy(enabled=frozenset({ENABLED})) -> TenantToolingPolicy:
    """``acme`` gets exactly ``enabled``; every other tenant is unrestricted."""
    return TenantToolingPolicy(tenant_toolkits=lambda tenant: set(enabled) if tenant == "acme" else None)


def _app(pool, policy=None):  # noqa: F811
    app = tenant_app(pool)
    set_tenant_tooling_policy(app, policy or _policy())
    return app


@pytest.fixture(autouse=True)
def _fresh_catalogues(monkeypatch):
    monkeypatch.setattr(catalog_module, "_BASE_CLASSES_CACHE", None)
    monkeypatch.setattr(tools_catalog_module, "_CATALOG_CACHE", None)


async def test_catalog_tools_filtered_for_t1(aiohttp_client, pool, host_plugins):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    slugs = lambda body: {row["slug"] for row in body}  # noqa: E731
    resp = await client.get(f"{BASE}/catalog/tools", headers=who("u1", "acme"))
    assert resp.status == 200
    acme = slugs(await resp.json())
    assert ENABLED in acme and DISABLED not in acme
    assert not any(s.startswith("tp_") and s != ENABLED for s in acme)
    resp = await client.get(f"{BASE}/catalog/tools", headers=who("u9", "globex"))
    other = slugs(await resp.json())
    assert {ENABLED, DISABLED} <= other            # a tenant whose callback returns None is unrestricted


async def test_put_toolkit_disabled_is_422_with_details(aiohttp_client, pool, host_plugins):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    assert (await create(client, "mine", who("u1")))[0].status == 201
    url = f"{BASE}/agents/mine/toolkits"
    resp = await client.put(f"{url}/{DISABLED}", json={"params": {}, "user_overridable": []}, headers=who("u1"))
    body = await resp.json()
    assert resp.status == 422 and body["code"] == "tooling_not_permitted", body
    assert body["details"] == EXPECTED
    resp = await client.put(f"{url}/{ENABLED}", json={"params": {}, "user_overridable": []}, headers=who("u1"))
    assert resp.status == 200, await resp.text()


async def test_create_and_patch_with_disabled_toolkit_422(aiohttp_client, pool, host_plugins):  # noqa: F811
    """Neither ``POST /agents`` nor ``PATCH`` carries tooling; every route that does is refused identically.

    The bundle route (draft save) and the toolkit PUT are the write paths; an agent created plainly stays writable
    for the enabled toolkit and refused for the disabled one, and its PATCH (General fields) is unaffected.
    """
    client = await aiohttp_client(_app(pool))
    assert (await create(client, "mine", who("u1")))[0].status == 201
    resp = await client.patch(f"{BASE}/agents/mine", json={"description": "x"}, headers=who("u1"))
    assert resp.status == 200
    resp = await client.put(f"{BASE}/agents/mine/toolkits/{DISABLED}", json={"params": {}}, headers=who("u1"))
    assert resp.status == 422 and (await resp.json())["details"] == EXPECTED


async def test_draft_save_and_activation_422_with_details(aiohttp_client, pool, host_plugins):  # noqa: F811
    app = _app(pool, _policy({ENABLED, DISABLED}))
    client = await aiohttp_client(app)
    extra = {"toolkits": [{"slug": DISABLED}]}
    assert (await save(client, "ok", who("u1"), bundle_extra=extra))[0].status == 201      # enabled at save time
    app[tooling_policy._POLICY_KEY] = _policy()          # the programme disabled it since the save (re-register)
    resp, body = await activate(client, "ok", who("u1"))
    assert resp.status == 422 and body["code"] == "tooling_not_permitted", body
    assert body["details"] == EXPECTED
    resp, body = await save(client, "bad", who("u1"), bundle_extra=extra)
    assert resp.status == 422 and body["code"] == "tooling_not_permitted"
    assert body["details"] == EXPECTED
    assert await client.app["studio_storage"].services.agents.get(StudioPartition("acme"), "ok") is None


async def test_execute_disabled_toolkit_is_403_same_shape(aiohttp_client, pool, host_plugins):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    resp = await client.post(f"{BASE}/tools/tp_tenant_tool/execute", json={"args": {"value": "x"}},
                             headers=who("u1"))
    body = await resp.json()
    assert resp.status == 403 and body["code"] == "tooling_not_permitted", body
    assert body["details"] == {"reason": "toolkit_unavailable", "item": "tp_tenant_tool"}


async def test_existing_agent_with_disabled_toolkit_still_builds(aiohttp_client, pool, host_plugins):  # noqa: F811
    """Phase ``build`` is never refused by the allow-list; the same tooling is refused on ``write``."""
    client = await aiohttp_client(_app(pool))
    gate = StudioToolingGate(client.app)
    tooling = NormalizedTooling(tools=[DISABLED])
    part = StudioPartition("acme")
    gate.enforce(part, tooling, agent_id=None, actor=None, phase="build")
    with pytest.raises(StudioToolingRefused) as err:
        gate.enforce(part, tooling, agent_id=None, actor=None, phase="write")
    assert err.value.reason == "toolkit_unavailable" and err.value.item == DISABLED
