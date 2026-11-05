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
        assert "- [Decision One](Decisions-Decision-One)\n" in sidebar
        assert "- [Decision One](Decisions-Decision-One)\n" in home  # Home links every page too, not only counts
        assert "[[" not in sidebar and "[[" not in home

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
        assert "[Two](Beta-Two)" in one.body  # the author's link text survives the rewrite
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
        module, title, name, body, section, source = "x.y", "x.y", "Dup", "b", "API Reference", None

    cfg = load_techwiki_config(techwiki_repo)
    original = bundle_module._generated_pages
    bundle_module._generated_pages = lambda c, r, rel: ([_Gen(), _Gen()], [])  # type: ignore[assignment]
    try:
        _, report = bundle_module.assemble(cfg, techwiki_repo)
    finally:
        bundle_module._generated_pages = original
    sources = " ".join(c.get("sources", "") for c in report.collisions)
    assert "None" not in sources
    assert "ref:x.y" in sources


# --- bundle + real generated API pages (needs the griffe extra) --------------------------------------------


@pytest.fixture
def api_repo(techwiki_repo: Path) -> Path:
    """The bundle fixture repository extended with the static sample package as a configured distribution."""
    import importlib.util
    import os

    if importlib.util.find_spec("griffe") is None:
        if os.environ.get("TECHWIKI_REQUIRE_GRIFFE") == "1":
            pytest.fail("TECHWIKI_REQUIRE_GRIFFE=1 but the griffe extra is not installed")
        pytest.skip("griffe extra is not installed")
    fixture = Path(__file__).parent / "fixtures" / "techwiki_pkg"
    destination = techwiki_repo / "packages" / "sample" / "src"
    shutil.copytree(fixture, destination)
    config_path = techwiki_repo / "sdd" / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["techwiki"]["packages"] = [{"dist": "sample", "src": "packages/sample/src", "roots": ["samplepkg"]}]
    config_path.write_text(json.dumps(config), encoding="utf-8")
    (techwiki_repo / "wiki" / "b" / "two.md").write_text(
        "# Two\n", encoding="utf-8"
    )  # drop the deliberate dangling link
    (techwiki_repo / "wiki" / "b" / "two-copy.md").unlink()  # and the deliberate authored name collision
    return techwiki_repo


def test_ref_links_resolve_to_generated_pages(api_repo: Path, tmp_path: Path) -> None:
    """``ref:<module>`` links become links to the generated reference page; an unknown module is dangling."""
    one = api_repo / "wiki" / "a" / "one.md"
    one.write_text(
        "---\ntitle: One\n---\n\n# One\n\n[Core](ref:samplepkg.core) [Nope](ref:samplepkg.nope)\n", encoding="utf-8"
    )
    cfg = load_techwiki_config(api_repo)
    pages, report = assemble(cfg, api_repo)
    page = next(p for p in pages if p.source == Path("wiki/a/one.md"))
    assert "[Core](API-Reference-samplepkg.core)" in page.body
    assert "[Nope](ref:samplepkg.nope)" in page.body
    assert report.dangling == [{"source": "wiki/a/one.md", "target": "ref:samplepkg.nope"}]
    core = next(p for p in pages if p.module == "samplepkg.core")
    assert core.title == "samplepkg.core" and core.name == "API-Reference-samplepkg.core"


def test_generated_pages_use_the_configured_reference_section(api_repo: Path) -> None:
    """The section of a generated page comes from ``techwiki.reference_section``, not a hard-coded name."""
    cfg = load_techwiki_config(api_repo).model_copy(update={"reference_section": "Code Reference"})
    pages, report = assemble(cfg, api_repo)
    core = next(p for p in pages if p.module == "samplepkg.core")
    assert core.section == "Code Reference" and core.name == "Code-Reference-samplepkg.core"
    assert not report.collisions


def test_written_bundle_file_names_are_artifact_safe(api_repo: Path, tmp_path: Path) -> None:
    """No written file carries a character ``actions/upload-artifact`` rejects (the 2.1.0 release failure)."""
    from parrot.sdd.techwiki.naming import FORBIDDEN_NAME_CHARS

    (api_repo / "wiki" / "a" / "colon.md").write_text("# Server Layer: BotManager and Handlers\n", encoding="utf-8")
    cfg = load_techwiki_config(api_repo)
    pages, report = assemble(cfg, api_repo)
    assert report.ok(), (report.collisions, report.dangling)
    out = tmp_path / "out"
    write_bundle(pages, report, cfg, out)
    names = [path.name for path in out.iterdir()]
    assert "Alpha-Server-Layer-BotManager-and-Handlers.md" in names
    assert "API-Reference-samplepkg.core.md" in names
    assert not [name for name in names if any(char in name for char in FORBIDDEN_NAME_CHARS)]


def test_every_rewritten_link_resolves_in_the_manifest(api_repo: Path, tmp_path: Path) -> None:
    """S9: every page link in every written page (navigation and index included) names a manifest page."""
    import re
    from urllib.parse import unquote

    cfg = load_techwiki_config(api_repo)
    pages, report = assemble(cfg, api_repo)
    assert report.ok(), (report.collisions, report.dangling)
    out = tmp_path / "out"
    write_bundle(pages, report, cfg, out)
    manifest = json.loads((out / "techwiki-manifest.json").read_text(encoding="utf-8"))
    names = {entry["name"] for entry in manifest["pages"]}
    assert any(name.startswith("API-Reference-") for name in names)
    checked = 0
    for written in out.glob("*.md"):
        text = written.read_text(encoding="utf-8")
        assert "[[" not in text, written.name  # no wiki-link syntax anywhere in the bundle
        for target in re.findall(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)", text):
            if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target) or target.startswith("#"):
                continue  # external URL or in-page anchor
            page = unquote(target.partition("#")[0])
            if page.endswith(".md") or "/" in page:
                continue  # an unresolved (dangling) relative link, reported separately
            checked += 1
            assert page in names or page == "Home", (written.name, target)
    assert checked > 0


def test_sidebar_links_one_reference_index_page_instead_of_every_module(api_repo: Path, tmp_path: Path) -> None:
    """The reference section of the sidebar and Home is one ``API-Reference`` link; the index links every module."""
    cfg = load_techwiki_config(api_repo)
    pages, report = assemble(cfg, api_repo)
    assert report.ok(), (report.collisions, report.dangling)
    out = tmp_path / "out"
    write_bundle(pages, report, cfg, out)
    sidebar = (out / "_Sidebar.md").read_text(encoding="utf-8")
    assert "## API Reference\n- [API Reference](API-Reference)\n" in sidebar
    assert "(API-Reference-samplepkg" not in sidebar
    assert "- [Decision One](Decisions-Decision-One)\n" in sidebar  # other sections still list every page
    index = (out / "API-Reference.md").read_text(encoding="utf-8")
    assert index.startswith("# API Reference\n")
    assert "## samplepkg\n" in index
    generated = [p for p in pages if p.module]
    assert generated and all(f"- [{p.module}]({p.name})" in index for p in generated)
    manifest = json.loads((out / "techwiki-manifest.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest["pages"] if e["name"] == "API-Reference")
    assert entry == {"id": "index:API-Reference", "name": "API-Reference", "section": "api", "kind": "index"}
    home = (out / "Home.md").read_text(encoding="utf-8")
    assert f"{len(generated) + 1} page(s)" in home  # Home still counts the module pages plus the index
    assert "- [API Reference](API-Reference)\n" in home and "(API-Reference-samplepkg" not in home
    authored = [p for p in pages if p.source is not None]
    assert authored and all(f"- [{p.title}]({p.name})" in home for p in authored if "-" not in p.title)


def test_authored_api_reference_page_collides_with_the_index(api_repo: Path) -> None:
    """A top-level authored page titled like the reference section is reported as a collision with the index."""
    (api_repo / "wiki" / "api-reference.md").write_text("# API Reference\n\nMine.\n", encoding="utf-8")
    cfg = load_techwiki_config(api_repo)
    _, report = assemble(cfg, api_repo)
    clash = [c for c in report.collisions if c.get("name") == "API-Reference"]
    assert clash and "index:API-Reference" in clash[0]["sources"] and "wiki/api-reference.md" in clash[0]["sources"]


def test_no_reference_index_without_generated_pages(techwiki_repo: Path) -> None:
    """Sidebar-only / no-API assembly emits no index page."""
    cfg = load_techwiki_config(techwiki_repo)
    pages, _ = assemble(cfg, techwiki_repo, with_api=False)
    assert not [p for p in pages if p.name == "API-Reference"]


def test_authored_page_colliding_with_a_generated_name(api_repo: Path) -> None:
    """An authored page whose name equals a generated reference page's name is a reported collision (AC-5)."""
    (api_repo / "wiki" / "_index.yaml").write_text(
        "sections:\n  - id: ref\n    title: API Reference\n", encoding="utf-8"
    )
    (api_repo / "wiki" / "ref").mkdir()
    (api_repo / "wiki" / "ref" / "core.md").write_text("# samplepkg.core\n\nClash.\n", encoding="utf-8")
    cfg = load_techwiki_config(api_repo)
    _, report = assemble(cfg, api_repo)
    clash = [c for c in report.collisions if c.get("name") == "API-Reference-samplepkg.core"]
    assert clash and "ref:samplepkg.core" in clash[0]["sources"] and "wiki/ref/core.md" in clash[0]["sources"]


def test_generated_page_ref_links_are_rewritten(api_repo: Path) -> None:
    """issue:0891861cb3c1 — a generated page's ``ref:`` links are rewritten, not published verbatim."""
    cfg = load_techwiki_config(api_repo)
    pages, report = assemble(cfg, api_repo)
    init = next(p for p in pages if p.module == "samplepkg")
    # samplepkg/__init__.py re-exports PublicModel from .core, so module.md.j2 renders a
    # ref:samplepkg.core link into this page's body. Assert on the resolved PAGE NAME, never on
    # the link syntax: "[[Page]]" today, "[text](Page)" once the Markdown-links branch lands.
    assert "API-Reference-samplepkg.core" in init.body
    assert "](ref:" not in init.body
    # No generated page anywhere may keep a literal ref: target (AC-1).
    for page in pages:
        if page.source is None:
            assert "](ref:" not in page.body, (page.name, page.body)
    assert report.ok(), (report.collisions, report.dangling)


def test_unresolvable_links_in_a_generated_page_are_dangling(
    techwiki_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A generated page's unresolvable ``ref:`` and relative targets are reported, not crashed on."""
    from parrot.sdd.techwiki import bundle as bundle_module

    def fake_generated(cfg, root, release):  # type: ignore[no-untyped-def]
        page = bundle_module.BundlePage(
            source=None,
            section=cfg.reference_section,
            title="samplepkg.fake",
            name="API-Reference-samplepkg.fake",
            body="# fake\n\n[Gone](ref:samplepkg.gone) [Rel](../other.md)\n",
            module="samplepkg.fake",
        )
        return [page], []

    monkeypatch.setattr(bundle_module, "_generated_pages", fake_generated)
    cfg = load_techwiki_config(techwiki_repo)
    _, report = assemble(cfg, techwiki_repo)
    generated_rows = [row for row in report.dangling if row["source"] == "ref:samplepkg.fake"]
    # The ref: row proves generated pages are validated at all (AC-2); the relative row proves the
    # no-source branch returns instead of dereferencing page.source (AC-3).
    assert {row["target"] for row in generated_rows} == {"ref:samplepkg.gone", "../other.md"}
    assert not report.ok()
