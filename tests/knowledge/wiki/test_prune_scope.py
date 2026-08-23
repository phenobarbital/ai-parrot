"""Tests for scoped pruning (FEAT-450, D4.4 — cli._prune_removed).

A wiki plane is not always one corpus: a vault ingested into a repo's
plane shares it with the codebase pages. ``scope="root"`` keeps the two
from deleting each other on every run.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from parrot.knowledge.wiki.cli import _ingest_files, _open_sources, _prune_removed
from parrot.knowledge.wiki.project import WikiProjectConfig, save_project_config
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord
from parrot.knowledge.wiki.vault_scan import VAULT_EXCLUDE_DIRS, scan_vault


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """A minimal Obsidian vault with two notes."""
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    (root / "A.md").write_text("# A\n\nLinks to [[B]].\n", encoding="utf-8")
    (root / "notes").mkdir()
    (root / "notes" / "B.md").write_text("# B\n\n#tag\n", encoding="utf-8")
    return root


@pytest.fixture
def shared_plane(tmp_path: Path) -> tuple[Path, WikiProjectConfig, SQLiteWikiStore]:
    """A repo whose plane already holds codebase pages."""
    repo = tmp_path / "repo"
    repo.mkdir()
    config = WikiProjectConfig(wiki_name="repo")
    save_project_config(repo, config)
    storage = config.storage_path(repo)
    storage.mkdir(parents=True, exist_ok=True)
    store = SQLiteWikiStore(storage / "wiki.db", wiki_name="repo")
    return repo, config, store


async def _seed_repo_pages(store: SQLiteWikiStore) -> None:
    await store.upsert_pages([
        WikiPageRecord(concept_id="file:pkg/store.py", title="store"),
        WikiPageRecord(concept_id="dir:pkg", title="pkg/", category="module"),
    ])


class TestVaultExcludesParrot:
    def test_parrot_directory_is_not_scanned(self, vault: Path):
        parrot = vault / ".parrot" / "wiki"
        parrot.mkdir(parents=True)
        (parrot / "log.md").write_text("# log\n\nREMEMBER x\n", encoding="utf-8")
        (parrot / "index.md").write_text("# index\n", encoding="utf-8")

        scan, _stats = scan_vault(vault)
        scanned = {fs.rel_path for fs in scan.files}
        assert scanned == {"A.md", "notes/B.md"}

    def test_constant_mirrors_repo_scan(self):
        assert ".parrot" in VAULT_EXCLUDE_DIRS
        assert ".obsidian" in VAULT_EXCLUDE_DIRS


class TestPruneScope:
    @pytest.mark.asyncio
    async def test_root_scope_keeps_other_corpora(
        self, shared_plane, vault: Path
    ):
        repo, config, store = shared_plane
        await _seed_repo_pages(store)
        sources = _open_sources(repo, config, store=store)

        scan, _stats = scan_vault(vault)
        await _ingest_files(store, sources, vault, scan, force=True)
        await store.upsert_pages(scan.dir_records)
        await store.add_edges(scan.dir_edges)

        removed = await _prune_removed(
            store, sources, vault, scan, scope="root"
        )
        assert removed == 0
        surviving = {
            str(row["concept_id"]) for row in await store.list_pages(limit=1000)
        }
        assert "file:pkg/store.py" in surviving
        assert "dir:pkg" in surviving
        assert "file:A.md" in surviving

    @pytest.mark.asyncio
    async def test_plane_scope_still_prunes_everything_foreign(
        self, shared_plane, vault: Path
    ):
        repo, config, store = shared_plane
        await _seed_repo_pages(store)
        sources = _open_sources(repo, config, store=store)

        scan, _stats = scan_vault(vault)
        await _ingest_files(store, sources, vault, scan, force=True)
        await store.upsert_pages(scan.dir_records)

        removed = await _prune_removed(store, sources, vault, scan)
        assert removed >= 2
        surviving = {
            str(row["concept_id"]) for row in await store.list_pages(limit=1000)
        }
        assert "file:pkg/store.py" not in surviving
        assert "dir:pkg" not in surviving
        assert "file:A.md" in surviving

    @pytest.mark.asyncio
    async def test_root_scope_removes_a_deleted_note(
        self, shared_plane, vault: Path
    ):
        repo, config, store = shared_plane
        await _seed_repo_pages(store)
        sources = _open_sources(repo, config, store=store)

        scan, _stats = scan_vault(vault)
        await _ingest_files(store, sources, vault, scan, force=True)
        await store.upsert_pages(scan.dir_records)
        await store.add_edges(scan.dir_edges)

        # The user deletes notes/B.md — and with it the last note under
        # notes/, so `dir:notes` must go too.
        (vault / "notes" / "B.md").unlink()
        rescan, _stats = scan_vault(vault)
        removed = await _prune_removed(
            store, sources, vault, rescan, scope="root"
        )
        assert removed >= 1

        surviving = {
            str(row["concept_id"]) for row in await store.list_pages(limit=1000)
        }
        assert "file:notes/B.md" not in surviving
        assert "dir:notes" not in surviving
        # ...while the repo's pages and the surviving note are untouched.
        assert "file:pkg/store.py" in surviving
        assert "dir:pkg" in surviving
        assert "file:A.md" in surviving

    @pytest.mark.asyncio
    async def test_root_scope_keeps_a_dir_with_survivors(
        self, shared_plane, vault: Path
    ):
        repo, config, store = shared_plane
        sources = _open_sources(repo, config, store=store)
        (vault / "notes" / "C.md").write_text("# C\n", encoding="utf-8")

        scan, _stats = scan_vault(vault)
        await _ingest_files(store, sources, vault, scan, force=True)
        await store.upsert_pages(scan.dir_records)

        (vault / "notes" / "B.md").unlink()
        rescan, _stats = scan_vault(vault)
        await _prune_removed(store, sources, vault, rescan, scope="root")

        surviving = {
            str(row["concept_id"]) for row in await store.list_pages(limit=1000)
        }
        assert "file:notes/C.md" in surviving
        assert "dir:notes" in surviving
