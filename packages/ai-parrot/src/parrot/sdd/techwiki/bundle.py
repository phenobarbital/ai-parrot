"""Bundle authored, decision, and generated pages for the technical wiki."""

from __future__ import annotations

import importlib.resources
import json
import logging
import posixpath
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from parrot.sdd.techwiki.config import TechwikiConfig
from parrot.sdd.techwiki.naming import (
    UNLINK,
    PageNameError,
    page_href,
    page_link,
    page_name,
    page_title,
    rewrite_links,
)

logger = logging.getLogger(__name__)

_RESERVED_NAMES = frozenset({"Home", "_Sidebar", "techwiki-report", "techwiki-manifest"})


@dataclass
class BundlePage:
    """One page in the assembled wiki bundle."""

    source: Path | None
    section: str
    title: str
    name: str
    body: str
    module: str | None = None  # dotted module of a generated API page; None for authored and ADR pages


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
    # Informational: generated-page ``ref:`` links whose module has no page (a re-export from an import
    # shim without a public API). The link is dropped and its text kept; this never fails the bundle.
    unlinked: list[dict[str, str]] = field(default_factory=list)

    def ok(self) -> bool:
        """Return whether the bundle has neither collisions nor dangling links (unlinked rows do not count)."""
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


def _new_page(source: Path, section: str, text: str, *, sanitize_title: bool = False) -> BundlePage:
    """Create an unvalidated page from Markdown source text.

    Args:
        source: Markdown source path.
        section: Wiki section display name.
        text: Complete markdown text.
        sanitize_title: Replace literal hyphens in the title with spaces. Used for sources that
            must not be edited (decision records), whose titles GitHub would otherwise rewrite.
    """
    title = page_title(source, text)
    if sanitize_title:
        title = " ".join(title.replace("-", " ").split())
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
        page = _new_page(source, cfg.adr_section, source.read_text(encoding="utf-8"), sanitize_title=True)
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
        BundlePage(None, page.section, page.title, page_name(page.section, page.title), page.body, module=page.module)
        for page in rendered
    ]
    return pages, skipped


def _reference_index_page(cfg: TechwikiConfig, generated: list[BundlePage]) -> BundlePage:
    """Build the one generated page the sidebar links for the reference section.

    GitHub renders ``_Sidebar.md`` on every wiki page, so listing thousands of module pages there makes the
    wiki unusable; the sidebar links this index instead, and the index links every module page grouped by
    top-level package.

    Args:
        cfg: Technical-wiki configuration (section name).
        generated: The generated module pages, each carrying ``module``.

    Returns:
        A page with ``source=None`` and ``module=None`` named after the reference section (``API-Reference``).
    """
    by_root: dict[str, list[BundlePage]] = {}
    for page in generated:
        by_root.setdefault(str(page.module).split(".", 1)[0], []).append(page)
    lines = [
        f"# {cfg.reference_section}",
        "",
        "Generated reference for every public module, one page per module, grouped by top-level package.",
    ]
    for root_name in sorted(by_root):
        lines.extend(["", f"## {root_name}", ""])
        lines.extend(
            f"- {page_link(page.name, str(page.module))}"
            for page in sorted(by_root[root_name], key=lambda item: str(item.module))
        )
    return BundlePage(
        source=None,
        section=cfg.reference_section,
        title=cfg.reference_section,
        name=page_name(None, cfg.reference_section),
        body="\n".join(lines) + "\n",
    )


def _manifest_entries(pages: list[BundlePage]) -> list[dict[str, str]]:
    """Build stable manifest rows for source paths, generated module identifiers and the reference index."""
    entries: list[dict[str, str]] = []
    for page in pages:
        if page.source is None:
            kind = "generated" if page.module else "index"
            entries.append({"id": _ref_id(page), "name": page.name, "section": "api", "kind": kind})
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
        if generated:
            pages.append(_reference_index_page(cfg, generated))

    by_name: dict[str, list[BundlePage]] = {}
    for page in pages:
        by_name.setdefault(page.name, []).append(page)
    for name, matching in sorted(by_name.items()):
        if len(matching) > 1:
            report.collisions.append(
                {"name": name, "sources": ", ".join(str(page.source or _ref_id(page)) for page in matching)}
            )

    for reserved in sorted(_RESERVED_NAMES & set(by_name)):
        report.collisions.append(
            {
                "name": reserved,
                "reason": "reserved name",
                "sources": ", ".join(str(page.source or _ref_id(page)) for page in by_name[reserved]),
            }
        )

    manifest: dict[str, str] = {}
    for page in pages:
        if page.source is None:
            manifest[_ref_id(page)] = page.name
        else:
            manifest[_source_id(root, page.source)] = page.name

    for page in pages:
        if page.source is None and page.module is None:
            continue  # the reference index page: its links are final hrefs built by _reference_index_page

        def resolve(target: str, page: BundlePage = page) -> str | None | object:
            """Return the wiki page name a link target names, recording unresolved targets as dangling.

            Args:
                target: The raw Markdown link target (``ref:<module>``, ``index:<name>`` or a relative path).
                page: The page the link appears on, bound at definition time.

            Returns:
                The resolved page name; ``None`` when the target is not in the manifest (reported as
                dangling); :data:`UNLINK` for a generated page's ``ref:`` to a module that has no page
                (reported as unlinked, the link text is kept).
            """
            origin = _source_id(root, page.source) if page.source is not None else _ref_id(page)
            if target.startswith(("ref:", "index:")):
                key = target
            elif page.source is None:
                # A generated page has no location in the source tree to resolve a relative link against.
                report.dangling.append({"source": origin, "target": target})
                return None
            else:
                key = posixpath.normpath(str(PurePosixPath(_source_id(root, page.source)).parent / target))
            resolved = manifest.get(key)
            if resolved is None:
                if page.source is None and target.startswith("ref:"):
                    # Re-export from a module without public members (e.g. an import shim without
                    # __all__): there is no page to link, and that is not an authoring error.
                    report.unlinked.append({"source": origin, "target": target})
                    return UNLINK
                report.dangling.append({"source": origin, "target": target})
            return resolved

        page.body = rewrite_links(page.body, resolve)
    return pages, report


def _ref_id(page: BundlePage) -> str:
    """Return the ``ref:<module>`` identifier of a generated page (the key links use), or ``index:<name>``."""
    return f"ref:{page.module}" if page.module else f"index:{page.name}"


def report_payload(report: BundleReport) -> dict[str, Any]:
    """Return the report as an ordered mapping with skipped modules first (AC-7b).

    Args:
        report: Bundle result to serialize.

    Returns:
        A dict whose first key is ``skipped_modules``; remaining keys are alphabetical, so output stays deterministic.
    """
    payload = asdict(report)
    skipped = payload.pop("skipped_modules")
    return {"skipped_modules": skipped, **{key: payload[key] for key in sorted(payload)}}


def _template(name: str) -> Any:
    """Load a packaged Jinja template only when writing output."""
    import jinja2

    path = importlib.resources.files("parrot.sdd.techwiki").joinpath(f"templates/{name}")
    return jinja2.Template(path.read_text(encoding="utf-8"), keep_trailing_newline=True)


def write_navigation(pages: list[BundlePage], report: BundleReport, cfg: TechwikiConfig, out: Path) -> None:
    """Write only the Home and Sidebar navigation files.

    Both list every authored and decision page as a plain Markdown link (never ``[[Page]]``, which GitHub
    cannot render by the hundreds in a wiki this size). For the reference section they link only the index
    page (``module is None``), since the thousands of module pages belong on the index; Home also shows the
    full page count of every section.

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
    rows = [
        {
            "name": name,
            "count": len(items),
            "pages": [
                {"title": p.title, "href": page_href(p.name)}
                for p in (items if name != cfg.reference_section else [p for p in items if p.module is None])
            ],
        }
        for name, items in sections.items()
    ]
    (out / "Home.md").write_text(
        _template("home.md.j2").render(report=report, site_url=cfg.site_url, sections=rows), encoding="utf-8"
    )
    (out / "_Sidebar.md").write_text(_template("sidebar.md.j2").render(sections=rows), encoding="utf-8")


def write_bundle(pages: list[BundlePage], report: BundleReport, cfg: TechwikiConfig, out: Path) -> None:
    """Write bundle pages, navigation, report, and manifest into a flat directory.

    The directory is not cleared first: stale pages from an earlier run survive, so publish from a fresh
    directory (CI does) or sync with deletion.

    Args:
        pages: Assembled pages.
        report: Bundle result to serialize.
        cfg: Technical-wiki configuration.
        out: Destination directory.
    """
    out.mkdir(parents=True, exist_ok=True)
    out_root = out.resolve()
    for page in pages:
        target = (out / f"{page.name}.md").resolve()
        if target.parent != out_root:
            raise PageNameError(f"Page name {page.name!r} would be written outside the output directory")
        target.write_text(page.body, encoding="utf-8")
    write_navigation(pages, report, cfg, out)
    (out / "techwiki-report.json").write_text(json.dumps(report_payload(report), indent=2) + "\n", encoding="utf-8")
    manifest = {"skipped_modules": report.skipped_modules, "pages": _manifest_entries(pages)}
    (out / "techwiki-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
