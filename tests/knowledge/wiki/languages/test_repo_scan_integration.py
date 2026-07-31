"""Integration tests for the registry-driven repo_scan.py (FEAT-394).

Covers the behavior added by TASK-2012: the ``FileSlice.language`` field,
registry-driven ``build_file_slice()``, per-language ``build_import_edges()``
grouping/isolation, the generalized incremental fast-path, the new
``.php``/``.html``/``.htm`` suffix coverage, and defensive degrade-on-
parse-failure behavior.
"""

from pathlib import Path
from typing import Any, ClassVar

import pytest
from parrot.knowledge.wiki import languages as languages_module
from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner
from parrot.knowledge.wiki.repo_scan import (
    CODE_SUFFIXES,
    DEFAULT_SUFFIXES,
    DOC_SUFFIXES,
    build_file_slice,
    build_import_edges,
    file_concept_id,
    scan_repository,
)


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class _FakeSpanishScanner(LanguageScanner):
    """A second, deliberately foreign-looking scanner used only to prove
    that :func:`build_import_edges` keeps each language's reference index
    isolated — without waiting on the real PHP/JS/Rust plugins (TASK-2013
    to TASK-2015), which land in later tasks of this feature.
    """

    name: ClassVar[str] = "fake"
    suffixes: ClassVar[frozenset[str]] = frozenset({".fake"})

    def outline(self, source: str, rel_path: str) -> LanguageOutline:
        imports = [line.strip() for line in source.splitlines() if line.strip()]
        return LanguageOutline(summary="fake file", outline=[], imports=imports)

    def build_reference_index(self, rel_paths) -> Any:
        return {p for p in rel_paths if p.endswith(".fake")}

    def resolve_import(self, spec: str, from_file: str, index: Any) -> str | None:
        return spec if spec in index else None

    @property
    def mode(self) -> str:
        return "heuristic"


@pytest.fixture
def with_fake_scanner():
    """Temporarily register a second scanner in the real module registry."""
    scanner = _FakeSpanishScanner()
    languages_module._SCANNERS["fake"] = scanner
    languages_module._SUFFIX_INDEX[".fake"] = "fake"
    try:
        yield scanner
    finally:
        languages_module._SCANNERS.pop("fake", None)
        languages_module._SUFFIX_INDEX.pop(".fake", None)


class TestSuffixSets:
    def test_php_is_code_suffix(self):
        assert ".php" in CODE_SUFFIXES

    def test_html_and_htm_are_doc_suffixes(self):
        assert ".html" in DOC_SUFFIXES
        assert ".htm" in DOC_SUFFIXES


class TestFileSliceLanguageField:
    def test_python_file_gets_language_python(self, tmp_path: Path):
        _write(tmp_path, "mod.py", '"""Doc."""\n')
        fs = build_file_slice(tmp_path, "mod.py")
        assert fs is not None
        assert fs.language == "python"

    def test_html_file_has_no_language(self, tmp_path: Path):
        _write(tmp_path, "index.html", "<html><body>hi</body></html>")
        fs = build_file_slice(tmp_path, "index.html")
        assert fs is not None
        assert fs.language is None


class TestHtmlShallowScan:
    def test_html_title_summary(self, tmp_path: Path):
        _write(
            tmp_path, "page.html",
            "<html><head><title>My Page Title</title></head><body></body></html>",
        )
        fs = build_file_slice(tmp_path, "page.html")
        assert fs is not None
        assert fs.record.summary == "My Page Title"
        assert "## API outline" not in fs.record.body

    def test_html_falls_back_to_heading(self, tmp_path: Path):
        _write(tmp_path, "page.html", "<html><body><h1>Heading Text</h1></body></html>")
        fs = build_file_slice(tmp_path, "page.html")
        assert fs is not None
        assert fs.record.summary == "Heading Text"

    def test_html_no_outline_no_edges(self, tmp_path: Path):
        _write(tmp_path, "page.html", "<html><body>plain</body></html>")
        fs = build_file_slice(tmp_path, "page.html")
        assert fs is not None
        assert fs.imports == []
        assert fs.language is None


class TestParseFailureDegradesShallow:
    def test_python_syntax_error_degrades_shallow(self, tmp_path: Path):
        _write(tmp_path, "broken.py", "def broken(:\n")
        fs = build_file_slice(tmp_path, "broken.py")
        assert fs is not None
        assert fs.record.summary  # falls back to first-line-of-content
        assert "## API outline" not in fs.record.body

    def test_scanner_exception_degrades_shallow(self, tmp_path: Path, monkeypatch):
        class _Boom(LanguageScanner):
            name: ClassVar[str] = "boom"
            suffixes: ClassVar[frozenset[str]] = frozenset({".boom"})

            def outline(self, source: str, rel_path: str) -> LanguageOutline:
                raise RuntimeError("kaboom")

            def build_reference_index(self, rel_paths) -> Any:
                return {}

            def resolve_import(self, spec, from_file, index) -> str | None:
                return None

            @property
            def mode(self) -> str:
                return "heuristic"

        scanner = _Boom()
        monkeypatch.setitem(languages_module._SCANNERS, "boom", scanner)
        monkeypatch.setitem(languages_module._SUFFIX_INDEX, ".boom", "boom")

        _write(tmp_path, "x.boom", "hello world\n")
        fs = build_file_slice(tmp_path, "x.boom")
        assert fs is not None
        assert fs.language is None
        assert fs.record.summary == "hello world"


class TestMixedLanguageIndexesIsolated:
    def test_fake_import_never_resolves_across_languages(
        self, tmp_path: Path, with_fake_scanner
    ):
        _write(tmp_path, "a.fake", "b.fake\nmod\n")
        _write(tmp_path, "b.fake", "")
        _write(tmp_path, "mod.py", '"""Mod."""\n')

        fs_a = build_file_slice(tmp_path, "a.fake")
        fs_b = build_file_slice(tmp_path, "b.fake")
        fs_py = build_file_slice(tmp_path, "mod.py")
        assert fs_a and fs_b and fs_py

        edges = build_import_edges(
            [fs_a, fs_b, fs_py],
            index_paths=["a.fake", "b.fake", "mod.py"],
        )
        # a.fake -> b.fake resolves (both in the fake index).
        assert (
            file_concept_id("a.fake"), file_concept_id("b.fake"), "references"
        ) in edges
        # The bare "mod" specifier is fake-language syntax, not Python —
        # it must never cross into mod.py's file page.
        assert (
            file_concept_id("a.fake"), file_concept_id("mod.py"), "references"
        ) not in edges


class TestIncrementalFastpathGeneralized:
    def test_changed_registered_suffix_triggers_full_discovery(self, tmp_path: Path):
        _write(tmp_path, "a.py", '"""A."""\nfrom pkg.b import x\n')
        _write(tmp_path, "pkg/b.py", '"""B."""\n')
        scan = scan_repository(tmp_path, rel_paths=["a.py"], use_git=False)
        # Full discovery ran, so pkg/b.py is resolvable as an edge target
        # even though only a.py was passed as the changed file.
        edges = scan.import_edges
        assert (
            file_concept_id("a.py"), file_concept_id("pkg/b.py"), "references"
        ) in edges

    def test_docs_only_change_skips_full_discovery(self, tmp_path: Path):
        _write(tmp_path, "README.md", "# Title\n")
        _write(tmp_path, "other.py", '"""Other."""\n')
        scan = scan_repository(tmp_path, rel_paths=["README.md"], use_git=False)
        # Only the explicitly-passed doc file was scanned — other.py was
        # never discovered because no changed file needed repo-wide
        # discovery to resolve import targets.
        assert [fs.rel_path for fs in scan.files] == ["README.md"]


class TestSvelteSuffixClaimed:
    """FEAT-396 / TASK-2020 — `.svelte` enters the scanned suffix set."""

    def test_code_suffixes_contains_svelte(self):
        """`.svelte` is a code suffix and flows into the default set.

        ``DEFAULT_SUFFIXES`` is a union, so it picks the entry up with no
        second edit.
        """
        assert ".svelte" in CODE_SUFFIXES
        assert ".svelte" in DEFAULT_SUFFIXES
        assert ".svelte" not in DOC_SUFFIXES

    def test_svelte_file_is_scanned_and_imports_resolve(self, tmp_path: Path):
        """The value this task delivers: components are no longer invisible.

        The outline is still degraded until TASK-2021 — deliberately not
        asserted here. Imports already work on raw Svelte source, and
        TASK-2021's contract requires they keep working unchanged, so this
        doubles as that task's regression guard.
        """
        _write(tmp_path, "src/lib/util.ts", "export function helper() {}\n")
        _write(
            tmp_path,
            "src/lib/Widget.svelte",
            '<script lang="ts">\n'
            "  import { helper } from './util'\n"
            "</script>\n"
            "<div>hi</div>\n",
        )
        scan = scan_repository(tmp_path, use_git=False)

        scanned = {fs.rel_path for fs in scan.files}
        assert "src/lib/Widget.svelte" in scanned

        assert (
            file_concept_id("src/lib/Widget.svelte"),
            file_concept_id("src/lib/util.ts"),
            "references",
        ) in scan.import_edges
