"""Bundle authored, decision, and generated pages for the technical wiki."""

from __future__ import annotations

import importlib.resources
import json
import logging
import posixpath
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import yaml

from parrot.sdd.techwiki.config import TechwikiConfig
from parrot.sdd.techwiki.naming import PageNameError, page_name, page_title, rewrite_links

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class BundlePage:
    """One page in the assembled wiki bundle."""

    source: Path | None
    section: str
    title: str
    name: str
    body: str


@dataclass
class BundleReport:
    """Summary and validation outcome for a bundle assembly."""

    release: str | None
    commit: str | None
    authored: int = 0
    generated: int = 0
    adrs: int = 0
    skipped_modules: list[dict[str, Any]] = field(default_factory=list)
    collisions: list[dict[str, str]] = field(default_factory=list)
    dangling: list[dict[str, str]] = field(default_factory=list)

    def ok(self) -> bool:
        """Return whether the bundle has neither collisions nor dangling links."""
        return not self.collisions and not self.dangling


def _index_sections(cfg: TechwikiConfig, root: Path) -> tuple[dict[str, str], list[str]]:
    """Return source-section display names and their configured order."""
    index_path = root / cfg.index_file
    if not index_path.exists():
        return {}, []
    raw = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
    entries = raw.get("sections", raw) if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return {}, []
    section_names: dict[str, str] = {}
    ordered: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        section_id = entry.get("id") or entry.get("section")
        if not isinstance(section_id, str):
            continue
        section_name = entry.get("title", section_id.replace("-", " ").title())
        if not isinstance(section_name, str):
            continue
        section_names[section_id] = section_name
        ordered.append(section_id)
    return section_names, ordered


def _source_id(root: Path, source: Path) -> str:
    """Return the stable repository-relative identifier for a source page."""
    return source.relative_to(root).as_posix() if source.is_absolute() else source.as_posix()


def _new_page(source: Path, section: str, text: str) -> BundlePage:
    """Create an unvalidated page from Markdown source text."""
    title = page_title(source, text)
    return BundlePage(source=source, section=section, title=title, name=page_name(section, title), body=text)


def collect_authored(cfg: TechwikiConfig, root: Path) -> list[BundlePage]:
    """Collect authored Markdown pages from the configured wiki source directory.

    Args:
        cfg: Technical-wiki configuration.
        root: Repository root.

    Returns:
        Authored pages in configured section order, followed by unindexed sections.
    """
    source_root = root / cfg.source_dir
    if not source_root.exists():
        return []
    section_names, section_order = _index_sections(cfg, root)
    excluded = {path.as_posix() for pattern in cfg.exclude for path in source_root.glob(pattern)}
    pages_by_section: dict[str, list[BundlePage]] = {}
    for source in sorted(source_root.rglob("*.md")):
        if source.as_posix() in excluded:
            continue
        relative = source.relative_to(source_root)
        if not relative.parts:
            continue
        section_id = relative.parts[0] if len(relative.parts) > 1 else ""
        section = section_names.get(section_id, section_id.replace("-", " ").title())
        page = _new_page(source, section, source.read_text(encoding="utf-8"))
        page.source = source.relative_to(root)
        pages_by_section.setdefault(section_id, []).append(page)
    ordered_ids = [*section_order, *sorted(set(pages_by_section) - set(section_order))]
    return [page for section_id in ordered_ids for page in pages_by_section.get(section_id, [])]


def collect_adrs(cfg: TechwikiConfig, root: Path) -> list[BundlePage]:
    """Collect configured ADR Markdown pages without modifying their sources.

    Args:
        cfg: Technical-wiki configuration.
        root: Repository root.

    Returns:
        Decision pages ordered by configured glob and path.
    """
    sources = {path for pattern in cfg.include_adrs for path in root.glob(pattern) if path.is_file()}
    pages = []
    for source in sorted(sources):
        page = _new_page(source, cfg.adr_section, source.read_text(encoding="utf-8"))
        page.source = source.relative_to(root)
        pages.append(page)
    return pages


def _generated_pages(
    cfg: TechwikiConfig, root: Path, release: str | None
) -> tuple[list[BundlePage], list[dict[str, Any]]]:
    """Generate API pages lazily so sidebar-only does not require griffe."""
    from parrot.sdd.techwiki.api import generate

    rendered, skipped = generate(cfg, root, release=release)
    pages = [
        BundlePage(None, page.section, page.title, page_name(page.section, page.title), page.body) for page in rendered
    ]
    return pages, skipped


def _manifest_entries(pages: list[BundlePage]) -> list[dict[str, str]]:
    """Build stable manifest rows for source paths and generated module identifiers."""
    entries: list[dict[str, str]] = []
    for page in pages:
        if page.source is None:
            module = page.title.removeprefix("Reference: ")
            entries.append({"id": f"ref:{module}", "name": page.name, "section": "api", "kind": "generated"})
        else:
            entries.append(
                {"id": page.source.as_posix(), "name": page.name, "section": page.section, "kind": "authored"}
            )
    return entries


def assemble(
    cfg: TechwikiConfig,
    root: Path,
    *,
    release: str | None = None,
    commit: str | None = None,
    with_api: bool = True,
) -> tuple[list[BundlePage], BundleReport]:
    """Assemble pages and report collisions and unresolved Markdown links.

    Args:
        cfg: Technical-wiki configuration.
        root: Repository root.
        release: Release tag used by API rendering.
        commit: Source commit identifier recorded in the report.
        with_api: Whether generated API pages are included.

    Returns:
        The assembled pages and their validation report. This function never writes files.
    """
    report = BundleReport(release=release, commit=commit)
    pages: list[BundlePage] = []
    for collector, count_name in ((collect_authored, "authored"), (collect_adrs, "adrs")):
        try:
            collected = collector(cfg, root)
        except PageNameError as exc:
            report.collisions.append({"source": str(exc), "reason": "invalid page name"})
            collected = []
        setattr(report, count_name, len(collected))
        pages.extend(collected)
    if with_api:
        try:
            generated, report.skipped_modules = _generated_pages(cfg, root, release)
        except PageNameError as exc:
            report.collisions.append({"source": str(exc), "reason": "invalid page name"})
            generated = []
        report.generated = len(generated)
        pages.extend(generated)

    by_name: dict[str, list[BundlePage]] = {}
    for page in pages:
        by_name.setdefault(page.name, []).append(page)
    for name, matching in sorted(by_name.items()):
        if len(matching) > 1:
            report.collisions.append({"name": name, "sources": ", ".join(str(page.source) for page in matching)})

    manifest: dict[str, str] = {}
    for page in pages:
        if page.source is None:
            manifest[f"ref:{page.title.removeprefix('Reference: ')}"] = page.name
        else:
            manifest[_source_id(root, page.source)] = page.name

    for page in pages:
        if page.source is None:
            continue

        def resolve(target: str) -> str | None:
            if target.startswith("ref:"):
                key = target
            else:
                key = posixpath.normpath(str(PurePosixPath(_source_id(root, page.source)).parent / target))
            resolved = manifest.get(key)
            if resolved is None:
                report.dangling.append({"source": _source_id(root, page.source), "target": target})
            return resolved

        page.body = rewrite_links(page.body, resolve)
    return pages, report


def _template(name: str) -> Any:
    """Load a packaged Jinja template only when writing output."""
    import jinja2

    path = importlib.resources.files("parrot.sdd.techwiki").joinpath(f"templates/{name}")
    return jinja2.Template(path.read_text(encoding="utf-8"), keep_trailing_newline=True)


def write_navigation(pages: list[BundlePage], report: BundleReport, cfg: TechwikiConfig, out: Path) -> None:
    """Write only the Home and Sidebar navigation files.

    Args:
        pages: Assembled pages used to construct navigation.
        report: Bundle metadata rendered onto Home.
        cfg: Technical-wiki configuration.
        out: Destination directory.
    """
    out.mkdir(parents=True, exist_ok=True)
    sections: dict[str, list[BundlePage]] = {}
    for page in pages:
        sections.setdefault(page.section, []).append(page)
    section_rows = [{"name": name, "pages": items} for name, items in sections.items()]
    (out / "Home.md").write_text(
        _template("home.md.j2").render(report=report, site_url=cfg.site_url, sections=section_rows), encoding="utf-8"
    )
    (out / "_Sidebar.md").write_text(_template("sidebar.md.j2").render(sections=section_rows), encoding="utf-8")


def write_bundle(pages: list[BundlePage], report: BundleReport, cfg: TechwikiConfig, out: Path) -> None:
    """Write bundle pages, navigation, report, and manifest into a flat directory.

    Args:
        pages: Assembled pages.
        report: Bundle result to serialize.
        cfg: Technical-wiki configuration.
        out: Destination directory.
    """
    out.mkdir(parents=True, exist_ok=True)
    for page in pages:
        (out / f"{page.name}.md").write_text(page.body, encoding="utf-8")
    write_navigation(pages, report, cfg, out)
    (out / "techwiki-report.json").write_text(
        json.dumps(asdict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = {"pages": _manifest_entries(pages)}
    (out / "techwiki-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
