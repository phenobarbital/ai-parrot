"""PA-5: a per-tenant allow-list narrows the BUILT-IN tools a tenant may use (``tenant_builtin_tools``).

Real app, real Studio routes and real ``TenantToolingPolicy``; ``calculator`` and ``arxiv`` are real built-in
(``parrot_tools``) slugs. Postgres via ``TEST_STUDIO_PG_DSN``.
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

from .test_agents_db_mode import BASE, _offline, pool  # noqa: F401  (fixtures)
from .test_agents_visibility import create, tenant_app, who

ALLOWED, WITHHELD = "calculator", "arxiv"
GLOBAL_SET = frozenset({ALLOWED, WITHHELD})
EXPECTED = {"reason": "toolkit_unavailable", "item": WITHHELD}


def _policy(enabled=frozenset({ALLOWED}), **extra) -> TenantToolingPolicy:
    """``acme`` gets exactly ``enabled`` of the global built-ins; every other tenant is unrestricted."""
    return TenantToolingPolicy(
        builtin_tools=GLOBAL_SET,
        tenant_builtin_tools=lambda tenant: set(enabled) if tenant == "acme" else None,
        **extra,
    )


def _app(pool, policy=None):  # noqa: F811
    app = tenant_app(pool)
    set_tenant_tooling_policy(app, policy or _policy())
    return app


@pytest.fixture(autouse=True)
def _fresh_catalogues(monkeypatch):
    monkeypatch.setattr(catalog_module, "_BASE_CLASSES_CACHE", None)
    monkeypatch.setattr(tools_catalog_module, "_CATALOG_CACHE", None)


def test_the_policy_exposes_a_feature_probe():
    assert "tenant_builtin_tools" in TenantToolingPolicy.model_fields


async def test_attach_and_write_refuse_a_builtin_the_tenant_does_not_have(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    resp, body = await create(client, "bad", who("u1"), config={"tools": [WITHHELD]})
    assert resp.status == 422 and body["code"] == "tooling_not_permitted", body
    assert body["details"] == EXPECTED
    assert (await create(client, "good", who("u1"), config={"tools": [ALLOWED]}))[0].status == 201
    # another tenant's callback answers None: unrestricted inside the global set
    assert (await create(client, "other", who("u9", "globex"), config={"tools": [WITHHELD]}))[0].status == 201
    # outside the GLOBAL set the old refusal stands, whatever the tenant allow-list says
    resp, body = await create(client, "nope", who("u9", "globex"), config={"tools": ["excel"]})
    assert resp.status == 422 and body["details"] == {"reason": "builtin_not_permitted", "item": "excel"}


async def test_catalog_differs_between_tenants_only_by_the_allow_list(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    slugs = lambda body: {row["slug"] for row in body}  # noqa: E731
    acme = slugs(await (await client.get(f"{BASE}/catalog/tools", headers=who("u1", "acme"))).json())
    globex = slugs(await (await client.get(f"{BASE}/catalog/tools", headers=who("u9", "globex"))).json())
    assert acme == {ALLOWED} and globex == GLOBAL_SET


async def test_failing_callback_refuses_and_logs_once_per_catalogue_build(aiohttp_client, pool, caplog):  # noqa: F811
    calls = []

    def boom(tenant):
        calls.append(tenant)
        raise RuntimeError("projection unavailable")

    client = await aiohttp_client(_app(pool, TenantToolingPolicy(builtin_tools=GLOBAL_SET, tenant_builtin_tools=boom)))
    with caplog.at_level("ERROR"):
        resp = await client.get(f"{BASE}/catalog/tools", headers=who("u1", "acme"))
    assert resp.status == 200 and await resp.json() == []        # fail closed: nothing is offered
    assert calls == ["acme"] and caplog.text.count("fail closed") == 1
    resp, body = await create(client, "mine", who("u1"), config={"tools": [ALLOWED]})
    assert resp.status == 422 and body["details"]["reason"] == "toolkit_unavailable"


async def test_held_builtin_still_builds_is_editable_and_refused_at_call_time(aiohttp_client, pool):  # noqa: F811
    app = _app(pool, _policy({ALLOWED, WITHHELD}))
    client = await aiohttp_client(app)
    owner = who("u1")
    assert (await create(client, "mine", owner, config={"tools": [WITHHELD]}))[0].status == 201
    app[tooling_policy._POLICY_KEY] = _policy()                    # the programme withdrew it since
    resp = await client.patch(f"{BASE}/agents/mine", json={"description": "still editable"}, headers=owner)
    assert resp.status == 200, await resp.text()                   # unchanged held tooling is not re-validated
    gate = StudioToolingGate(app)
    tooling, part = NormalizedTooling(tools=[WITHHELD]), StudioPartition("acme")
    gate.enforce(part, tooling, agent_id=None, actor=None, phase="build")        # a stored agent must still build
    with pytest.raises(StudioToolingRefused) as err:
        gate.enforce(part, tooling, agent_id=None, actor=None, phase="write")
    assert err.value.reason == "toolkit_unavailable" and err.value.item == WITHHELD
    resp = await client.post(f"{BASE}/tools/{WITHHELD}/execute", json={"args": {}}, headers=owner)
    body = await resp.json()
    assert resp.status == 403 and body["code"] == "tooling_not_permitted" and body["details"] == EXPECTED, body


async def test_global_partition_is_unrestricted(aiohttp_client, pool):  # noqa: F811
    app = tenant_app(pool, resolver=False)         # a plain host: no tenant, the global partition
    set_tenant_tooling_policy(app, _policy(apply_to_global=True))
    client = await aiohttp_client(app)
    assert (await create(client, "g", who("u1", None), config={"tools": [WITHHELD]}))[0].status == 201
