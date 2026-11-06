"""Tests for the static techwiki API reference generator."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from parrot.sdd.scripts.techwiki_api import main
from parrot.sdd.techwiki.api import GriffeUnavailable, RenderedPage, _unlink_pageless_refs, generate
from parrot.sdd.techwiki.config import TechwikiConfig, TechwikiPackage

REPO_ROOT = Path(__file__).resolve().parents[4]
GOLDEN_DIR = Path(__file__).parent / "fixtures" / "techwiki_golden"


def _require_griffe() -> None:
    """Skip static-rendering tests only when the declared optional extra is absent.

    CI sets ``TECHWIKI_REQUIRE_GRIFFE=1`` so a missing extra fails the run instead of silently skipping it.
    """
    if importlib.util.find_spec("griffe") is None:
        if os.environ.get("TECHWIKI_REQUIRE_GRIFFE") == "1":
            pytest.fail("TECHWIKI_REQUIRE_GRIFFE=1 but the griffe extra is not installed")
        pytest.skip("griffe extra is not installed")


@pytest.fixture
def bad_repo(tmp_path: Path) -> Path:
    """A repository whose package contains one module with a syntax error (griffe drops it silently)."""
    package = tmp_path / "src" / "badpkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""Bad package."""\n', encoding="utf-8")
    (package / "good.py").write_text('def ok() -> None:\n    """Fine."""\n', encoding="utf-8")
    (package / "broken.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
    (tmp_path / "sdd").mkdir()
    (tmp_path / "sdd" / "config.json").write_text(
        json.dumps({"techwiki": {"packages": [{"dist": "bad", "src": "src", "roots": ["badpkg"]}]}}), encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def techwiki_repo(tmp_path: Path) -> tuple[Path, TechwikiConfig]:
    """Build a minimal repository containing the static sample package."""
    fixture = Path(__file__).parent / "fixtures" / "techwiki_pkg"
    destination = tmp_path / "packages" / "sample" / "src"
    destination.mkdir(parents=True)
    for source in fixture.rglob("*.py"):
        target = destination / source.relative_to(fixture)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path, TechwikiConfig(
        packages=[TechwikiPackage(dist="sample", src="packages/sample/src", roots=["samplepkg"])]
    )


class TestGenerate:
    """Static generator behaviour."""

    def test_generate_static_no_import(self, techwiki_repo: tuple[Path, TechwikiConfig]) -> None:
        """Fixture package renders without import side effects."""
        _require_griffe()
        root, cfg = techwiki_repo
        before = set(sys.modules)
        pages, skipped = generate(cfg, root)
        assert not skipped
        assert pages
        assert not ({name for name in sys.modules if name.startswith("samplepkg")} - before)

    def test_generate_is_deterministic(self, techwiki_repo: tuple[Path, TechwikiConfig]) -> None:
        """Two runs return byte-identical output."""
        _require_griffe()
        root, cfg = techwiki_repo
        first, _ = generate(cfg, root)
        second, _ = generate(cfg, root)
        assert [(page.module, page.body) for page in first] == [(page.module, page.body) for page in second]

    def test_generate_satellite_coverage(self) -> None:
        """Modules from satellite distributions merge into the shared ``parrot`` namespace (AC-2)."""
        _require_griffe()
        cfg = TechwikiConfig(
            packages=[
                TechwikiPackage(
                    dist="ai-parrot", src="packages/ai-parrot/src", roots=["parrot.clients", "parrot.stores"]
                ),
                TechwikiPackage(
                    dist="ai-parrot-embeddings", src="packages/ai-parrot-embeddings/src", roots=["parrot.stores"]
                ),
                TechwikiPackage(
                    dist="ai-parrot-client-google", src="packages/ai-parrot-client-google/src", roots=["parrot.clients"]
                ),
            ]
        )
        pages, skipped = generate(cfg, REPO_ROOT)
        modules = {page.module for page in pages}
        assert not skipped
        # one core module and one satellite module of each shared sub namespace
        assert {"parrot.clients.base", "parrot.clients.google"} <= modules
        assert {"parrot.stores.abstract", "parrot.stores.faiss_store"} <= modules

    def test_page_title_is_the_module_name_and_section_is_configured(
        self, techwiki_repo: tuple[Path, TechwikiConfig]
    ) -> None:
        """The title is the bare module name (no ``Reference:`` prefix) and the section follows the config."""
        _require_griffe()
        root, cfg = techwiki_repo
        cfg = cfg.model_copy(update={"reference_section": "Code Reference"})
        pages, _ = generate(cfg, root)
        core = next(page for page in pages if page.module == "samplepkg.core")
        assert core.title == "samplepkg.core"
        assert core.section == "Code Reference"
        assert core.body.startswith("# samplepkg.core\n")
        assert ":" not in core.title

    def test_generate_reports_syntax_error_modules(self, bad_repo: Path) -> None:
        """A module griffe cannot parse is listed as skipped instead of silently disappearing."""
        _require_griffe()
        cfg = TechwikiConfig(packages=[TechwikiPackage(dist="bad", src="src", roots=["badpkg"])])
        pages, skipped = generate(cfg, bad_repo)
        assert [item["module"] for item in skipped] == ["badpkg.broken"]
        assert skipped[0]["reason"].startswith("SyntaxError")
        assert "badpkg.good" in {page.module for page in pages}


class TestCli:
    """CLI dependency and strict exit paths."""

    def test_griffe_unavailable_exit_3(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Unavailable griffe returns the documented dependency exit code."""

        def unavailable(*args: object, **kwargs: object) -> tuple[list[object], list[dict[str, str]]]:
            raise GriffeUnavailable("griffe is not installed. Install with: pip install ai-parrot[techwiki]")

        monkeypatch.setattr("parrot.sdd.techwiki.api.generate", unavailable)
        assert main(["--out", str(tmp_path), "--root", str(tmp_path)]) == 3

    def test_generate_matches_golden(self, techwiki_repo: tuple[Path, TechwikiConfig]) -> None:
        """Every generated page equals its golden file byte for byte, and no golden file is orphaned (S8 / AC-7b).

        Regenerate after an intentional template or renderer change with
        ``TECHWIKI_UPDATE_GOLDEN=1 pytest packages/ai-parrot/tests/sdd/test_techwiki_api.py -k golden`` and review the diff.
        """
        _require_griffe()
        root, cfg = techwiki_repo
        pages, _ = generate(cfg, root)
        if os.environ.get("TECHWIKI_UPDATE_GOLDEN") == "1":
            for stale in GOLDEN_DIR.glob("*.md"):
                stale.unlink()
            for page in pages:
                (GOLDEN_DIR / f"{page.module}.md").write_text(page.body, encoding="utf-8")
        assert {path.name for path in GOLDEN_DIR.glob("*.md")} == {f"{page.module}.md" for page in pages}
        for page in pages:
            assert page.body == (GOLDEN_DIR / f"{page.module}.md").read_text(encoding="utf-8"), page.module

    def test_strict_fails_on_skipped_module(self, bad_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A real fixture module with a syntax error is listed first in the report; ``--strict`` exits 4 (AC-7b)."""
        _require_griffe()
        out = bad_repo / "out"
        assert main(["--out", str(out), "--root", str(bad_repo), "--strict", "--json"]) == 4
        captured = capsys.readouterr()
        report = json.loads(captured.out)
        assert next(iter(report)) == "skipped_modules"
        assert report["skipped_modules"][0]["module"] == "badpkg.broken"
        assert "Skipped badpkg.broken" in captured.err  # always printed on stderr, also in --json mode
        assert main(["--out", str(out), "--root", str(bad_repo)]) == 0  # non strict still succeeds


class TestRenderingRules:
    """Public API filtering and rendering rules (spec §3 M2, S8)."""

    @staticmethod
    def _pages(techwiki_repo: tuple[Path, TechwikiConfig]) -> dict[str, str]:
        _require_griffe()
        root, cfg = techwiki_repo
        pages, _ = generate(cfg, root)
        return {page.module: page.body for page in pages}

    def test_all_honoured_and_private_excluded(self, techwiki_repo: tuple[Path, TechwikiConfig]) -> None:
        """``__all__`` is honoured; underscore members and imported names do not render."""
        core = self._pages(techwiki_repo)["samplepkg.core"]
        assert "_private" not in core
        assert "_helper" not in core
        assert "## Class `PublicModel`" in core and "## Function `format_value`" in core
        assert "BaseModel`" not in core.replace("PublicModel", "")  # the imported base class is not documented here
        assert "overload" not in core.lower().replace("overloads:", "")

    def test_lazy_export_package_renders_an_index_page(self, techwiki_repo: tuple[Path, TechwikiConfig]) -> None:
        """A package whose ``__all__`` resolves lazily still gets a page, listing its exports and submodules.

        ``issue:6b80e9a6474b`` — ``parrot.auth`` declares 47 exports behind ``__getattr__``, so griffe sees
        no public member on the package itself and it used to render nothing, leaving every re-export that
        pointed at it unlinked.
        """
        pages = self._pages(techwiki_repo)
        assert "samplepkg.lazy" in pages
        body = pages["samplepkg.lazy"]
        assert body.startswith("# samplepkg.lazy\n")
        assert "A namespace package whose public names resolve lazily." in body
        assert "- `LazyThing`" in body
        assert "- [`samplepkg.lazy.impl`](ref:samplepkg.lazy.impl)" in body
        assert "_LAZY_ATTRS" not in body  # private members stay private on an index page
        assert "__getattr__" not in body

    def test_package_index_links_only_submodules_that_have_pages(self, tmp_path: Path) -> None:
        """An index page links a child only when that child rendered a page, so no ``ref:`` dangles."""
        _require_griffe()
        package = tmp_path / "src" / "mixedpkg"
        (package / "hidden").mkdir(parents=True)
        (package / "__init__.py").write_text('"""A namespace with one documented child."""\n', encoding="utf-8")
        (package / "shown.py").write_text('def visible() -> None:\n    """Public."""\n', encoding="utf-8")
        (package / "hidden" / "__init__.py").write_text('"""Nothing public."""\n\n_X = 1\n', encoding="utf-8")
        cfg = TechwikiConfig(packages=[TechwikiPackage(dist="mixed", src="src", roots=["mixedpkg"])])
        pages, skipped = generate(cfg, tmp_path)
        assert not skipped
        bodies = {page.module: page.body for page in pages}
        assert set(bodies) == {"mixedpkg", "mixedpkg.shown"}
        assert "- [`mixedpkg.shown`](ref:mixedpkg.shown)" in bodies["mixedpkg"]
        assert "mixedpkg.hidden" not in bodies["mixedpkg"]
        assert "## Exports" not in bodies["mixedpkg"]  # no ``__all__`` declared

    def test_package_with_no_documented_descendant_renders_nothing(self, tmp_path: Path) -> None:
        """A package whose whole subtree is private still produces no page (no empty index pages)."""
        _require_griffe()
        package = tmp_path / "src" / "quietpkg"
        (package / "sub").mkdir(parents=True)
        (package / "__init__.py").write_text('"""Quiet namespace."""\n', encoding="utf-8")
        (package / "sub" / "__init__.py").write_text('"""Also quiet."""\n\n_X = 1\n', encoding="utf-8")
        cfg = TechwikiConfig(packages=[TechwikiPackage(dist="quiet", src="src", roots=["quietpkg"])])
        pages, skipped = generate(cfg, tmp_path)
        assert not skipped
        assert pages == []

    def test_reexport_alias_is_one_line_not_a_duplicate_body(self, techwiki_repo: tuple[Path, TechwikiConfig]) -> None:
        """A re-export renders as a single 'Re-exported from' line linking the source module page."""
        package = self._pages(techwiki_repo)["samplepkg"]
        assert "## Alias `PublicModel`" in package
        assert "Re-exported from [`samplepkg.core.PublicModel`](ref:samplepkg.core)." in package
        assert "A public model used to exercise class rendering." not in package

    def test_overloads_are_collapsed_into_one_entry(self, techwiki_repo: tuple[Path, TechwikiConfig]) -> None:
        """Two ``@overload`` stubs plus the implementation yield one heading listing each signature."""
        core = self._pages(techwiki_repo)["samplepkg.core"]
        assert core.count("`format_value`") == 1
        assert "- `format_value(value: int) -> str`" in core
        assert "- `format_value(value: str) -> str`" in core

    def test_property_renders_under_attributes(self, techwiki_repo: tuple[Path, TechwikiConfig]) -> None:
        """A property is listed under Attributes with its return annotation, not as a method."""
        core = self._pages(techwiki_repo)["samplepkg.core"]
        assert "| `label` | `str` | Return a readable label. |" in core
        assert "Method `PublicModel.label`" not in core

    def test_model_fields_render_under_fields(self, techwiki_repo: tuple[Path, TechwikiConfig]) -> None:
        """Pydantic fields render in a Fields table with annotation, default and Field description."""
        core = self._pages(techwiki_repo)["samplepkg.core"]
        assert "| `name` | `str` |  |  |" in core
        assert "| `count` | `int` | `1` | How many times to repeat the name. |" in core

    def test_nested_class_has_dotted_heading(self, techwiki_repo: tuple[Path, TechwikiConfig]) -> None:
        """A nested class renders below its parent with a dotted full name."""
        core = self._pages(techwiki_repo)["samplepkg.core"]
        assert "### Class `PublicModel.Nested`" in core

    def test_init_is_merged_into_the_class(self, techwiki_repo: tuple[Path, TechwikiConfig]) -> None:
        """``__init__`` parameters appear on the class (with class docstring descriptions); no ``__init__`` entry."""
        core = self._pages(techwiki_repo)["samplepkg.core"]
        assert "__init__" not in core
        assert "| `size` | `int` |  | Edge length in pixels. |" in core
        assert "| `name` | `str \\| None` | `None` | Optional display name. |" in core
        assert "### Method `Widget.resize`" in core


# --- issue:3ecba9ea5ffc — link a re-export only when its target module has a page -------------


def _page(module: str, body: str) -> RenderedPage:
    """Build a minimal RenderedPage for the unlink tests."""
    return RenderedPage(module=module, section="API Reference", title=module, body=body)


def test_alias_link_to_a_module_without_a_page_is_plain_text() -> None:
    """issue:3ecba9ea5ffc — a re-export whose target produced no page is not linked."""
    pages = {"a.b": _page("a.b", "Re-exported from [`a.missing.Thing`](ref:a.missing).\n")}
    _unlink_pageless_refs(pages)
    # Byte-identical to module.md.j2's own else-branch, the form used when target_module is falsy.
    assert pages["a.b"].body == "Re-exported from `a.missing.Thing`.\n"
    assert "](ref:" not in pages["a.b"].body


def test_alias_link_to_a_paged_module_is_still_linked() -> None:
    """The downgrade is not indiscriminate: a target that DID produce a page keeps its link."""
    body = "Re-exported from [`a.target.Thing`](ref:a.target).\n"
    pages = {"a.b": _page("a.b", body), "a.target": _page("a.target", "# a.target\n")}
    _unlink_pageless_refs(pages)
    assert pages["a.b"].body == body


def test_unlink_leaves_images_and_ordinary_links_alone() -> None:
    """The regex is anchored on the backticked alias form, so other Markdown is untouched."""
    body = "![shot](ref:not-a-module)\n[plain](ref:a.missing)\n[`x.Y`](https://example.test)\n"
    pages = {"a.b": _page("a.b", body)}
    _unlink_pageless_refs(pages)
    assert pages["a.b"].body == body


def test_generate_links_only_re_exports_whose_target_has_a_page(tmp_path: Path) -> None:
    """End-to-end wiring: generate() must apply the downgrade, not just the helper in isolation.

    ``pkgx.real`` produces a page, so its re-export stays linked; ``pkgx.nosuch`` has no source
    file and therefore no page, so its re-export renders as plain code text.
    """
    pkg = tmp_path / "packages" / "sample" / "src" / "pkgx"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(
        '"""Pkg."""\n\nfrom .nosuch import Thing\nfrom .real import Real\n\n__all__ = ["Thing", "Real"]\n',
        encoding="utf-8",
    )
    (pkg / "real.py").write_text('"""Real."""\n\n\nclass Real:\n    """A real class."""\n', encoding="utf-8")
    cfg = TechwikiConfig(packages=[TechwikiPackage(dist="sample", src="packages/sample/src", roots=["pkgx"])])
    pages, skipped = generate(cfg, tmp_path)
    assert skipped == []
    body = next(page.body for page in pages if page.module == "pkgx")
    assert "Re-exported from [`pkgx.real.Real`](ref:pkgx.real)." in body  # target has a page
    assert "Re-exported from `pkgx.nosuch.Thing`." in body  # target has none
    assert "](ref:pkgx.nosuch)" not in body


@pytest.mark.skipif(
    os.environ.get("TECHWIKI_FULL_BUNDLE") != "1",
    reason="full-repository bundle is slow (~3.4k pages); set TECHWIKI_FULL_BUNDLE=1 to run",
)
def test_full_repository_bundle_has_no_dangling_links() -> None:
    """AC-3: this repository's own bundle resolves every generated link (was 300 rows / 49 targets)."""
    from parrot.sdd.techwiki.bundle import assemble
    from parrot.sdd.techwiki.config import load_techwiki_config

    root = Path(__file__).resolve().parents[4]
    assert (root / "sdd" / "config.json").is_file(), root
    cfg = load_techwiki_config(root)
    _, report = assemble(cfg, root)
    assert report.dangling == [], report.dangling[:10]
    assert report.ok(), (report.collisions[:5], report.dangling[:5])


def test_generated_page_link_to_a_page_named_like_a_markdown_file_is_not_dangling(tmp_path: Path) -> None:
    """A module literally named ``md`` yields a page name ending in ``.md``.

    ``rewrite_links`` resolves any target ending ``.md`` as a relative path, so the reference index's
    already-final link to such a page used to be reported dangling once FEAT-818 began validating
    generated pages. The link is correct and must be left alone.
    """
    from parrot.sdd.techwiki.bundle import assemble

    pkg = tmp_path / "packages" / "sample" / "src" / "pkgy"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('"""Pkg."""\n', encoding="utf-8")
    (pkg / "md.py").write_text('"""Markdown splitter."""\n\n\nclass MdSplitter:\n    """Splits."""\n', encoding="utf-8")
    cfg = TechwikiConfig(packages=[TechwikiPackage(dist="sample", src="packages/sample/src", roots=["pkgy"])])
    pages, report = assemble(cfg, tmp_path)
    assert any(page.name == "API-Reference-pkgy.md" for page in pages), [p.name for p in pages]
    assert report.dangling == [], report.dangling
    assert report.ok(), (report.collisions, report.dangling)
