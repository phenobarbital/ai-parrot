"""Tests for technical-wiki bundle assembly."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from parrot.sdd.scripts.techwiki_bundle import main
from parrot.sdd.techwiki.bundle import assemble, write_bundle
from parrot.sdd.techwiki.config import load_techwiki_config


@pytest.fixture
def techwiki_repo(tmp_path: Path) -> Path:
    """Copy the fixture repository and initialize it for commit metadata tests."""
    fixture = Path(__file__).parent / "fixtures" / "techwiki_repo"
    root = tmp_path / "repository"
    shutil.copytree(fixture, root)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.test",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    return root


class TestBundle:
    """Bundle validation and output behaviour."""

    def test_bundle_collision_and_dangling_exit_1(
        self, techwiki_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Collision and dangling links return one while the report is still written."""
        out = tmp_path / "out"
        monkeypatch.setattr("parrot.sdd.techwiki.api.generate", lambda *args, **kwargs: ([], []))
        assert main(["--root", str(techwiki_repo), "--out", str(out)]) == 1
        report = json.loads((out / "techwiki-report.json").read_text(encoding="utf-8"))
        assert report["collisions"]
        assert report["dangling"] == [{"source": "wiki/b/two.md", "target": "missing.md"}]

    def test_bundle_home_sidebar_from_index(self, techwiki_repo: Path, tmp_path: Path) -> None:
        """Home and sidebar retain index order and include release, commit, and ADRs."""
        cfg = load_techwiki_config(techwiki_repo)
        pages, report = assemble(cfg, techwiki_repo, release="v1.2.3", commit="abc", with_api=False)
        report.dangling.clear()
        report.collisions.clear()
        out = tmp_path / "out"
        write_bundle(pages, report, cfg, out)
        home = (out / "Home.md").read_text(encoding="utf-8")
        sidebar = (out / "_Sidebar.md").read_text(encoding="utf-8")
        assert "v1.2.3" in home and "abc" in home and "https://example.test/docs" in home
        assert sidebar.index("## Alpha") < sidebar.index("## Beta") < sidebar.index("## Decisions")
        assert "[[Decisions-Decision-One]]" in sidebar

    def test_bundle_dry_run_writes_only_report(self, techwiki_repo: Path, tmp_path: Path) -> None:
        """Dry-run writes the validation report but no wiki pages or navigation."""
        out = tmp_path / "out"
        assert main(["--root", str(techwiki_repo), "--out", str(out), "--dry-run", "--sidebar-only"]) == 1
        assert {path.name for path in out.iterdir()} == {"techwiki-report.json"}

    def test_sidebar_only_writes_navigation(self, techwiki_repo: Path, tmp_path: Path) -> None:
        """Sidebar mode emits only the two requested navigation files."""
        out = tmp_path / "out"
        assert main(["--root", str(techwiki_repo), "--out", str(out), "--sidebar-only"]) == 1
        assert {path.name for path in out.iterdir()} == {"Home.md", "_Sidebar.md"}

    def test_bundle_manifest_resolves_links(self, techwiki_repo: Path, tmp_path: Path) -> None:
        """Each rewritten authored link resolves to a page registered in the manifest."""
        source = techwiki_repo / "wiki" / "b" / "two.md"
        source.write_text("# Two\n", encoding="utf-8")
        cfg = load_techwiki_config(techwiki_repo)
        pages, report = assemble(cfg, techwiki_repo, with_api=False)
        assert not report.dangling
        out = tmp_path / "out"
        write_bundle(pages, report, cfg, out)
        manifest = json.loads((out / "techwiki-manifest.json").read_text(encoding="utf-8"))
        names = {entry["name"] for entry in manifest["pages"]}
        one = next(page for page in pages if page.source == Path("wiki/a/one.md"))
        assert "[[Beta-Two]]" in one.body
        assert "Beta-Two" in names


def test_adr_title_with_hyphen_is_sanitized_not_fatal(techwiki_repo: Path) -> None:
    """A hyphenated ADR title yields a hyphen-free page name instead of failing every ADR."""
    adr = techwiki_repo / "docs" / "decisions" / "hyphen.md"
    adr.write_text("# Clients are memory-less\n\nBody.\n", encoding="utf-8")
    cfg = load_techwiki_config(techwiki_repo)
    pages, report = assemble(cfg, techwiki_repo, with_api=False)
    assert not [c for c in report.collisions if c.get("reason") == "invalid page name"]
    assert any(p.title == "Clients are memory less" and "-" not in p.title for p in pages)
    assert "Clients are memory-less" in adr.read_text(encoding="utf-8")


def test_reserved_page_name_is_a_collision(techwiki_repo: Path) -> None:
    """A top-level page titled Home must not silently be overwritten by the generated navigation."""
    (techwiki_repo / "wiki" / "home.md").write_text("# Home\n\nBody.\n", encoding="utf-8")
    cfg = load_techwiki_config(techwiki_repo)
    _, report = assemble(cfg, techwiki_repo, with_api=False)
    assert any(c.get("name") == "Home" and c.get("reason") == "reserved name" for c in report.collisions)
    assert not report.ok()


def test_report_lists_skipped_modules_first(techwiki_repo: Path, tmp_path: Path) -> None:
    """AC-7b: the report and manifest put skipped modules before everything else."""
    from parrot.sdd.techwiki.bundle import report_payload

    cfg = load_techwiki_config(techwiki_repo)
    pages, report = assemble(cfg, techwiki_repo, with_api=False)
    report.skipped_modules = [{"module": "pkg.broken", "reason": "SyntaxError"}]
    assert next(iter(report_payload(report))) == "skipped_modules"
    out = tmp_path / "out"
    write_bundle(pages, report, cfg, out)
    assert next(iter(json.loads((out / "techwiki-report.json").read_text()))) == "skipped_modules"
    manifest = json.loads((out / "techwiki-manifest.json").read_text())
    assert next(iter(manifest)) == "skipped_modules"
    assert manifest["skipped_modules"] == report.skipped_modules


def test_empty_packages_is_reported_as_skipped(techwiki_repo: Path) -> None:
    """With no packages configured the API reference is not silently empty: it is a skipped entry."""
    from parrot.sdd.techwiki.api import generate

    cfg = load_techwiki_config(techwiki_repo)
    cfg = cfg.model_copy(update={"packages": []})
    pages, skipped = generate(cfg, techwiki_repo)
    assert pages == []
    assert skipped and skipped[0]["reason"] == "no packages configured"


def test_collision_with_generated_page_names_its_ref_id(techwiki_repo: Path) -> None:
    """A collision with a generated page reports ref:<module>, not 'None'."""
    from parrot.sdd.techwiki import bundle as bundle_module

    class _Gen:
        module, title, name, body, section, source = "x.y", "Reference: x.y", "Dup", "b", "API Reference", None

    cfg = load_techwiki_config(techwiki_repo)
    original = bundle_module._generated_pages
    bundle_module._generated_pages = lambda c, r, rel: ([_Gen(), _Gen()], [])  # type: ignore[assignment]
    try:
        _, report = bundle_module.assemble(cfg, techwiki_repo)
    finally:
        bundle_module._generated_pages = original
    sources = " ".join(c.get("sources", "") for c in report.collisions)
    assert "None" not in sources
