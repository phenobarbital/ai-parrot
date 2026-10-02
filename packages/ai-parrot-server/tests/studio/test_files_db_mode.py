"""FEAT-621 W3 files in database mode (AC4, AC8, AC13, AC16).

Real aiohttp app, the real Studio routes, a session middleware installing a real ``SessionData`` and a real
Postgres pool. ``AbstractBot.configure`` is replaced so no LLM is ever started.
"""
from __future__ import annotations

import hashlib

from .test_agents_db_mode import BASE, _app, _create, _offline, pool  # noqa: F401  (fixtures)
from parrot.handlers.studio.storage.models import StudioPartition

SKILL = "---\nname: demo\ndescription: a demo skill\ntriggers:\n  - /demo\n---\nBody text.\n"


def _url(kind, name=""):
    return f"{BASE}/agents/alpha/files/{kind}" + (f"/{name}" if name else "")


async def _row_count(client, kind="kb"):
    return len(await client.app["studio_storage"].services.assets.list(StudioPartition.GLOBAL, "alpha", kind))


async def test_files_put_get_delete_shapes(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    await _create(client)
    resp = await client.put(_url("kb", "notes.md"), json={"content": "hello"})
    body = await resp.json()
    assert resp.status == 200
    assert body == {"path": "notes.md", "kind": "kb", "size": 5, "reload_required": False, "version": body["version"],
                    "sha256": hashlib.sha256(b"hello").hexdigest()}
    assert body["version"] >= 2
    got = await (await client.get(_url("kb", "notes.md"))).json()
    assert got["content"] == "hello" and got["size"] == 5 and got["sha256"] == body["sha256"]
    assert got["path"] == "notes.md" and got["kind"] == "kb" and got["version"] == body["version"]
    resp = await client.delete(_url("kb", "notes.md"))
    gone = await resp.json()
    assert resp.status == 200 and gone["deleted"] is True and gone["reload_required"] is False
    assert gone["path"] == "notes.md" and gone["kind"] == "kb" and gone["version"] > body["version"]
    assert (await client.get(_url("kb", "notes.md"))).status == 404
    assert (await client.delete(_url("kb", "notes.md"))).status == 404
    assert (await client.put(_url("kb", "x.md"), json={})).status == 400
    assert (await client.put(_url("kb", "x.md"), headers={"X-User": "u2"}, json={"content": "a"})).status == 403
    assert (await client.get(f"{BASE}/agents/nobody/files/kb")).status == 404
    assert (await client.get(f"{BASE}/agents/alpha/files/bogus")).status == 400


async def test_files_list_shape_unchanged(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    await _create(client)
    assert await (await client.get(_url("kb"))).json() == {"kind": "kb", "files": []}
    await client.put(_url("kb", "b.md"), json={"content": "b"})
    await client.put(_url("kb", "a.txt"), json={"content": "a"})
    resp = await client.put(_url("skills", "demo/SKILL.md"), json={"content": SKILL})
    assert resp.status == 200, await resp.text()
    assert await (await client.get(_url("kb"))).json() == {"kind": "kb", "files": ["a.txt", "b.md"]}
    assert await (await client.get(_url("skills"))).json() == {"kind": "skills", "files": ["demo/SKILL.md"]}


async def test_files_413_415_codes(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    await _create(client)
    resp = await client.put(_url("identity", "role.md"), json={"content": "x" * (65 * 1024)})
    assert resp.status == 413 and (await resp.json())["code"] == "asset_too_large"
    resp = await client.put(_url("kb", "a.md"), json={"content": "x", "content_type": "application/pdf"})
    assert resp.status == 415 and (await resp.json())["code"] == "binary_assets_unsupported"
    storage = client.app["studio_storage"]
    storage.services.assets._limits = type(storage.services.assets._limits)(agent_total_max=10)
    resp = await client.put(_url("kb", "big.md"), json={"content": "x" * 11})
    assert resp.status == 413 and (await resp.json())["code"] == "agent_assets_quota"
    assert await _row_count(client) == 0
    resp = await client.put(_url("skills", "bad.md"), json={"content": "no frontmatter"})
    assert resp.status == 422
    assert (await client.put(_url("kb", "sub/a.md"), json={"content": "x"})).status in (400, 422)


async def test_files_stale_expected_version(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    await _create(client)
    first = await (await client.put(_url("kb", "a.md"), json={"content": "one"})).json()
    version = first["version"]
    resp = await client.put(_url("kb", "a.md"), json={"content": "two", "expected_version": version - 1})
    assert resp.status == 409 and (await resp.json())["code"] == "version_conflict"
    assert (await (await client.get(_url("kb", "a.md"))).json())["content"] == "one"
    resp = await client.delete(_url("kb", "a.md"), params={"expected_version": str(version - 1)})
    assert resp.status == 409 and (await resp.json())["code"] == "version_conflict"
    assert await _row_count(client) == 1
    resp = await client.put(_url("kb", "a.md"), json={"content": "two", "expected_version": version})
    assert resp.status == 200
    resp = await client.put(_url("kb", "a.md"), json={"content": "x", "expected_version": "nope"})
    assert resp.status == 400
    resp = await client.delete(_url("kb", "a.md"), params={"expected_version": str(version + 1)})
    assert resp.status == 200


async def test_files_policy_refusal_422(aiohttp_client, pool, monkeypatch):
    from parrot.tools import tooling_policy

    client = await aiohttp_client(_app(pool))
    await _create(client)

    def _refuse(app, tooling, *, subject):
        raise tooling_policy.TenantToolingRefused("endpoint_not_allowed", item="srv")

    monkeypatch.setattr(tooling_policy, "enforce_tenant_tooling", _refuse)
    resp = await client.put(_url("kb", "a.md"), json={"content": "x"})
    assert resp.status == 422 and (await resp.json())["code"] == "tooling_not_permitted"
    assert await _row_count(client) == 0
    resp = await client.delete(_url("kb", "a.md"))
    assert resp.status == 422 and (await resp.json())["code"] == "tooling_not_permitted"


async def test_files_legacy_agent_takes_filesystem_path(aiohttp_client, pool, monkeypatch, tmp_path):
    from parrot.bots.basic import BasicBot
    from parrot.handlers.studio import files as files_module

    monkeypatch.setattr(files_module, "AGENTS_DIR", tmp_path / "agents")
    client = await aiohttp_client(_app(pool))
    client.app["bot_manager"].registry.register("legacy-one", BasicBot)
    (tmp_path / "agents" / "legacy-one" / "kb").mkdir(parents=True)
    (tmp_path / "agents" / "legacy-one" / "kb" / "n.md").write_text("hi")
    url = f"{BASE}/agents/legacy-one/files/kb"
    assert await (await client.get(url)).json() == {"kind": "kb", "files": ["n.md"]}
    got = await (await client.get(url + "/n.md")).json()
    assert got == {"path": "n.md", "kind": "kb", "size": 2, "content": "hi"}


async def test_files_put_invalid_content_is_422_not_500(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    await _create(client)
    resp = await client.put(_url("kb", "n.md"), json={"content": 123})
    body = await resp.json()
    assert resp.status == 422 and body["code"] == "validation_error"
    assert await _row_count(client) == 0
