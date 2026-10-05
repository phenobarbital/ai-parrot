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
    assert {ENABLED, DISABLED} <= other  # a tenant whose callback returns None is unrestricted


async def _async_callback(tenant):
    return {ENABLED}


async def test_failing_callback_logged_once_per_catalogue_build(aiohttp_client, pool, host_plugins, caplog):  # noqa: F811
    calls = []

    def boom(tenant):
        calls.append(tenant)
        raise RuntimeError("projection unavailable")

    client = await aiohttp_client(_app(pool, TenantToolingPolicy(tenant_toolkits=boom)))
    with caplog.at_level("ERROR"):
        resp = await client.get(f"{BASE}/catalog/tools", headers=who("u1", "acme"))
    assert resp.status == 200
    assert calls == ["acme"] and caplog.text.count("fail closed") == 1      # not once per catalogue entry


@pytest.mark.parametrize("callback", [_async_callback, lambda t: 5, lambda t: True], ids=["async", "int", "bool"])
async def test_malformed_callback_fails_closed_never_500(aiohttp_client, pool, host_plugins, callback):  # noqa: F811
    """A callback result that is not a collection refuses (422 / filtered catalogue) instead of a 500."""
    client = await aiohttp_client(_app(pool, TenantToolingPolicy(tenant_toolkits=callback)))
    assert (await create(client, "mine", who("u1")))[0].status == 201
    resp = await client.put(f"{BASE}/agents/mine/toolkits/{ENABLED}", json={"params": {}}, headers=who("u1"))
    body = await resp.json()
    assert resp.status == 422 and body["details"] == {"reason": "toolkit_unavailable", "item": ENABLED}, body
    resp = await client.get(f"{BASE}/catalog/tools", headers=who("u1", "acme"))
    assert resp.status == 200                                   # the catalogue filters the host toolkits out
    assert not {row["slug"] for row in await resp.json()} & {ENABLED, DISABLED}


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


async def test_create_with_disabled_tool_422(aiohttp_client, pool, host_plugins):  # noqa: F811
    """``POST /agents`` with ``config.tools`` naming a disabled host toolkit is refused; the enabled one is not."""
    client = await aiohttp_client(_app(pool))
    resp, body = await create(client, "bad", who("u1"), config={"tools": [DISABLED]})
    assert resp.status == 422 and body["code"] == "tooling_not_permitted", body
    assert body["details"] == EXPECTED
    assert (await create(client, "good", who("u1"), config={"tools": [ENABLED]}))[0].status == 201


async def test_unrelated_edits_not_blocked_by_held_disabled_toolkit(aiohttp_client, pool, host_plugins):  # noqa: F811
    """Delta check (Resolved 2026-10-05): an agent already holding a now-disabled toolkit stays editable.

    PATCH of metadata, asset PUT/DELETE and adding ANOTHER enabled toolkit pass; re-configuring or adding the
    disabled toolkit is refused; removing it is always allowed.
    """
    app = _app(pool, _policy({ENABLED, DISABLED}))
    client = await aiohttp_client(app)
    owner = who("u1")
    assert (await create(client, "mine", owner))[0].status == 201
    url = f"{BASE}/agents/mine/toolkits"
    assert (await client.put(f"{url}/{DISABLED}", json={"params": {}}, headers=owner)).status == 200
    app[tooling_policy._POLICY_KEY] = _policy()          # the programme disabled it since
    resp = await client.patch(f"{BASE}/agents/mine", json={"description": "still editable"}, headers=owner)
    assert resp.status == 200, await resp.text()
    resp = await client.put(f"{BASE}/agents/mine/files/kb/n.md", json={"content": "x"}, headers=owner)
    assert resp.status == 200, await resp.text()
    resp = await client.delete(f"{BASE}/agents/mine/files/kb/n.md", headers=owner)
    assert resp.status == 200, await resp.text()
    resp = await client.put(f"{url}/{ENABLED}", json={"params": {}}, headers=owner)
    assert resp.status == 200, await resp.text()          # adding another toolkit does not re-validate the held one
    resp = await client.put(f"{url}/{DISABLED}", json={"params": {}}, headers=owner)
    body = await resp.json()
    assert resp.status == 422 and body["details"] == EXPECTED, body       # re-configured -> checked
    assert (await client.delete(f"{url}/{DISABLED}", headers=owner)).status == 200


async def test_draft_save_and_activation_422_with_details(aiohttp_client, pool, host_plugins):  # noqa: F811
    app = _app(pool, _policy({ENABLED, DISABLED}))
    client = await aiohttp_client(app)
    extra = {"toolkits": [{"slug": DISABLED}]}
    assert (await save(client, "ok", who("u1"), bundle_extra=extra))[0].status == 201  # enabled at save time
    app[tooling_policy._POLICY_KEY] = _policy()  # the programme disabled it since the save (re-register)
    resp, body = await activate(client, "ok", who("u1"))
    assert resp.status == 422 and body["code"] == "tooling_not_permitted", body
    assert body["details"] == EXPECTED
    resp, body = await save(client, "bad", who("u1"), bundle_extra=extra)
    assert resp.status == 422 and body["code"] == "tooling_not_permitted"
    assert body["details"] == EXPECTED
    assert await client.app["studio_storage"].services.agents.get(StudioPartition("acme"), "ok") is None


async def test_execute_disabled_toolkit_is_403_same_shape(aiohttp_client, pool, host_plugins):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    resp = await client.post(f"{BASE}/tools/tp_tenant_tool/execute", json={"args": {"value": "x"}}, headers=who("u1"))
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
