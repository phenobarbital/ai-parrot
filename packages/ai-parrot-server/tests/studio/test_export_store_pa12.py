"""PA-12: tenant-partitioned export store and tenant-checked download.

Real app and routes, a real ``ArtifactStore`` over the real SQLite backend and a real local file manager.
"""
from __future__ import annotations

import time

import pytest

from parrot.storage.artifacts import ArtifactStore
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.exports import (
    ExportTooLarge,
    InvalidExportKey,
    build_export_key,
    parse_export_key,
    safe_filename,
)
from parrot.storage.overflow import OverflowStore
from navigator.utils.file import LocalFileManager

from .test_agents_db_mode import BASE, pool  # noqa: F401  (fixture)
from .test_agents_visibility import tenant_app, who


@pytest.fixture
def store(tmp_path):
    return ArtifactStore(
        dynamodb=ConversationSQLiteBackend(str(tmp_path / "c.db")),
        s3_overflow=OverflowStore(LocalFileManager(base_path=tmp_path / "files")),
    )


def _app(pool, store, **kw):  # noqa: F811
    app = tenant_app(pool, **kw)
    app["artifact_store"] = store
    return app


async def _get(client, url, caller):
    resp = await client.get(url, headers=caller)
    return resp, await resp.read()


async def test_a_tenants_export_downloads_for_that_tenant_only(aiohttp_client, pool, store):  # noqa: F811
    client = await aiohttp_client(_app(pool, store))
    ref = await store.save_export("acme", "agent-1", "report.csv", b"a,b\n1,2\n")
    assert ref.url == f"/api/v1/astudio/exports/{ref.key}" and ref.key.startswith("acme/agent-1/")
    resp, body = await _get(client, ref.url, who("u1", "acme"))
    assert resp.status == 200 and body == b"a,b\n1,2\n"
    assert resp.headers["Content-Disposition"] == 'attachment; filename="report.csv"'
    assert resp.headers["X-Content-Type-Options"] == "nosniff" and "no-store" in resp.headers["Cache-Control"]
    other, other_body = await _get(client, ref.url, who("u9", "globex"))
    assert other.status == 404 and b"acme" not in other_body          # 404, never 403, and nothing leaks
    nobody, _ = await _get(client, ref.url, who("u9", None))
    assert nobody.status == 404


async def test_the_untenanted_partition_is_its_own(aiohttp_client, pool, store):  # noqa: F811
    client = await aiohttp_client(_app(pool, store, resolver=False))
    ref = await store.save_export(None, None, "x.txt", b"hello")
    assert ref.key.startswith("-/agent/")
    resp, body = await _get(client, ref.url, who("u1", None))
    assert resp.status == 200 and body == b"hello"
    tenant_client = await aiohttp_client(_app(pool, store))
    resp, _ = await _get(tenant_client, ref.url, who("u1", "acme"))
    assert resp.status == 404


@pytest.mark.parametrize(
    "path",
    ["acme/agent-1/../../globex/x/1/a.txt", "acme/agent-1/%2e%2e/a.txt", "acme/a%2Fb/id/a.txt",
     "acme/agent-1/id/..%2f..%2fa.txt", "acme/agent-1/id/.hidden", "acme/agent-1/id"],
)
async def test_a_crafted_key_is_refused(aiohttp_client, pool, store, path):  # noqa: F811
    client = await aiohttp_client(_app(pool, store))
    resp, _ = await _get(client, f"{BASE}/exports/{path}", who("u1", "acme"))
    assert resp.status == 404


def test_key_building_and_parsing_reject_what_could_cross_a_partition():
    key = build_export_key("acme", "agent-1", "abc123", "../../etc/passwd")
    assert key == "acme/agent-1/abc123/passwd" and parse_export_key(key)[3] == "passwd"
    for bad_tenant in ("a/b", "..", "a..b", "a\x00b", "../x", "-"):  # "-" is the untenanted marker, never a tenant
        with pytest.raises(InvalidExportKey):
            build_export_key(bad_tenant, "agent", "id", "f.txt")
    for bad_key in ("a/b/c", "a/b/c/d/e", "acme/agent/../x", "acme/agent/id/.."):
        with pytest.raises(InvalidExportKey):
            parse_export_key(bad_key)
    assert safe_filename("a/b\\c.txt") == "c.txt" and safe_filename("...") == "export" and safe_filename("") == "export"


async def test_an_expired_export_is_404_and_deleted(aiohttp_client, pool, store):  # noqa: F811
    client = await aiohttp_client(_app(pool, store))
    ref = await store.save_export("acme", "agent-1", "old.txt", b"x", ttl=1)
    assert (await _get(client, ref.url, who("u1", "acme")))[0].status == 200
    time.sleep(1.2)
    assert (await _get(client, ref.url, who("u1", "acme")))[0].status == 404
    assert await store.file_manager.exists(f"exports/{ref.key}") is False       # lazily deleted


async def test_ttl_and_size_cap_come_from_the_environment(store, monkeypatch):
    monkeypatch.setenv("STUDIO_ARTIFACT_TTL_SECONDS", "60")
    monkeypatch.setenv("STUDIO_ARTIFACT_MAX_BYTES", "10")
    ref = await store.save_export("acme", "a", "f.txt", b"0123456789")
    assert 55 < ref.expires_at - time.time() <= 60
    with pytest.raises(ExportTooLarge):
        await store.save_export("acme", "a", "f.txt", b"01234567890")
    monkeypatch.setenv("STUDIO_ARTIFACT_TTL_SECONDS", "nope")
    monkeypatch.setenv("STUDIO_ARTIFACT_MAX_BYTES", "-3")
    ref = await store.save_export("acme", "a", "f.txt", b"x")
    assert ref.expires_at - time.time() > 6 * 24 * 3600                          # malformed -> the 7-day default


async def test_no_store_means_404_never_a_500(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    resp, _ = await _get(client, f"{BASE}/exports/acme/agent-1/id/f.txt", who("u1", "acme"))
    assert resp.status == 404


async def test_the_download_requires_a_session(aiohttp_client, pool, store):  # noqa: F811
    app = _app(pool, store)
    client = await aiohttp_client(app)
    ref = await store.save_export("acme", "agent-1", "f.txt", b"x")
    resp = await client.get(ref.url)                    # no X-Tenant: no tenant scope at all
    assert resp.status == 404
