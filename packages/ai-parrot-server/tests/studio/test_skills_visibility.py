"""FEAT-605 M8 — skills catalogue route matrix (real resolver, real ``SessionData``, real Postgres)."""
from __future__ import annotations

import uuid

import pytest

from parrot.handlers.studio import skills_catalog as sc
from parrot.handlers.studio.skills_catalog import StudioSkillVisibilityHandler

from .test_agents_db_mode import BASE, _offline, pool  # noqa: F401  (fixtures)
from .test_agents_visibility import create, tenant_app, who
from .test_skills_catalog_db_mode import PAYLOAD, _FakeRegistry


@pytest.fixture(autouse=True)
def _registry(monkeypatch):
    fake = _FakeRegistry()
    monkeypatch.setattr(sc, "_get_shared_skill_registry", lambda _app, _org, part=None: fake)
    return fake


def _app(pool):  # noqa: F811
    app = tenant_app(pool)
    app.router.add_view(f"{BASE}/skills/{{id}}/visibility", StudioSkillVisibilityHandler)
    return app


async def publish(client, name, caller, **extra):
    resp = await client.post(f"{BASE}/skills", json={**PAYLOAD, "name": name, **extra}, headers=caller)
    return resp, await resp.json()


async def skill_names(client, caller) -> set[str]:
    resp = await client.get(f"{BASE}/skills", headers=caller)
    assert resp.status == 200, await resp.text()
    return {s["name"] for cat in (await resp.json())["skills"].values() for s in cat}


async def seed(client) -> dict[str, str]:
    owner = who("u1", groups="g1")
    ids = {}
    for name, extra in (("s-private", {}), ("s-tenant", {"visibility": "tenant"}),
                        ("s-groups", {"visibility": "groups", "allowed_groups": ["g1"]})):
        resp, body = await publish(client, name, owner, **extra)
        assert resp.status == 201, body
        ids[name] = body["skill_id"]
    resp, body = await publish(client, "s-other", who("u9", "globex"))
    ids["s-other"] = body["skill_id"]
    return ids


async def test_list_get_filter_and_fields(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    ids = await seed(client)
    assert await skill_names(client, who("u1", groups="g1")) == {"s-private", "s-tenant", "s-groups"}
    assert await skill_names(client, who("u2")) == {"s-tenant"}
    assert await skill_names(client, who("u3", groups="g1")) == {"s-tenant", "s-groups"}
    assert await skill_names(client, who("u4", admin=True)) == {"s-private", "s-tenant", "s-groups"}
    assert await skill_names(client, who("u9", "globex")) == {"s-other"}
    assert await skill_names(client, who("u9", None)) == set()
    hidden = await client.get(f"{BASE}/skills/{ids['s-private']}", headers=who("u2"))
    absent = await client.get(f"{BASE}/skills/{uuid.uuid4()}", headers=who("u2"))
    foreign = await client.get(f"{BASE}/skills/{ids['s-other']}", headers=who("u2"))
    assert hidden.status == absent.status == foreign.status == 404
    assert (await hidden.json())["code"] == (await absent.json())["code"] == "not_found"
    body = await (await client.get(f"{BASE}/skills/{ids['s-groups']}", headers=who("u3", groups="g1"))).json()
    assert {k: body[k] for k in ("tenant", "visibility", "allowed_groups", "access", "can_manage", "owner")} == {
        "tenant": "acme", "visibility": "groups", "allowed_groups": ["g1"], "access": "groups",
        "can_manage": False, "owner": "u1"}


async def test_publish_rules(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    resp, body = await publish(client, "x", who("u1", author=False))
    assert resp.status == 403 and body["code"] == "authoring_denied"
    resp, body = await publish(client, "x", who("u1"), visibility="groups")
    assert resp.status == 422 and body["code"] == "groups_required"
    resp, body = await publish(client, "x", who("u1", groups="g1"), visibility="groups", allowed_groups=["g2"])
    assert resp.status == 422 and body["code"] == "groups_not_allowed"
    resp, body = await publish(client, "x", who("u1", None), visibility="tenant")
    assert resp.status == 422 and body["code"] == "tenant_required"
    for key in ("owner", "created_by", "tenant"):
        resp, body = await publish(client, "x", who("u1"), **{key: "evil"})
        assert resp.status == 400 and body["code"] == "reserved_config_key", key
    resp, body = await publish(client, "stamped", who("u1"), owner="evil")  # sanity: refused, nothing stored
    assert await skill_names(client, who("u1")) == set()
    resp, body = await publish(client, "shared", who("u1"), visibility="tenant")
    assert resp.status == 201 and body["tenant"] == "acme" and body["owner"] == "u1"
    resp, body = await publish(client, "shared", who("u2"))
    assert resp.status == 409 and body["code"] == "name_taken" and "u1" not in body["message"]
    resp, _ = await publish(client, "shared", who("u9", "globex"))
    assert resp.status == 201


async def test_put_delete_404_before_403(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    ids = await seed(client)
    put = lambda sid, caller, **kw: client.put(f"{BASE}/skills/{sid}", json={**PAYLOAD, **kw}, headers=caller)  # noqa: E731
    assert (await put(ids["s-private"], who("u2"))).status == 404
    assert (await put(uuid.uuid4(), who("u2"))).status == 404
    assert (await put(ids["s-tenant"], who("u2"))).status == 403
    assert (await put(ids["s-tenant"], who("u1", author=False))).status == 403
    resp = await put(ids["s-tenant"], who("u1"), description="new")
    assert resp.status == 200 and (await resp.json())["version"] == 2
    assert (await put(ids["s-tenant"], who("u4", admin=True))).status == 200
    resp = await put(ids["s-tenant"], who("u1"), visibility="private")        # visibility only through /visibility
    assert resp.status == 400 and (await resp.json())["code"] == "reserved_config_key"
    delete = lambda sid, caller: client.delete(f"{BASE}/skills/{sid}", headers=caller)  # noqa: E731
    assert (await delete(ids["s-private"], who("u2"))).status == 404
    assert (await delete(ids["s-tenant"], who("u2"))).status == 403
    assert (await delete(ids["s-tenant"], who("u1"))).status == 200


async def test_import_rule(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    ids = await seed(client)
    assert (await create(client, "agent-u2", who("u2")))[0].status == 201
    assert (await create(client, "agent-u1-shared", who("u1"), visibility="tenant"))[0].status == 201
    imp = lambda agent, sid, caller: client.post(  # noqa: E731
        f"{BASE}/agents/{agent}/skills/import/{sid}", json={}, headers=caller)
    assert (await imp("agent-u2", ids["s-private"], who("u2"))).status == 404          # skill invisible
    assert (await imp("agent-u2", ids["s-other"], who("u2"))).status == 404            # skill of another tenant
    assert (await imp("agent-u1-shared", ids["s-tenant"], who("u2"))).status == 403    # agent visible, not manageable
    assert (await imp("agent-u1-private-none", ids["s-tenant"], who("u2"))).status == 404   # agent absent
    resp = await imp("agent-u2", ids["s-tenant"], who("u2"))                            # visible skill, own agent
    assert resp.status == 201, await resp.text()
    hidden_agent = await create(client, "agent-hidden", who("u1"))
    assert hidden_agent[0].status == 201
    assert (await imp("agent-hidden", ids["s-tenant"], who("u2"))).status == 404       # agent invisible


async def test_visibility_patch_rules(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    ids = await seed(client)
    url = lambda name: f"{BASE}/skills/{ids[name]}/visibility"  # noqa: E731
    body = {"visibility": "tenant"}
    assert (await client.patch(url("s-private"), json=body, headers=who("u2"))).status == 404
    assert (await client.patch(f"{BASE}/skills/{uuid.uuid4()}/visibility", json=body, headers=who("u2"))).status == 404
    assert (await client.patch(url("s-tenant"), json=body, headers=who("u2"))).status == 403
    resp = await client.patch(url("s-private"), json=body, headers=who("u1"))
    assert resp.status == 200 and (await resp.json())["visibility"] == "tenant"
    assert await skill_names(client, who("u2")) == {"s-private", "s-tenant"}
    resp = await client.patch(url("s-private"), json={"visibility": "groups"}, headers=who("u1"))
    assert resp.status == 422 and (await resp.json())["code"] == "groups_required"
    resp = await client.patch(url("s-private"), json={"visibility": "groups", "allowed_groups": ["g2"]},
                              headers=who("u1", groups="g1"))
    assert resp.status == 422 and (await resp.json())["code"] == "groups_not_allowed"
    resp = await client.patch(url("s-private"), json={"visibility": "private"}, headers=who("u4", admin=True))
    assert resp.status == 200 and await skill_names(client, who("u2")) == {"s-tenant"}
    resp = await client.patch(url("s-private"), json={"visibility": "tenant"}, headers=who("u1", None))
    assert resp.status == 422 and (await resp.json())["code"] == "tenant_required"
