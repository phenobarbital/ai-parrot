"""FEAT-621 W3 skills catalogue in database mode (AC4, AC6, AC16).

Real aiohttp app, the real Studio routes, a session middleware installing a real ``SessionData`` and a real
Postgres pool. ``AbstractBot.configure`` is replaced so no LLM starts; the shared ``SkillRegistry`` is a recording
fake so no embedding model loads (``test_index_not_under_agents_dir`` exercises the real location function).
"""
from __future__ import annotations

import pytest

from parrot.handlers.studio import skills_catalog as sc
from parrot.handlers.studio.skills_catalog import StudioSkillsCatalogHandler, reconcile_skills_catalog
from parrot.handlers.studio.storage.models import StudioPartition

from .test_agents_db_mode import BASE, _app, _create, _offline, pool  # noqa: F401  (fixtures)

PAYLOAD = {"name": "demo", "description": "a demo skill", "category": "general", "triggers": ["/demo"],
           "body": "Body text."}
TENANCY = {"tenant", "visibility", "allowed_groups"}


class _FakeRegistry:
    def __init__(self):
        self.uploads, self.revoked, self.fail = [], [], False

    async def upload_skill(self, **kwargs):
        if self.fail:
            raise RuntimeError("index down")
        self.uploads.append(kwargs["name"])

    async def get_skill_versions(self, _skill_id):
        return [1]

    async def revoke_skill(self, skill_id, reason=""):
        self.revoked.append(skill_id)


@pytest.fixture
def registry(monkeypatch):
    fake = _FakeRegistry()
    monkeypatch.setattr(sc, "_get_shared_skill_registry", lambda _app, _org, part=None: fake)
    return fake


class _AcmeSkills(StudioSkillsCatalogHandler):
    async def _studio_partition(self):
        return StudioPartition("acme")


async def _publish(client, user="u1", **extra):
    resp = await client.post(f"{BASE}/skills", json={**PAYLOAD, **extra}, headers={"X-User": user})
    return resp, await resp.json()


async def test_skills_shapes_add_tenancy_keys(aiohttp_client, pool, registry):
    client = await aiohttp_client(_app(pool))
    resp, body = await _publish(client)
    assert resp.status == 201 and TENANCY <= set(body)
    assert body["tenant"] is None and body["visibility"] == "private" and body["allowed_groups"] == []
    assert body["owner"] == "u1" and body["version"] == 1 and body["search_index_stale"] is False
    one = await (await client.get(f"{BASE}/skills/{body['skill_id']}")).json()
    assert TENANCY <= set(one) and one["versions"] == [1]
    await _publish(client, name="other", category="workflow")
    listing = await (await client.get(f"{BASE}/skills")).json()
    assert listing["count"] == 2 and set(listing["skills"]) == {"general", "workflow"}
    assert TENANCY <= set(listing["skills"]["workflow"][0])
    only = await (await client.get(f"{BASE}/skills", params={"category": "workflow"})).json()
    assert only["count"] == 1
    assert (await client.get(f"{BASE}/skills", params={"category": "nope"})).status == 400
    assert (await client.get(f"{BASE}/skills/not-a-uuid")).status == 404
    resp = await client.put(f"{BASE}/skills/{body['skill_id']}", json={**PAYLOAD, "description": "new"})
    updated = await resp.json()
    assert resp.status == 200 and updated["description"] == "new" and updated["version"] == 2
    resp = await client.delete(f"{BASE}/skills/{body['skill_id']}")
    assert resp.status == 200 and await resp.json() == {"skill_id": body["skill_id"], "deleted": True}
    assert registry.revoked == [body["skill_id"]]
    assert (await client.delete(f"{BASE}/skills/{body['skill_id']}")).status == 404


async def test_skills_owner_enforced(aiohttp_client, pool, registry):
    client = await aiohttp_client(_app(pool))
    _resp, body = await _publish(client)
    url = f"{BASE}/skills/{body['skill_id']}"
    assert (await client.put(url, json=PAYLOAD, headers={"X-User": "u2"})).status == 403
    assert (await client.delete(url, headers={"X-User": "u2"})).status == 403
    assert (await client.get(url)).status == 200


async def test_skills_unique_per_partition_409(aiohttp_client, pool, registry):
    app = _app(pool)
    app.router.add_view("/tenant/skills", _AcmeSkills)
    client = await aiohttp_client(app)
    resp, _ = await _publish(client)
    assert resp.status == 201
    resp, body = await _publish(client)
    assert resp.status == 409 and body["code"] == "duplicate"
    resp = await client.post("/tenant/skills", json=PAYLOAD)
    tenant_body = await resp.json()
    assert resp.status == 201 and tenant_body["tenant"] == "acme"
    assert (await client.post("/tenant/skills", json=PAYLOAD)).status == 409
    assert (await (await client.get(f"{BASE}/skills")).json())["count"] == 1
    assert (await (await client.get("/tenant/skills")).json())["count"] == 1
    assert (await client.get(f"{BASE}/skills/{tenant_body['skill_id']}")).status == 404


async def test_skills_expected_version_unsupported(aiohttp_client, pool, registry):
    client = await aiohttp_client(_app(pool))
    await _create(client)
    _resp, body = await _publish(client)
    url = f"{BASE}/skills/{body['skill_id']}"
    refused = [
        await client.post(f"{BASE}/skills", json={**PAYLOAD, "name": "x", "expected_version": 1}),
        await client.put(url, json={**PAYLOAD, "expected_version": 1}),
        await client.delete(url, params={"expected_version": "1"}),
        await client.post(f"{BASE}/agents/alpha/skills/import/{body['skill_id']}", json={"expected_version": 1}),
    ]
    for resp in refused:
        assert resp.status == 400 and (await resp.json())["code"] == "expected_version_unsupported"
    assert (await (await client.get(url)).json())["version"] == 1
    assert (await (await client.get(f"{BASE}/skills")).json())["count"] == 1
    services = client.app["studio_storage"].services
    assert await services.assets.list(StudioPartition.GLOBAL, "alpha", "skills") == []


async def test_import_writes_asset_row(aiohttp_client, pool, registry, tmp_path):
    client = await aiohttp_client(_app(pool))
    await _create(client)
    _resp, body = await _publish(client)
    url = f"{BASE}/agents/alpha/skills/import/{body['skill_id']}"
    resp = await client.post(url)
    assert resp.status == 201
    assert await resp.json() == {"agent": "alpha", "skill": "demo", "file_path": None, "reload_required": False}
    assets = client.app["studio_storage"].services.assets
    row = await assets.get(StudioPartition.GLOBAL, "alpha", "skills", "demo.md")
    assert row is not None and "Body text." in row.content and "name: demo" in row.content
    resp = await client.post(url)
    assert resp.status == 409 and (await resp.json())["code"] == "collision"
    assert (await client.post(url, json={"overwrite": True})).status == 201
    assert (await client.post(url, headers={"X-User": "u2"})).status == 403
    assert (await client.post(f"{BASE}/agents/nobody/skills/import/{body['skill_id']}")).status == 404
    assert (await client.post(f"{BASE}/agents/alpha/skills/import/{body['skill_id'][:-1]}{'1' if body['skill_id'][-1] == '0' else '0'}")).status == 404
    assert not (tmp_path / "agents" / "alpha").exists()


async def test_resync_rebuilds_from_postgres(aiohttp_client, pool, registry, monkeypatch):
    client = await aiohttp_client(_app(pool))
    registry.fail = True
    _resp, stale = await _publish(client)
    assert stale["search_index_stale"] is True
    assert (await (await client.get(f"{BASE}/skills/{stale['skill_id']}")).json())["search_index_stale"] is True
    registry.fail = False
    await _publish(client, name="fresh")
    assert registry.uploads == ["fresh"]
    assert (await client.post(f"{BASE}/skills/resync", headers={"X-User": "u2"})).status == 403
    # the test session is not a superuser: promote the caller the way the legacy admin tests do
    from parrot.handlers.studio._base import StudioBaseView

    real = StudioBaseView._get_user

    async def _admin(self):
        user = await real(self)
        user.is_superuser = True
        return user

    monkeypatch.setattr(StudioBaseView, "_get_user", _admin)
    resp = await client.post(f"{BASE}/skills/resync")
    assert resp.status == 200 and await resp.json() == {"resynced": 2, "failed": 0, "total": 2}
    assert sorted(registry.uploads) == ["demo", "fresh", "fresh"]
    listing = await (await client.get(f"{BASE}/skills")).json()
    assert [s["search_index_stale"] for s in listing["skills"]["general"]] == [False, False]
    await reconcile_skills_catalog(client.app)  # startup reconcile rebuilds the same way
    assert sorted(registry.uploads) == ["demo", "demo", "fresh", "fresh", "fresh"]


async def test_index_not_under_agents_dir(aiohttp_client, pool, monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(sc, "create_skill_registry", lambda **kw: seen.append(kw) or object())
    client = await aiohttp_client(_app(pool))
    app = client.app
    app.pop(sc._REGISTRIES_APP_KEY, None)  # the startup reconcile may have cached one
    seen.clear()
    sc._get_shared_skill_registry(app, "org1", StudioPartition.GLOBAL)
    sc._get_shared_skill_registry(app, "org1", StudioPartition("acme"))
    first, second = seen
    runtime = tmp_path / "rt"
    assert first["namespace"] == "org1/_shared" and second["namespace"] == "acme/_shared"
    assert first["persistence_path"] == runtime / "_shared" / "-" / "skills"
    assert second["persistence_path"] == runtime / "_shared" / "acme" / "skills"
    assert not str(first["persistence_path"]).startswith(str(tmp_path / "agents"))
    sc._get_shared_skill_registry(app, "org1", StudioPartition.GLOBAL)
    assert len(seen) == 2  # cached per namespace
    sc._get_shared_skill_registry(app, "org1")  # filesystem layout is unchanged
    assert seen[2]["persistence_path"].parts[-3:] == ("_shared", "org1", "skills")
