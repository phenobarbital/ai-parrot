"""Obsidian sync tests — mirror wiki planes into a vault, config-driven.

Covers `sync_obsidian` (selection by category, folder mapping,
idempotency, marker-guarded prune, dry-run, namespace planes) and the
`wikitoolkit sync obsidian` CLI wiring. Everything runs on local sqlite
planes and a tmp-dir vault — no Obsidian instance needed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from parrot.knowledge.wiki.obsidian_sync import (
    SYNC_ID_KEY,
    SYNC_MARKER_KEY,
    SYNC_SCOPE_KEY,
    ObsidianSyncError,
    folder_for_category,
    project_scope,
    sync_obsidian,
)
from parrot.knowledge.wiki.project import (
    ObsidianSyncConfig,
    WikiProjectConfig,
    load_effective_config,
)
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord
from parrot.knowledge.wiki.sync import _open_plane


def _page(cid: str, **kw) -> WikiPageRecord:
    """Shorthand page-record builder (mirrors test_sync.py's helper)."""
    defaults = {
        "concept_id": cid,
        "title": kw.pop("title", cid.replace("-", " ").title()),
        "category": kw.pop("category", "concept"),
        "summary": kw.pop("summary", f"Summary of {cid}"),
        "body": kw.pop("body", f"# {cid}\n\nBody of {cid}."),
        "origin": kw.pop("origin", "memory"),
    }
    defaults.update(kw)
    return WikiPageRecord(**defaults)


def _frontmatter(path: Path) -> dict:
    """Parse the YAML frontmatter block of a written note."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"no frontmatter in {path}"
    block = text.split("---\n", 2)[1]
    return yaml.safe_load(block)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("WIKI_ENV", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    # Keep the global namespace registry out of the picture.
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "parrot-home"))


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, BaseWikiStore, Path]:
    """A built sqlite plane plus a vault dir, both under `tmp_path`.

    The project config points `obsidian_sync.vault_dir` at the vault, so
    `sync_obsidian(root)` runs with no per-call overrides.
    """
    root = tmp_path / "repo"
    (root / ".parrot").mkdir(parents=True)
    vault = tmp_path / "vault"
    vault.mkdir()
    (root / ".parrot" / "wiki.json").write_text(
        json.dumps(
            {
                "wiki_name": "testwiki",
                "backend": "sqlite",
                "obsidian_sync": {"vault_dir": str(vault)},
            }
        ),
        encoding="utf-8",
    )
    store = _open_plane(root, load_effective_config(root).config)
    return root, store, vault


class TestConfigModel:
    def test_defaults(self) -> None:
        cfg = ObsidianSyncConfig()
        assert cfg.root_folder == "LLM Wiki"
        assert cfg.namespaces == ["local"]
        assert cfg.categories == []
        assert cfg.prune is False

    def test_rejects_escaping_folders(self) -> None:
        with pytest.raises(ValueError):
            ObsidianSyncConfig(root_folder="../outside")
        with pytest.raises(ValueError):
            ObsidianSyncConfig(folders={"concept": "/abs"})

    def test_rejects_bad_namespace_names(self) -> None:
        with pytest.raises(ValueError):
            ObsidianSyncConfig(namespaces=["bad::name"])

    def test_roundtrips_through_project_config(self) -> None:
        config = WikiProjectConfig.model_validate(
            {"obsidian_sync": {"categories": ["concept"], "folders": {"concept": "Concepts"}}}
        )
        assert config.obsidian_sync is not None
        assert config.obsidian_sync.folders == {"concept": "Concepts"}


class TestSyncBasics:
    async def test_creates_notes_under_category_folders(self, project) -> None:
        root, store, vault = project
        await store.upsert_pages([_page("alpha", category="concept"), _page("acme", category="entity")])
        report = await sync_obsidian(root)
        assert report.created == 2
        concept = vault / "LLM Wiki" / "concepts" / "alpha.md"
        entity = vault / "LLM Wiki" / "entities" / "acme.md"
        assert concept.is_file() and entity.is_file()
        front = _frontmatter(concept)
        assert front[SYNC_MARKER_KEY] == "testwiki"
        assert front[SYNC_ID_KEY] == "alpha"
        assert front["namespace"] == "local"
        assert "Body of alpha." in concept.read_text(encoding="utf-8")

    async def test_category_filter_and_folder_mapping(self, project) -> None:
        root, store, vault = project
        config_path = root / ".parrot" / "wiki.json"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        data["obsidian_sync"].update(
            {"categories": ["concept"], "folders": {"concept": "Ideas"}}
        )
        config_path.write_text(json.dumps(data), encoding="utf-8")
        await store.upsert_pages([_page("alpha", category="concept"), _page("acme", category="entity")])
        report = await sync_obsidian(root)
        assert report.created == 1
        assert (vault / "LLM Wiki" / "Ideas" / "alpha.md").is_file()
        assert not (vault / "LLM Wiki" / "entities" / "acme.md").exists()

    async def test_cli_category_override_wins(self, project) -> None:
        root, store, vault = project
        await store.upsert_pages([_page("alpha", category="concept"), _page("acme", category="entity")])
        report = await sync_obsidian(root, categories=["entity"])
        assert report.created == 1
        assert (vault / "LLM Wiki" / "entities" / "acme.md").is_file()

    async def test_edges_between_synced_pages_become_wikilinks(self, project) -> None:
        root, store, vault = project
        await store.upsert_pages([_page("alpha"), _page("beta"), _page("gamma", category="entity")])
        await store.add_edges(
            [
                ("alpha", "beta", "references", "asserted"),
                ("alpha", "gamma", "references", "asserted"),
            ]
        )
        await sync_obsidian(root, categories=["concept"])
        text = (vault / "LLM Wiki" / "concepts" / "alpha.md").read_text(encoding="utf-8")
        assert "## Related" in text
        assert "[[LLM Wiki/concepts/beta|Beta]]" in text
        # gamma was filtered out by category — no dangling wikilink to it.
        assert "gamma" not in text.split("## Related")[1]


class TestIdempotency:
    async def test_second_run_is_unchanged(self, project) -> None:
        root, store, _vault = project
        await store.upsert_pages([_page("alpha")])
        first = await sync_obsidian(root)
        second = await sync_obsidian(root)
        assert first.created == 1
        assert second.created == 0 and second.updated == 0
        assert second.unchanged == 1

    async def test_changed_page_is_updated(self, project) -> None:
        root, store, vault = project
        await store.upsert_pages([_page("alpha", body="old body")])
        await sync_obsidian(root)
        await store.upsert_pages([_page("alpha", body="new body")])
        report = await sync_obsidian(root)
        assert report.updated == 1
        assert "new body" in (vault / "LLM Wiki" / "concepts" / "alpha.md").read_text(encoding="utf-8")

    async def test_dry_run_writes_nothing(self, project) -> None:
        root, store, vault = project
        await store.upsert_pages([_page("alpha")])
        report = await sync_obsidian(root, dry_run=True)
        assert report.dry_run and report.created == 1
        assert not (vault / "LLM Wiki").exists()


class TestPrune:
    async def test_prunes_vanished_page_but_not_foreign_notes(self, project) -> None:
        root, store, vault = project
        await store.upsert_pages([_page("alpha"), _page("beta")])
        await sync_obsidian(root)
        # A hand-written note inside the managed folder, no marker.
        hand_written = vault / "LLM Wiki" / "concepts" / "mine.md"
        hand_written.write_text("# Mine\n\nHands off.\n", encoding="utf-8")
        await store.delete_page("beta")
        report = await sync_obsidian(root, prune=True)
        assert report.pruned == 1
        assert not (vault / "LLM Wiki" / "concepts" / "beta.md").exists()
        assert hand_written.is_file()
        assert (vault / "LLM Wiki" / "concepts" / "alpha.md").is_file()

    async def test_prune_dry_run_deletes_nothing(self, project) -> None:
        root, store, vault = project
        await store.upsert_pages([_page("alpha"), _page("beta")])
        await sync_obsidian(root)
        await store.delete_page("beta")
        report = await sync_obsidian(root, prune=True, dry_run=True)
        assert report.pruned == 1
        assert (vault / "LLM Wiki" / "concepts" / "beta.md").is_file()

    async def test_no_prune_by_default(self, project) -> None:
        root, store, vault = project
        await store.upsert_pages([_page("alpha"), _page("beta")])
        await sync_obsidian(root)
        await store.delete_page("beta")
        report = await sync_obsidian(root)
        assert report.pruned == 0
        assert (vault / "LLM Wiki" / "concepts" / "beta.md").is_file()


class TestPruneScope:
    async def test_shared_vault_same_wiki_name_never_cross_prunes(self, tmp_path: Path) -> None:
        """Two projects with the SAME wiki_name sharing one vault must not
        prune each other's notes (adversarial-review high finding)."""
        vault = tmp_path / "vault"
        vault.mkdir()
        stores = {}
        for repo in ("repo-a", "repo-b"):
            root = tmp_path / repo
            (root / ".parrot").mkdir(parents=True)
            (root / ".parrot" / "wiki.json").write_text(
                json.dumps(
                    {
                        "wiki_name": "codebase",  # the common default
                        "backend": "sqlite",
                        "obsidian_sync": {"vault_dir": str(vault)},
                    }
                ),
                encoding="utf-8",
            )
            stores[repo] = _open_plane(root, load_effective_config(root).config)
        await stores["repo-a"].upsert_pages([_page("alpha")])
        await stores["repo-b"].upsert_pages([_page("beta")])
        await sync_obsidian(tmp_path / "repo-a")
        await sync_obsidian(tmp_path / "repo-b")
        report = await sync_obsidian(tmp_path / "repo-a", prune=True)
        assert report.pruned == 0
        assert (vault / "LLM Wiki" / "concepts" / "alpha.md").is_file()
        assert (vault / "LLM Wiki" / "concepts" / "beta.md").is_file()

    async def test_scope_written_and_stable(self, project) -> None:
        root, store, vault = project
        await store.upsert_pages([_page("alpha")])
        await sync_obsidian(root)
        front = _frontmatter(vault / "LLM Wiki" / "concepts" / "alpha.md")
        assert front[SYNC_SCOPE_KEY] == project_scope(root, "testwiki")
        assert front[SYNC_SCOPE_KEY].startswith("testwiki@")

    async def test_prune_deselected_category(self, project) -> None:
        """Narrowing the category selection prunes the now-deselected notes."""
        root, store, vault = project
        await store.upsert_pages([_page("alpha", category="concept"), _page("acme", category="entity")])
        await sync_obsidian(root)
        report = await sync_obsidian(root, categories=["entity"], prune=True)
        assert report.pruned == 1
        assert not (vault / "LLM Wiki" / "concepts" / "alpha.md").exists()
        assert (vault / "LLM Wiki" / "entities" / "acme.md").is_file()


class TestPathSafety:
    def test_empty_folder_override_is_honored(self) -> None:
        from parrot.knowledge.wiki.project import ObsidianSyncConfig

        cfg = ObsidianSyncConfig(folders={"concept": ""})
        assert folder_for_category("concept", cfg) == ""

    async def test_empty_folder_override_places_notes_under_root(self, project) -> None:
        root, store, vault = project
        config_path = root / ".parrot" / "wiki.json"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        data["obsidian_sync"]["folders"] = {"concept": ""}
        config_path.write_text(json.dumps(data), encoding="utf-8")
        await store.upsert_pages([_page("alpha")])
        report = await sync_obsidian(root)
        assert report.created == 1
        assert (vault / "LLM Wiki" / "alpha.md").is_file()

    async def test_traversal_shaped_category_is_sanitized(self, project) -> None:
        """A hostile category value from page data must neither escape the
        vault nor crash the run with an untyped error."""
        root, store, vault = project
        await store.upsert_pages([_page("evil", category="../../outside")])
        report = await sync_obsidian(root)
        assert report.created == 1
        written = list((vault / "LLM Wiki").rglob("evil.md"))
        assert len(written) == 1  # landed inside the managed subtree
        assert not (vault.parent / "outside").exists()


class TestGuards:
    async def test_no_vault_configured_raises(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        (root / ".parrot").mkdir(parents=True)
        (root / ".parrot" / "wiki.json").write_text(json.dumps({"backend": "sqlite"}), encoding="utf-8")
        _open_plane(root, load_effective_config(root).config)  # build the plane
        with pytest.raises(ObsidianSyncError, match="No Obsidian vault"):
            await sync_obsidian(root)

    async def test_unbuilt_local_plane_raises(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        (root / ".parrot").mkdir(parents=True)
        vault = tmp_path / "vault"
        vault.mkdir()
        (root / ".parrot" / "wiki.json").write_text(
            json.dumps({"backend": "sqlite", "obsidian_sync": {"vault_dir": str(vault)}}),
            encoding="utf-8",
        )
        with pytest.raises(ObsidianSyncError, match="not built"):
            await sync_obsidian(root)

    async def test_unknown_namespace_raises(self, project) -> None:
        root, _store, _vault = project
        with pytest.raises(ObsidianSyncError, match="Unknown namespace"):
            await sync_obsidian(root, namespaces=["nope"])

    async def test_configured_but_missing_vault_is_distinguished(self, project, tmp_path: Path) -> None:
        root, _store, _vault = project
        with pytest.raises(ObsidianSyncError, match="does not exist"):
            await sync_obsidian(root, vault=str(tmp_path / "no-such-vault"))

    async def test_unopenable_namespace_is_skipped_not_fatal(self, project, tmp_path: Path) -> None:
        """A declared-but-unbuilt namespace is reported and skipped; the
        local plane still syncs and prune leaves the skip's subtree alone."""
        root, store, _vault = project
        await store.upsert_pages([_page("alpha")])
        config_path = root / ".parrot" / "wiki.json"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        data["namespaces"] = {"ghost": {"store": str(tmp_path / "missing-plane")}}
        config_path.write_text(json.dumps(data), encoding="utf-8")
        report = await sync_obsidian(root, namespaces=["local", "ghost"], prune=True)
        assert report.namespaces == ["local"]
        assert report.skipped_namespaces and report.skipped_namespaces[0].startswith("ghost:")
        assert report.created == 1


class TestNamespacePlanes:
    async def test_store_namespace_lands_in_its_own_subtree(self, project, tmp_path: Path) -> None:
        root, store, vault = project
        await store.upsert_pages([_page("alpha")])
        # A second, pre-built plane declared as a store-kind namespace.
        other_dir = tmp_path / "other-plane"
        other_dir.mkdir()
        other = _open_plane(
            root,
            load_effective_config(root).config.model_copy(update={"storage_dir": str(other_dir)}),
        )
        await other.upsert_pages([_page("issue-1", category="summary")])
        config_path = root / ".parrot" / "wiki.json"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        data["namespaces"] = {"issues": {"store": str(other_dir)}}
        config_path.write_text(json.dumps(data), encoding="utf-8")

        report = await sync_obsidian(root, namespaces=["local", "issues"])
        assert sorted(report.namespaces) == ["issues", "local"]
        assert (vault / "LLM Wiki" / "concepts" / "alpha.md").is_file()
        note = vault / "LLM Wiki" / "issues" / "summaries" / "issue-1.md"
        assert note.is_file()
        assert _frontmatter(note)["namespace"] == "issues"


class TestCli:
    def test_sync_obsidian_command(self, project) -> None:
        from parrot.knowledge.wiki.cli import wiki

        root, store, vault = project
        import asyncio

        asyncio.run(store.upsert_pages([_page("alpha")]))
        runner = CliRunner()
        result = runner.invoke(wiki, ["sync", "obsidian", "--path", str(root)])
        assert result.exit_code == 0, result.output
        assert "created=1" in result.output
        assert (vault / "LLM Wiki" / "concepts" / "alpha.md").is_file()

    def test_sync_obsidian_dry_run_output(self, project) -> None:
        from parrot.knowledge.wiki.cli import wiki

        root, store, vault = project
        import asyncio

        asyncio.run(store.upsert_pages([_page("alpha")]))
        runner = CliRunner()
        result = runner.invoke(wiki, ["sync", "obsidian", "--path", str(root), "--dry-run", "-v"])
        assert result.exit_code == 0, result.output
        assert "DRY RUN" in result.output
        assert "created: LLM Wiki/concepts/alpha.md" in result.output
        assert not (vault / "LLM Wiki").exists()
