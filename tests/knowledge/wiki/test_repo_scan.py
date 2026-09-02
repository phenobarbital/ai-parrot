"""Tests for the deterministic repository scanner (repo_scan).

All offline: temp directories, no git required (``use_git=False``),
no LLM. Pins discovery filtering, per-file extraction (Python AST
outline, markdown summary), directory overview pages, and import-edge
derivation including src-layout resolution.
"""

import hashlib
from pathlib import Path

from parrot.knowledge.wiki.repo_scan import (
    DEFAULT_MAX_FILE_BYTES,
    WIKI_BUNDLE_MARKER,
    build_dir_pages,
    build_file_slice,
    build_symbol_pages,
    dir_concept_id,
    discover_repo_files,
    file_concept_id,
    find_wiki_bundle_dirs,
    is_inside_wiki_bundle,
    scan_repository,
)
from parrot.knowledge.wiki.sources import SourceCollectionManager


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


PY_A = '"""Mod A does things."""\nfrom pkg.b import x\n\n\nclass Alpha:\n    """Alpha class."""\n\n    def run(self, arg):\n        """Run it."""\n        return arg\n\n\ndef helper():\n    """Top-level helper."""\n'
PY_B = '"""Mod B."""\nx = 1\n'


class TestFrontmatterSummary:
    """A YAML frontmatter block is metadata, not the document's lead.

    Taking the first non-empty line of such a file yields the ``---``
    delimiter, which is both useless in search results and indexed by
    FTS as if it were content.
    """

    def _summary(self, tmp_path: Path, body: str) -> str:
        _write(tmp_path, "doc.md", body)
        slice_ = build_file_slice(tmp_path, "doc.md")
        assert slice_ is not None
        return slice_.record.summary

    def test_prefers_the_frontmatter_summary_field(self, tmp_path: Path):
        got = self._summary(
            tmp_path,
            "---\ntitle: query()\nsummary: Scoped question against the KB.\n" "---\n\n# query\n\nBody text.\n",
        )
        assert got == "Scoped question against the KB."

    def test_falls_back_to_the_frontmatter_title(self, tmp_path: Path):
        got = self._summary(tmp_path, "---\ntype: Concept\ntitle: query()\n---\n\n# query\n")
        assert got == "query()"

    def test_falls_back_to_the_first_heading_after_the_block(self, tmp_path: Path):
        got = self._summary(tmp_path, "---\ntype: Concept\ntags:\n- a\n---\n\n# Real Heading\n\nText.\n")
        assert got == "Real Heading"

    def test_strips_quotes_from_frontmatter_values(self, tmp_path: Path):
        got = self._summary(tmp_path, '---\nsummary: "Quoted lead."\n---\n\n# H\n')
        assert got == "Quoted lead."

    def test_ignores_an_empty_frontmatter_summary(self, tmp_path: Path):
        got = self._summary(tmp_path, "---\nsummary:\ntitle: The Title\n---\n\n# H\n")
        assert got == "The Title"

    def test_ignores_a_block_scalar_summary(self, tmp_path: Path):
        # `summary: |` introduces a folded block; the indicator itself
        # is not a summary.
        got = self._summary(tmp_path, "---\nsummary: |\ntitle: The Title\n---\n\n# H\n")
        assert got == "The Title"

    def test_never_returns_the_delimiter(self, tmp_path: Path):
        got = self._summary(tmp_path, "---\ntype: Concept\n---\n\nPlain lead line.\n")
        assert got == "Plain lead line."

    def test_unterminated_frontmatter_does_not_swallow_the_document(self, tmp_path: Path):
        got = self._summary(tmp_path, "---\nnot really frontmatter\n\n# Heading\n")
        assert got
        assert got != "---"

    def test_a_document_without_frontmatter_is_unchanged(self, tmp_path: Path):
        got = self._summary(tmp_path, "# Project Title\n\nSome text.\n")
        assert got == "Project Title"

    def test_a_leading_horizontal_rule_is_not_frontmatter(self, tmp_path: Path):
        # Position alone does not make a block frontmatter: without any
        # `key:` line this is a rule, and swallowing it would silently
        # discard the document's real lead.
        got = self._summary(tmp_path, "---\nIntro line.\n---\n\nAfter the rule.\n")
        assert got == "Intro line."

    def test_a_horizontal_rule_mid_document_is_not_frontmatter(self, tmp_path: Path):
        got = self._summary(tmp_path, "# Heading\n\n---\n\nAfter the rule.\n")
        assert got == "Heading"


class TestWikiBundleGuardrail:
    """A wiki must never ingest another wiki's exported bundle."""

    def test_finds_a_nested_bundle_by_its_marker(self, tmp_path: Path):
        _write(tmp_path, f"docs/parrot/{WIKI_BUNDLE_MARKER}", "{}")
        _write(tmp_path, "docs/parrot/index.md", "# Wiki")
        assert find_wiki_bundle_dirs(tmp_path) == ["docs/parrot"]

    def test_reports_no_bundle_for_an_ordinary_tree(self, tmp_path: Path):
        _write(tmp_path, "docs/guide.md", "# Guide")
        assert find_wiki_bundle_dirs(tmp_path) == []

    def test_discovery_skips_everything_inside_a_bundle(self, tmp_path: Path):
        _write(tmp_path, "app.py", "x = 1")
        _write(tmp_path, "docs/guide.md", "# A real doc")
        _write(tmp_path, f"docs/parrot/{WIKI_BUNDLE_MARKER}", "{}")
        _write(tmp_path, "docs/parrot/index.md", "# Wiki")
        _write(
            tmp_path,
            "docs/parrot/overviews/doc:app-py.md",
            "---\ntitle: app.py\n---\n\n# app.py\n",
        )

        found = discover_repo_files(tmp_path, use_git=False)

        assert "app.py" in found
        assert "docs/guide.md" in found
        assert all(not f.startswith("docs/parrot/") for f in found)

    def test_detects_a_path_inside_a_bundle_without_walking_the_repo(self, tmp_path: Path):
        # The incremental path must answer "is this one file inside a
        # bundle?" by looking at its ancestors, not by scanning the tree:
        # the git post-commit hook pays this cost on every commit.
        _write(tmp_path, f"docs/parrot/{WIKI_BUNDLE_MARKER}", "{}")
        _write(tmp_path, "docs/parrot/overviews/doc:app-py.md", "# app")
        _write(tmp_path, "docs/guide.md", "# Guide")

        assert is_inside_wiki_bundle(tmp_path, "docs/parrot/overviews/doc:app-py.md")
        assert is_inside_wiki_bundle(tmp_path, "docs/parrot/index.md")
        assert not is_inside_wiki_bundle(tmp_path, "docs/guide.md")
        assert not is_inside_wiki_bundle(tmp_path, "app.py")

    def test_inside_check_ignores_a_marker_at_the_repo_root(self, tmp_path: Path):
        _write(tmp_path, WIKI_BUNDLE_MARKER, "{}")
        _write(tmp_path, "app.py", "x = 1")
        assert not is_inside_wiki_bundle(tmp_path, "app.py")

    def test_walk_does_not_descend_into_path_prefix_excludes(self, tmp_path: Path):
        _write(tmp_path, f"vendor/stuff/{WIKI_BUNDLE_MARKER}", "{}")
        _write(tmp_path, f"docs/parrot/{WIKI_BUNDLE_MARKER}", "{}")

        found = find_wiki_bundle_dirs(tmp_path, exclude_dirs=["vendor/stuff"])

        assert found == ["docs/parrot"]

    def test_a_bundle_at_the_repo_root_does_not_prune_the_repo(self, tmp_path: Path):
        # The scanned repo may itself be a wiki bundle root; excluding "."
        # would silently discover nothing at all.
        _write(tmp_path, WIKI_BUNDLE_MARKER, "{}")
        _write(tmp_path, "app.py", "x = 1")

        found = discover_repo_files(tmp_path, use_git=False)

        assert "app.py" in found


class TestDiscovery:
    def test_filters_suffixes_and_dirs(self, tmp_path: Path):
        _write(tmp_path, "pkg/a.py", PY_A)
        _write(tmp_path, "README.md", "# Hello\n\nWorld.")
        _write(tmp_path, "node_modules/x.js", "var x;")
        _write(tmp_path, ".parrot/wiki.json", "{}")
        _write(tmp_path, "image.png", "not really a png")
        _write(tmp_path, "uv.lock", "lockfile")

        found = discover_repo_files(tmp_path, use_git=False)
        assert "pkg/a.py" in found
        assert "README.md" in found
        assert all("node_modules" not in f for f in found)
        assert all(".parrot" not in f for f in found)
        assert "image.png" not in found
        assert "uv.lock" not in found

    def test_extra_exclude_dirs(self, tmp_path: Path):
        _write(tmp_path, "vendor/lib.py", "x = 1")
        _write(tmp_path, "app.py", "y = 2")
        found = discover_repo_files(tmp_path, exclude_dirs=["vendor"], use_git=False)
        assert found == ["app.py"]

    def test_deterministic_sorted(self, tmp_path: Path):
        _write(tmp_path, "b.py", "x=1")
        _write(tmp_path, "a.py", "x=1")
        assert discover_repo_files(tmp_path, use_git=False) == [
            "a.py",
            "b.py",
        ]


class TestFileSlice:
    def test_python_outline_and_summary(self, tmp_path: Path):
        _write(tmp_path, "pkg/a.py", PY_A)
        fs = build_file_slice(tmp_path, "pkg/a.py")
        assert fs is not None
        rec = fs.record
        assert rec.concept_id == "file:pkg/a.py"
        assert rec.category == "module"
        assert rec.summary == "Mod A does things."
        assert "class Alpha: Alpha class." in rec.body
        assert "def run(self, arg): Run it." in rec.body
        assert "def helper(): Top-level helper." in rec.body
        assert fs.imports == ["pkg.b"]
        assert rec.token_count > 0

    def test_markdown_summary(self, tmp_path: Path):
        _write(tmp_path, "README.md", "# Project Title\n\nBody text.")
        fs = build_file_slice(tmp_path, "README.md")
        assert fs is not None
        assert fs.record.category == "document"
        assert fs.record.summary == "Project Title"

    def test_config_category(self, tmp_path: Path):
        _write(tmp_path, "settings.toml", "[tool]\nname = 'x'")
        fs = build_file_slice(tmp_path, "settings.toml")
        assert fs is not None
        assert fs.record.category == "config"

    def test_syntax_error_degrades_gracefully(self, tmp_path: Path):
        _write(tmp_path, "bad.py", "def broken(:\n")
        fs = build_file_slice(tmp_path, "bad.py")
        assert fs is not None
        assert fs.record.summary  # falls back, never empty
        assert fs.imports == []

    def test_binary_and_oversized_skipped(self, tmp_path: Path):
        (tmp_path / "bin.py").write_bytes(b"\x00\x01\x02")
        assert build_file_slice(tmp_path, "bin.py") is None
        _write(tmp_path, "big.py", "x = 1\n" * 10)
        assert build_file_slice(tmp_path, "big.py", max_file_bytes=10) is None
        assert DEFAULT_MAX_FILE_BYTES > 10

    def test_body_truncation(self, tmp_path: Path):
        _write(tmp_path, "long.md", "word " * 5000)
        fs = build_file_slice(tmp_path, "long.md", body_max_chars=100)
        assert fs is not None
        assert "(truncated)" in fs.record.body


class TestDirPagesAndEdges:
    def test_dir_pages_and_contains_edges(self, tmp_path: Path):
        _write(tmp_path, "pkg/a.py", PY_A)
        _write(tmp_path, "pkg/b.py", PY_B)
        _write(tmp_path, "README.md", "# T")
        scan = scan_repository(tmp_path, use_git=False)

        dir_ids = {r.concept_id for r in scan.dir_records}
        assert dir_concept_id("pkg") in dir_ids
        assert dir_concept_id("") in dir_ids  # repo root
        assert (dir_concept_id("pkg"), file_concept_id("pkg/a.py"), "contains") in scan.dir_edges
        assert (dir_concept_id(""), dir_concept_id("pkg"), "contains") in scan.dir_edges

    def test_dir_body_lists_children(self, tmp_path: Path):
        _write(tmp_path, "pkg/a.py", PY_A)
        files = [build_file_slice(tmp_path, "pkg/a.py")]
        records, _ = build_dir_pages([f for f in files if f])
        pkg = next(r for r in records if r.concept_id == "dir:pkg")
        assert "file:pkg/a.py" in pkg.body
        assert pkg.category == "overview"


class TestImportEdges:
    def test_flat_layout(self, tmp_path: Path):
        _write(tmp_path, "pkg/a.py", PY_A)
        _write(tmp_path, "pkg/b.py", PY_B)
        scan = scan_repository(tmp_path, use_git=False)
        assert (
            file_concept_id("pkg/a.py"),
            file_concept_id("pkg/b.py"),
            "references",
        ) in scan.import_edges

    def test_src_layout_resolution(self, tmp_path: Path):
        _write(
            tmp_path,
            "packages/lib/src/mypkg/mod.py",
            '"""Target."""\nX = 1\n',
        )
        _write(tmp_path, "app.py", "from mypkg.mod import X\n")
        scan = scan_repository(tmp_path, use_git=False)
        assert (
            file_concept_id("app.py"),
            file_concept_id("packages/lib/src/mypkg/mod.py"),
            "references",
        ) in scan.import_edges

    def test_package_prefix_fallback(self, tmp_path: Path):
        _write(tmp_path, "pkg/__init__.py", '"""Pkg."""\n')
        _write(tmp_path, "app.py", "import pkg.missing.deep\n")
        scan = scan_repository(tmp_path, use_git=False)
        # pkg.missing.deep has no file; falls back to the pkg package.
        assert (
            file_concept_id("app.py"),
            file_concept_id("pkg/__init__.py"),
            "references",
        ) in scan.import_edges

    def test_partial_scan_resolves_against_full_index(self, tmp_path: Path):
        _write(tmp_path, "pkg/a.py", PY_A)
        _write(tmp_path, "pkg/b.py", PY_B)
        scan = scan_repository(tmp_path, use_git=False, rel_paths=["pkg/a.py"])
        assert [fs.rel_path for fs in scan.files] == ["pkg/a.py"]
        # b.py was not scanned, but the import edge still resolves.
        assert (
            file_concept_id("pkg/a.py"),
            file_concept_id("pkg/b.py"),
            "references",
        ) in scan.import_edges

    def test_no_self_edges(self, tmp_path: Path):
        _write(tmp_path, "pkg/__init__.py", "import pkg\n")
        scan = scan_repository(tmp_path, use_git=False)
        assert all(src != dst for src, dst, _ in scan.import_edges)


class TestIncrementalScanCost:
    """Partial scans avoid the whole-repo discovery when they can."""

    def test_docs_only_upsert_skips_full_discovery(self, tmp_path: Path, monkeypatch):
        # A docs/config-only incremental commit cannot produce import
        # edges, so the O(repo) discovery scan must be skipped entirely
        # (the git post-commit hook runs on every commit).
        _write(tmp_path, "pkg/a.py", PY_A)
        _write(tmp_path, "README.md", "# Title\n\nText.\n")

        import parrot.knowledge.wiki.repo_scan as rs

        called = False
        real_discover = rs.discover_repo_files

        def _spy(*args, **kwargs):
            nonlocal called
            called = True
            return real_discover(*args, **kwargs)

        monkeypatch.setattr(rs, "discover_repo_files", _spy)
        scan = scan_repository(tmp_path, use_git=False, rel_paths=["README.md"])
        assert called is False
        assert [fs.rel_path for fs in scan.files] == ["README.md"]
        assert scan.import_edges == []

    def test_python_upsert_still_runs_full_discovery(self, tmp_path: Path, monkeypatch):
        _write(tmp_path, "pkg/a.py", PY_A)
        _write(tmp_path, "pkg/b.py", PY_B)

        import parrot.knowledge.wiki.repo_scan as rs

        called = False
        real_discover = rs.discover_repo_files

        def _spy(*args, **kwargs):
            nonlocal called
            called = True
            return real_discover(*args, **kwargs)

        monkeypatch.setattr(rs, "discover_repo_files", _spy)
        scan = scan_repository(tmp_path, use_git=False, rel_paths=["pkg/a.py"])
        assert called is True
        # Edge to the unscanned b.py still resolves via the full index.
        assert (
            file_concept_id("pkg/a.py"),
            file_concept_id("pkg/b.py"),
            "references",
        ) in scan.import_edges


class TestSymbolPlaneContentHash:
    """FEAT-498 — content_hash equals SourceCollectionManager's file hash."""

    def test_build_file_slice_sets_content_hash(self, tmp_path: Path):
        path = _write(tmp_path, "a.py", PY_A)
        fs = build_file_slice(tmp_path, "a.py")
        assert fs is not None
        assert fs.record.content_hash == hashlib.sha1(path.read_bytes()).hexdigest()

    def test_content_hash_matches_source_collection_manager(self, tmp_path: Path):
        path = _write(tmp_path, "a.py", PY_A)
        fs = build_file_slice(tmp_path, "a.py")
        mgr = SourceCollectionManager.__new__(SourceCollectionManager)
        assert fs.record.content_hash == mgr._compute_hash(path)


class TestSymbolPagesAndEdges:
    """FEAT-498 — sym: pages, defines/contains edges, depth, ordinals."""

    def test_symbol_pages_and_defines_contains_edges(self, tmp_path: Path):
        _write(tmp_path, "a.py", PY_A)
        fs = build_file_slice(tmp_path, "a.py")
        assert fs is not None
        records, edges = build_symbol_pages(tmp_path, fs)
        titles = {r.title for r in records}
        assert {"Alpha", "Alpha.run", "helper"} <= titles
        for record in records:
            assert record.category == "symbol"
            assert record.node_id == "a.py"
        defines = {(s, d) for s, d, rel, _p in edges if rel == "defines"}
        assert (file_concept_id("a.py"), "sym:a.py#Alpha") in defines
        assert (file_concept_id("a.py"), "sym:a.py#helper") in defines
        contains = {(s, d) for s, d, rel, _p in edges if rel == "contains"}
        assert ("sym:a.py#Alpha", "sym:a.py#Alpha.run") in contains

    def test_symbol_depth_1_drops_methods(self, tmp_path: Path):
        _write(tmp_path, "a.py", PY_A)
        fs = build_file_slice(tmp_path, "a.py", symbol_depth=1)
        assert fs is not None
        assert {s.qualname for s in fs.symbols} == {"Alpha", "helper"}
        records, _edges = build_symbol_pages(tmp_path, fs)
        assert {r.title for r in records} == {"Alpha", "helper"}

    def test_duplicate_qualname_ordinals_stable(self, tmp_path: Path):
        # Two top-level defs sharing a name (valid Python — the second
        # simply shadows the first at runtime) are two distinct
        # ClassDef nodes with the identical qualname "Parser".
        src = "class Parser:\n    pass\n\n\nclass Parser:\n    pass\n"
        _write(tmp_path, "dup.py", src)
        fs = build_file_slice(tmp_path, "dup.py", symbol_depth=6)
        assert fs is not None
        records, _edges = build_symbol_pages(tmp_path, fs)
        ids = sorted(r.concept_id for r in records if r.title == "Parser")
        assert ids == ["sym:dup.py#Parser", "sym:dup.py#Parser~2"]
        # Re-scanning the unchanged file yields the same ids.
        fs2 = build_file_slice(tmp_path, "dup.py", symbol_depth=6)
        assert fs2 is not None
        records2, _edges2 = build_symbol_pages(tmp_path, fs2)
        ids2 = sorted(r.concept_id for r in records2 if r.title == "Parser")
        assert ids2 == ids

    def test_no_symbols_yields_empty(self, tmp_path: Path):
        _write(tmp_path, "empty.py", "")
        fs = build_file_slice(tmp_path, "empty.py")
        assert fs is not None
        records, edges = build_symbol_pages(tmp_path, fs)
        assert records == []
        assert edges == []


class TestScanRepositorySymbolPlane:
    """FEAT-498 — RepoScan.symbol_records / symbol_edges end to end."""

    def test_scan_repository_populates_symbol_plane(self, tmp_path: Path):
        _write(tmp_path, "a.py", "def helper():\n    return 1\n")
        _write(
            tmp_path,
            "b.py",
            "from a import helper\n\n\ndef run():\n    return helper()\n",
        )
        scan = scan_repository(tmp_path, use_git=False)
        titles = {r.title for r in scan.symbol_records}
        assert titles == {"helper", "run"}
        calls = {(s, d) for s, d, rel, prov in scan.symbol_edges if rel == "calls" and prov == "extracted"}
        assert ("sym:b.py#run", "sym:a.py#helper") in calls
