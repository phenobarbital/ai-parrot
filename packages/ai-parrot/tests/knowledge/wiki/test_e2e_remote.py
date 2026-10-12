"""Loopback remote MCP evidence: server, client, proxy configuration, and SDK interop."""

from __future__ import annotations

import asyncio
import hashlib

import aiohttp
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
    """Serve two SQLite wiki test planes on one ephemeral loopback port."""
    monkeypatch.setenv("WIKITOOLKIT_SERVER_TOKEN", "t0k3n")
    monkeypatch.setenv("WIKITOOLKIT_TOKEN", "t0k3n")
    wikis = {}
    for name in ("a", "b"):
        root = tmp_path / name
        root.mkdir()
        config = WikiProjectConfig(wiki_name=name)
        save_project_config(root, config)
        store = create_wiki_store(config.storage_path(root), wiki_name=name, backend="sqlite")
        await store.upsert_pages([WikiPageRecord(concept_id="c", title=f"{name} page", body="fixture body")])
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


async def test_query_both_mounts_auth_and_404(served):
    """Both mounts answer, while the HTTP bearer gate rejects bad routes and tokens."""
    base_url, _ = served
    for name in ("a", "b"):
        async with RemoteWikiClient(WikiRemoteConfig(url=f"{base_url}/{name}"), actor="human:alice") as client:
            assert "wiki_query" in {tool["name"] for tool in await client.list_tools()}
            assert await client.call_tool_text("wiki_query", {"question": "page", "budget_tokens": 1200})

    async with aiohttp.ClientSession() as session:
        assert (await session.get(f"{base_url}/a/info")).status == 401
        assert (await session.get(f"{base_url}/missing/info", headers=HEADERS)).status == 404


async def test_actor_attribution_and_server_tool_surface(served):
    """A request actor becomes assertion attribution and server exposes all bulk tools."""
    base_url, app = served
    async with RemoteWikiClient(WikiRemoteConfig(url=f"{base_url}/a"), actor="human:alice") as client:
        names = {tool["name"] for tool in await client.list_tools()}
        assert {"wiki_query", "wiki_page_hashes", "wiki_ingest_batch", "wiki_sync_push", "wiki_sync_pull"} <= names
        await client.call_tool("wiki_remember", {"fact": "fact", "category": "note", "title": "memory"})

    page_id = "mem-" + hashlib.sha1("memory::note".encode()).hexdigest()[:12]
    page = await app["wiki_servers"]["a"][1].store.get_page(page_id)
    assert page is not None and page["asserted_by"] == "human:alice"


async def test_build_push_then_remote_outline(served, tmp_path, monkeypatch):
    """A local build pushes symbols for an outline served without that source tree."""
    base_url, _ = served
    client_root = tmp_path / "client"
    client_root.mkdir()
    (client_root / ".parrot").mkdir()
    (client_root / "pkg").mkdir()
    (client_root / "pkg" / "mod.py").write_text("def pushed_symbol() -> str:\n    return 'ok'\n")
    save_project_config(
        client_root,
        WikiProjectConfig(wiki_name="client", remote=WikiRemoteConfig(url=f"{base_url}/a")),
    )
    monkeypatch.chdir(client_root)

    result = await asyncio.to_thread(CliRunner().invoke, wiki, ["build", "--quiet", "--no-git"])
    assert result.exit_code == 0, result.output

    async with RemoteWikiClient(WikiRemoteConfig(url=f"{base_url}/a"), actor="human:alice") as client:
        outline = await client.call_tool_text(
            "wiki_code_outline",
            {"target": "file:pkg/mod.py", "depth": 2, "include_source": False, "namespace": None},
        )
    assert "pushed_symbol" in outline


def test_cli_proxy_configuration_requires_no_local_plane(tmp_path, monkeypatch):
    """A configured CLI proxy resolves before a local database is opened."""
    (tmp_path / ".parrot").mkdir()
    save_project_config(
        tmp_path, WikiProjectConfig(wiki_name="client", remote=WikiRemoteConfig(url="http://fake/mcp/a"))
    )
    monkeypatch.setenv("WIKITOOLKIT_TOKEN", "t0k3n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "parrot.knowledge.wiki.cli.remote_cli.call_remote_text", lambda *_args, **_kwargs: "remote page"
    )

    result = CliRunner().invoke(wiki, ["query", "page"])
    assert result.exit_code == 0, result.output
    assert "remote page" in result.output
    assert not (tmp_path / ".parrot" / "wiki" / "wiki.db").exists()


async def test_official_sdk_interop(served):
    """The official SDK can initialize and list the server tool surface when installed."""
    pytest.importorskip("mcp", reason="requires the mcp extra")
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError:
        # ``packages/ai-parrot/tests/mcp`` can shadow the SDK when that tests dir is on sys.path.
        pytest.skip("official `mcp` SDK is not importable (shadowed by tests/mcp or too old)")

    base_url, _ = served
    async with (
        streamablehttp_client(f"{base_url}/a", headers=HEADERS) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        assert "wiki_query" in {tool.name for tool in (await session.list_tools()).tools}
