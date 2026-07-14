"""Tests for the deterministic repository scanner (repo_scan).

All offline: temp directories, no git required (``use_git=False``),
no LLM. Pins discovery filtering, per-file extraction (Python AST
outline, markdown summary), directory overview pages, and import-edge
derivation including src-layout resolution.
"""

from pathlib import Path

from parrot.knowledge.wiki.repo_scan import (
    DEFAULT_MAX_FILE_BYTES,
    build_dir_pages,
    build_file_slice,
    dir_concept_id,
    discover_repo_files,
    file_concept_id,
    scan_repository,
)


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


PY_A = '"""Mod A does things."""\nfrom pkg.b import x\n\n\nclass Alpha:\n    """Alpha class."""\n\n    def run(self, arg):\n        """Run it."""\n        return arg\n\n\ndef helper():\n    """Top-level helper."""\n'
PY_B = '"""Mod B."""\nx = 1\n'


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
        found = discover_repo_files(
            tmp_path, exclude_dirs=["vendor"], use_git=False
        )
        assert found == ["app.py"]

    def test_deterministic_sorted(self, tmp_path: Path):
        _write(tmp_path, "b.py", "x=1")
        _write(tmp_path, "a.py", "x=1")
        assert discover_repo_files(tmp_path, use_git=False) == [
            "a.py", "b.py",
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
        assert (
            dir_concept_id("pkg"), file_concept_id("pkg/a.py"), "contains"
        ) in scan.dir_edges
        assert (
            dir_concept_id(""), dir_concept_id("pkg"), "contains"
        ) in scan.dir_edges

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
        scan = scan_repository(
            tmp_path, use_git=False, rel_paths=["pkg/a.py"]
        )
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
