"""FEAT-498 TASK-2749 — ``StructuralService`` lookup/outline/blast_radius."""

from __future__ import annotations

from pathlib import Path

import pytest
from parrot.knowledge.wiki.cli import _ingest_files, _open_sources, _open_store
from parrot.knowledge.wiki.project import WikiProjectConfig, wiki_write_lock
from parrot.knowledge.wiki.repo_scan import scan_repository
from parrot.knowledge.wiki.structural import StructuralService
from parrot.knowledge.wiki.symbols import SymbolKind


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


async def _build(tmp_path: Path, files: dict[str, str]) -> tuple[StructuralService, Path]:
    """Build a one-off tmp repo + sqlite plane + service for a custom fixture set."""
    root = tmp_path / "repo"
    root.mkdir()
    for rel, content in files.items():
        _write(root, rel, content)

    config = WikiProjectConfig()
    store = _open_store(root, config)
    sources = _open_sources(root, config, store=store)
    scan = scan_repository(root, use_git=False)
    await _ingest_files(store, sources, root, scan)
    return StructuralService(store, root, config), root


class TestLookup:
    @pytest.mark.asyncio
    async def test_exact_qualname_beats_fts(self, built_repo):
        svc, _root = built_repo
        out = await svc.lookup("helper")
        assert out.hits
        assert out.hits[0].qualname == "helper"
        assert out.hits[0].score == 1.0
        assert not out.repaired_files

    @pytest.mark.asyncio
    async def test_limit_is_honoured(self, built_repo):
        svc, _root = built_repo
        out = await svc.lookup("helper", limit=1)
        assert len(out.hits) <= 1

    @pytest.mark.asyncio
    async def test_language_filter(self, built_repo):
        svc, _root = built_repo
        out = await svc.lookup("helper", language="php")
        assert all(hit.rel_path.endswith(".php") for hit in out.hits)

    @pytest.mark.asyncio
    async def test_path_prefix_filter(self, built_repo):
        svc, _root = built_repo
        out = await svc.lookup("helper", path_prefix="a.py")
        assert all(hit.rel_path.startswith("a.py") for hit in out.hits)

    @pytest.mark.asyncio
    async def test_kind_filter(self, built_repo):
        svc, _root = built_repo
        out = await svc.lookup("helper", kind=SymbolKind.FUNCTION)
        assert all(hit.kind == SymbolKind.FUNCTION for hit in out.hits)


class TestOutline:
    @pytest.mark.asyncio
    async def test_outline_lists_file_symbols(self, built_repo):
        svc, _root = built_repo
        out = await svc.outline("file:a.py")
        names = {hit.qualname for hit in out.symbols}
        assert "helper" in names
        assert out.language == "python"

    @pytest.mark.asyncio
    async def test_outline_accepts_sym_id(self, built_repo):
        svc, _root = built_repo
        out = await svc.outline("sym:a.py#helper")
        assert {hit.qualname for hit in out.symbols} == {"helper"}

    @pytest.mark.asyncio
    async def test_outline_bare_relative_path(self, built_repo):
        svc, _root = built_repo
        out = await svc.outline("a.py")
        assert any(hit.qualname == "helper" for hit in out.symbols)

    @pytest.mark.asyncio
    async def test_outline_include_source_excerpt(self, built_repo):
        svc, _root = built_repo
        out = await svc.outline("sym:a.py#helper", include_source=True)
        assert out.source is not None
        assert "return 1" in out.source
        assert not out.truncated

    @pytest.mark.asyncio
    async def test_outline_rejects_parent_traversal(self, built_repo):
        svc, _root = built_repo
        out = await svc.outline("../outside.py")
        assert out.symbols == []

    @pytest.mark.asyncio
    async def test_outline_rejects_absolute_outside_root(self, built_repo, tmp_path):
        svc, _root = built_repo
        outside = tmp_path / "outside.py"
        outside.write_text("def x(): ...\n")
        out = await svc.outline(f"file:{outside}")
        assert out.symbols == []

    @pytest.mark.asyncio
    async def test_outline_rejects_parrot_dir(self, built_repo):
        svc, _root = built_repo
        out = await svc.outline("file:.parrot/wiki/wiki.db")
        assert out.symbols == []


class TestBlastRadius:
    @pytest.mark.asyncio
    async def test_finds_dependent_caller(self, built_repo):
        svc, _root = built_repo
        out = await svc.blast_radius("sym:a.py#helper")
        assert out.root is not None
        assert out.root.qualname == "helper"
        impacted_ids = {imp.symbol.symbol_id for imp in out.impacted}
        assert "sym:b.py#run" in impacted_ids
        run_impact = next(imp for imp in out.impacted if imp.symbol.symbol_id == "sym:b.py#run")
        assert run_impact.via == "calls"
        assert run_impact.provenance == "extracted"
        assert out.files == ["b.py"]
        assert not out.truncated

    @pytest.mark.asyncio
    async def test_resolves_by_exact_qualname(self, built_repo):
        svc, _root = built_repo
        out = await svc.blast_radius("helper")
        assert out.root is not None and out.root.qualname == "helper"

    @pytest.mark.asyncio
    async def test_unknown_symbol_returns_empty(self, built_repo):
        svc, _root = built_repo
        out = await svc.blast_radius("sym:missing.py#nope")
        assert out.root is None
        assert out.impacted == []

    @pytest.mark.asyncio
    async def test_include_tests_false_filters_test_paths(self, tmp_path):
        svc, _root = await _build(
            tmp_path,
            {
                "a.py": "def helper():\n    return 1\n",
                "tests/test_a.py": (
                    "from a import helper\n\n\ndef test_it():\n    return helper()\n"
                ),
            },
        )
        out_with_tests = await svc.blast_radius("sym:a.py#helper", include_tests=True)
        assert any(imp.symbol.rel_path.startswith("tests/") for imp in out_with_tests.impacted)

        out_without_tests = await svc.blast_radius("sym:a.py#helper", include_tests=False)
        assert not any(imp.symbol.rel_path.startswith("tests/") for imp in out_without_tests.impacted)

    @pytest.mark.asyncio
    async def test_include_inferred_false_drops_inferred_edges(self, tmp_path):
        svc, _root = await _build(
            tmp_path,
            {
                "d.py": "def unique_fn():\n    return 1\n",
                "c.py": "def go():\n    return unique_fn()\n",
            },
        )
        out_all = await svc.blast_radius("sym:d.py#unique_fn", include_inferred=True)
        assert any(imp.symbol.symbol_id == "sym:c.py#go" for imp in out_all.impacted)

        out_no_inferred = await svc.blast_radius("sym:d.py#unique_fn", include_inferred=False)
        assert not any(imp.symbol.symbol_id == "sym:c.py#go" for imp in out_no_inferred.impacted)

    @pytest.mark.asyncio
    async def test_dangling_target_skipped(self, built_repo):
        svc, _root = built_repo
        # Fabricate an edge into a concept id that has no backing page —
        # blast_radius must skip it silently rather than raising.
        await svc._store.add_edges([("sym:ghost.py#phantom", "sym:a.py#helper", "calls", "inferred")])
        out = await svc.blast_radius("sym:a.py#helper")
        assert not any(imp.symbol.symbol_id == "sym:ghost.py#phantom" for imp in out.impacted)


class TestReadRepair:
    @pytest.mark.asyncio
    async def test_read_repair_on_edit(self, built_repo):
        """Editing a hit file is detected and repaired on the next lookup.

        NOTE (deviation, documented in the Completion Note): the task's
        illustrative Test Specification queries the brand-new symbol
        name (``"helper_two"``) directly after the edit and expects
        ``repaired_files == ["a.py"]`` on that same call. That can never
        happen: ``_ensure_fresh`` only hashes *hit* files (Key
        Constraints — "never the repo"), and a name introduced by the
        very edit that made the file stale cannot be a pre-repair hit
        (exact-match and FTS both search the still-stale index). This
        version repairs via a query for the symbol that was ALREADY
        indexed ("helper", still present after the edit), then shows
        the new symbol is queryable on the very next call.
        """
        svc, root = built_repo
        out = await svc.lookup("helper")
        assert out.hits and not out.repaired_files

        (root / "a.py").write_text((root / "a.py").read_text() + "\ndef helper_two(): ...\n")
        out_repair = await svc.lookup("helper")
        assert out_repair.repaired_files == ["a.py"]

        out2 = await svc.lookup("helper_two")
        assert not out2.repaired_files
        assert out2.hits[0].qualname == "helper_two"

    @pytest.mark.asyncio
    async def test_lock_busy_serves_stale(self, built_repo):
        svc, root = built_repo
        (root / "a.py").write_text("def changed(): ...\n")
        with wiki_write_lock(svc._config.storage_path(root), timeout=0) as ok:
            assert ok
            out = await svc.lookup("helper")
        assert out.repaired_files == []
        assert all(hit.stale for hit in out.hits)

    @pytest.mark.asyncio
    async def test_deleted_file_removes_pages(self, built_repo):
        svc, root = built_repo
        out = await svc.lookup("helper")
        assert out.hits

        (root / "a.py").unlink()
        out2 = await svc.lookup("helper")
        assert out2.repaired_files == ["a.py"]
        assert not any(hit.rel_path == "a.py" for hit in out2.hits)
        page = await svc._store.get_page("file:a.py", include_body=False)
        assert page is None
