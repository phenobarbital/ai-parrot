"""Application-level tests for ``wikitoolkit serve`` (FEAT-569)."""

from __future__ import annotations

import aiohttp
import hashlib
import pytest
from aiohttp import web
from click.testing import CliRunner

pytest.importorskip("parrot.mcp.transports.streamable_http")

from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.project import WikiProjectConfig, WikiRemoteConfig, save_project_config
from parrot.knowledge.wiki.remote import RemoteWikiClient
from parrot.knowledge.wiki.serve import WikiServerConfig, build_server_app
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store

HEADERS = {"Authorization": "Bearer t0k3n"}


@pytest.fixture
async def served(tmp_path, monkeypatch):
    """Serve two small SQLite wiki fixtures on a randomly assigned port."""
    monkeypatch.setenv("WIKITOOLKIT_SERVER_TOKEN", "t0k3n")
    wikis = {}
    for name in ("a", "b"):
        root = tmp_path / name
        root.mkdir()
        config = WikiProjectConfig(wiki_name=name)
        save_project_config(root, config)
        store = create_wiki_store(config.storage_path(root), wiki_name=name, backend="sqlite")
        await store.upsert_pages([WikiPageRecord(concept_id="c", title="c", body="b")])
        wikis[name] = {"root": str(root)}

    app = await build_server_app(WikiServerConfig(wikis=wikis, allow_sqlite_for_tests=True))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    try:
        yield f"http://127.0.0.1:{runner.addresses[0][1]}/mcp", app
    finally:
        await runner.cleanup()


async def test_info_is_authenticated_and_mounts_each_wiki(served):
    """Info exposes only mounted wikis and uses the same bearer gate as MCP."""
    base_url, _ = served
    async with aiohttp.ClientSession() as session:
        assert (await session.get(f"{base_url}/a/info")).status == 401
        response = await session.get(f"{base_url}/a/info", headers=HEADERS)
        assert response.status == 200
        assert (await response.json())["tools_count"] >= 13
        assert (await session.get(f"{base_url}/zzz/info", headers=HEADERS)).status == 404


async def test_tools_include_bulk_tools_and_actor_header_is_propagated(served, monkeypatch):
    """MCP tool calls expose bulk tools and preserve an explicit request actor."""
    base_url, app = served
    monkeypatch.setenv("WIKITOOLKIT_TOKEN", "t0k3n")
    remote = WikiRemoteConfig(url=f"{base_url}/a")
    async with RemoteWikiClient(remote, actor="human:alice") as client:
        names = {tool["name"] for tool in await client.list_tools()}
        assert {"wiki_query", "wiki_ingest_batch", "wiki_sync_pull"} <= names
        await client.call_tool("wiki_remember", {"fact": "fact", "category": "note", "title": "memory"})

    page_id = "mem-" + hashlib.sha1("memory::note".encode()).hexdigest()[:12]
    page = await app["wiki_servers"]["a"][1].store.get_page(page_id)
    assert page is not None
    assert page["asserted_by"] == "human:alice"


def test_serve_help_lists_server_options_without_workers():
    """The CLI exposes one-process serving controls and no worker option."""
    result = CliRunner().invoke(wiki, ["serve", "--help"])
    assert result.exit_code == 0
    for option in ("--config", "--host", "--port", "--ssl-cert", "--ssl-key"):
        assert option in result.output
    assert "--workers" not in result.output
