"""§32 Graph workflow (FEAT-481, spec Module 14).

Writes optional, **rebuildable** reports under ``Wiki/Graph/`` — every
artifact is labeled derived and is never treated as canonical (§32 rules
4/5). The GraphIndex/PageIndex plane (``graph.py``, spec Module 13)
remains the primary query/relationship engine; this module only renders
a human-readable snapshot of what the vault's own wikilinks/pages
already say.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

#: §32 rule 4 — every graph artifact is labeled derived.
_DERIVED_BANNER = (
    "> **Derived report — not canonical.** Regenerate with the `graph` "
    "intent; never edit by hand. The GraphIndex/PageIndex plane is the "
    "primary query graph (§28/§32); this page is a human-readable "
    "snapshot only."
)


class GraphReportResult(BaseModel):
    """Result of one §32 graph report.

    Attributes:
        target: The requested report target (e.g. a project name, or
            ``"overview"`` for a vault-wide inventory).
        content: The rendered Markdown report.
        vault_path: ``Wiki/Graph/<target>.md``.
    """

    target: str
    content: str
    vault_path: str


async def run_graph_report(toolkit: Any, target: str) -> GraphReportResult:
    """Build a derived graph report for ``target`` (§32).

    Args:
        toolkit: This subsystem's own ``ObsidianToolkit`` (spec Module 4).
        target: A project name (renders that project's relationship
            inventory) or ``"overview"`` (renders a vault-wide node/edge
            inventory).

    Returns:
        The :class:`GraphReportResult`.
    """
    if target.lower() == "overview":
        content = await _render_overview_report(toolkit)
    else:
        content = await _render_project_report(toolkit, target)

    vault_path = f"Wiki/Graph/{target}.md"
    return GraphReportResult(target=target, content=content, vault_path=vault_path)


async def _render_overview_report(toolkit: Any) -> str:
    """§32 — a vault-wide node/edge inventory, derived from ``catalog_notes()``."""
    catalog = await toolkit.catalog_notes()
    lines = [
        "# Graph Overview",
        "",
        _DERIVED_BANNER,
        "",
        f"- Total pages: {catalog.get('note_count', 0)}",
        f"- Orphan pages: {len(catalog.get('orphans', []))}",
        f"- Broken links: {len(catalog.get('broken_links', []))}",
        "",
        "## Pages per folder",
        *(f"- `{folder}`: {count}" for folder, count in catalog.get("notes_per_folder", {}).items()),
    ]
    return "\n".join(lines) + "\n"


async def _render_project_report(toolkit: Any, project_name: str) -> str:
    """§32 — one project's relationship inventory, derived from its page's own links."""
    path = f"Projects/{project_name}/{project_name}.md"
    try:
        await toolkit.read_note(path, include_content=False)
    except FileNotFoundError:
        return f"# {project_name} — Graph Report\n\n{_DERIVED_BANNER}\n\nNo project page found at `{path}`.\n"

    links = await toolkit.get_outgoing_links(path)
    relationship_lines = (
        [f"- [[{link['target']}]]" for link in links.get("links", [])] if links.get("links") else ["- None identified"]
    )
    lines = [
        f"# {project_name} — Graph Report",
        "",
        _DERIVED_BANNER,
        "",
        "## Relationships (from existing wikilinks)",
        *relationship_lines,
    ]
    return "\n".join(lines) + "\n"
