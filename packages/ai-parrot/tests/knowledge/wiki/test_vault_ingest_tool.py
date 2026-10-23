"""Tests for VaultIngestTool and vault_dir resolution (Obsidian over MCP)."""
import pytest

from parrot.knowledge.wiki.project import (
    WikiProjectConfig,
    resolve_vault_dir,
    wiki_write_lock,
)
from parrot.knowledge.wiki.store import create_wiki_store
from parrot.knowledge.wiki.tools import VaultIngestTool
from tests.interfaces.obsidian.conftest import fixture_vault  # noqa: F401


class TestResolveVaultDir:
    def test_override_wins(self, tmp_path, fixture_vault):
        config = WikiProjectConfig(vault_dir="somewhere-else")
        assert (
            resolve_vault_dir(tmp_path, config, override=fixture_vault)
            == fixture_vault.resolve()
        )

    def test_config_relative(self, tmp_path, fixture_vault):
        config = WikiProjectConfig(vault_dir="vault")
        assert resolve_vault_dir(tmp_path, config) == fixture_vault.resolve()

    def test_config_absolute(self, tmp_path, fixture_vault):
        config = WikiProjectConfig(vault_dir=str(fixture_vault))
        assert resolve_vault_dir(tmp_path, config) == fixture_vault.resolve()

    def test_root_autodetect(self, fixture_vault):
        config = WikiProjectConfig()
        assert resolve_vault_dir(fixture_vault, config) == fixture_vault.resolve()

    def test_no_vault_returns_none(self, tmp_path):
        assert resolve_vault_dir(tmp_path, WikiProjectConfig()) is None

    def test_missing_configured_dir_returns_none(self, tmp_path):
        config = WikiProjectConfig(vault_dir="does-not-exist")
        assert resolve_vault_dir(tmp_path, config) is None


@pytest.fixture
def project(tmp_path, fixture_vault):
    """A wiki project (root=tmp_path) configured to serve fixture_vault."""
    config = WikiProjectConfig(wiki_name="vaultwiki", vault_dir=str(fixture_vault))
    storage = config.storage_path(tmp_path)
    storage.mkdir(parents=True, exist_ok=True)
    store = create_wiki_store(storage, wiki_name="vaultwiki")
    return tmp_path, config, store


class TestVaultIngestTool:
    @pytest.mark.asyncio
    async def test_ingest_happy_path(self, project):
        root, config, store = project
        tool = VaultIngestTool(store, root=root, config=config)
        result = await tool._execute()
        assert result.success, result.error
        payload = result.result
        assert payload["notes"] == 7
        assert payload["ingested"] == 7
        assert payload["wikilink_edges"] >= 3
        assert payload["pages_total"] > 7  # notes + dirs + tags

        # Pages are queryable in the plane, backlinks traversable.
        hits = await store.search_fts("machine learning", limit=5)
        assert any("machine-learning" in h["concept_id"] for h in hits)
        incoming = await store.neighbors(
            "file:concepts/machine-learning.md", direction="in"
        )
        assert any(
            row["concept_id"] == "file:daily/2026-07-30.md" for row in incoming
        )

    @pytest.mark.asyncio
    async def test_second_run_incremental(self, project):
        root, config, store = project
        tool = VaultIngestTool(store, root=root, config=config)
        await tool._execute()
        second = await tool._execute()
        assert second.success
        assert second.result["ingested"] == 0
        assert second.result["unchanged"] == 7

    @pytest.mark.asyncio
    async def test_force_reingests(self, project):
        root, config, store = project
        tool = VaultIngestTool(store, root=root, config=config)
        await tool._execute()
        forced = await tool._execute(force=True)
        assert forced.success
        assert forced.result["ingested"] == 7

    @pytest.mark.asyncio
    async def test_vault_path_override(self, tmp_path, fixture_vault):
        config = WikiProjectConfig(wiki_name="w")  # no vault_dir
        storage = config.storage_path(tmp_path)
        storage.mkdir(parents=True, exist_ok=True)
        store = create_wiki_store(storage, wiki_name="w")
        tool = VaultIngestTool(store, root=tmp_path, config=config)
        result = await tool._execute(vault_path=str(fixture_vault))
        assert result.success
        assert result.result["notes"] == 7

    @pytest.mark.asyncio
    async def test_no_vault_errors(self, tmp_path):
        config = WikiProjectConfig(wiki_name="w")
        storage = config.storage_path(tmp_path)
        storage.mkdir(parents=True, exist_ok=True)
        store = create_wiki_store(storage, wiki_name="w")
        tool = VaultIngestTool(store, root=tmp_path, config=config)
        result = await tool._execute()
        assert result.success is False
        assert "No Obsidian vault" in result.error

    @pytest.mark.asyncio
    async def test_lock_contention_refused(self, project):
        root, config, store = project
        tool = VaultIngestTool(store, root=root, config=config)
        with wiki_write_lock(config.storage_path(root)) as held:
            assert held
            result = await tool._execute()
        assert result.success is False
        assert "writer" in result.error
