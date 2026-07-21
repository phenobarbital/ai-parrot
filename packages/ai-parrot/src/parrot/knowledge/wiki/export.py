"""OKF v0.1 bundle export for the LLM Wiki (export-only boundary).

The wiki's internal representation is the machine-first
:class:`WikiStore` SQLite plane; OKF markdown is generated **lazily and
only at export time** as an interchange projection, never read back on
the retrieval path.

Bundle layout (Google OKF v0.1 — markdown files with YAML frontmatter,
one concept per file, ``type`` as the only required field)::

    <output_dir>/
    ├── index.md                 # root catalog of exported pages
    ├── summaries/<id>.md
    ├── entities/<id>.md
    └── <category>s/<id>.md      # one directory per page category

Wiki categories map onto the ``ConceptType.WIKI_*`` vocabulary where a
member exists; other categories export their title-cased raw string —
OKF types are producer-defined, so this remains conformant.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from parrot.knowledge.okf.utils import flatten_concept_id_for_filename
from parrot.knowledge.wiki.store import BaseWikiStore

logger = logging.getLogger(__name__)

# WikiPageCategory value → OKF ConceptType string (FEAT-260 vocabulary).
CATEGORY_TO_OKF_TYPE: dict[str, str] = {
    "summary": "Wiki Summary",
    "entity": "Wiki Entity",
    "comparison": "Wiki Comparison",
    "synthesis": "Wiki Synthesis",
    "overview": "Wiki Overview",
    "concept": "Concept",
}

# Inverse map for consumers that read bundles back (file_store backend).
OKF_TYPE_TO_CATEGORY: dict[str, str] = {
    v: k for k, v in CATEGORY_TO_OKF_TYPE.items()
}


class WikiExportReport(BaseModel):
    """Result of an OKF bundle export.

    Attributes:
        wiki_name: Exported wiki.
        output_dir: Bundle root directory.
        files_written: Number of concept files written.
        index_generated: Whether the root ``index.md`` was written.
        categories: Files written per category directory.
    """

    wiki_name: str = ""
    output_dir: str = ""
    files_written: int = 0
    index_generated: bool = False
    categories: dict[str, int] = Field(default_factory=dict)


def okf_type(category: str) -> str:
    """Map a wiki category to an OKF ``type`` string."""
    return CATEGORY_TO_OKF_TYPE.get(category, category.title() or "Other")


def category_dir(category: str) -> str:
    """Directory name for a category (naive English plural, lowercase)."""
    cat = (category or "concept").lower()
    if cat.endswith("s"):
        return cat
    if cat.endswith("y"):
        return f"{cat[:-1]}ies"
    return f"{cat}s"


def page_frontmatter(
    page: dict[str, Any],
    relates_to: list[dict[str, str]],
) -> str:
    """Render OKF frontmatter for one page (deterministic key order)."""
    data: dict[str, Any] = {
        "type": okf_type(str(page.get("category") or "concept")),
        "title": page.get("title") or page["concept_id"],
        "id": page["concept_id"],
        "tags": [str(page.get("category") or "concept")],
        "timestamp": page.get("updated_at") or "",
    }
    summary = page.get("summary") or ""
    if summary:
        data["summary"] = summary
    if relates_to:
        data["relates_to"] = relates_to
    rendered = yaml.dump(
        data, sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    return f"---\n{rendered}---\n"


def generate_index(wiki_name: str, entries: list[tuple[str, str, str]]) -> str:
    """Render the root ``index.md`` (title, relative path, summary)."""
    lines = [
        f"# {wiki_name}",
        "",
        "<!-- Auto-generated OKF bundle index. Do not edit. -->",
        "",
    ]
    for title, rel_path, summary in entries:
        lines.append(f"## [{title}]({rel_path})")
        if summary:
            lines.append(f"\n{summary}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


async def export_okf_bundle(
    store: BaseWikiStore,
    output_dir: Path,
    wiki_name: str = "",
) -> WikiExportReport:
    """Project a wiki store into an OKF v0.1 markdown bundle.

    Works with any :class:`BaseWikiStore` backend via ``dump_pages`` /
    ``dump_edges`` (for the file backend this re-projects the live
    bundle into ``output_dir``).

    Args:
        store: Source store (any backend).
        output_dir: Bundle root (created if missing).
        wiki_name: Name used in the bundle index header.

    Returns:
        A :class:`WikiExportReport`.
    """
    output_dir = Path(output_dir)
    pages = await store.dump_pages()
    edges = await store.dump_edges()

    # Outgoing typed edges per page → relates_to frontmatter entries.
    known_targets = {p["concept_id"] for p in pages}
    relates_by_src: dict[str, list[dict[str, str]]] = {}
    for edge in edges:
        relates_by_src.setdefault(edge["src"], []).append(
            {"concept": edge["dst"], "rel": edge["rel"]}
        )

    report = WikiExportReport(
        wiki_name=wiki_name, output_dir=str(output_dir)
    )
    index_entries: list[tuple[str, str, str]] = []

    def _write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    for page in pages:
        category = str(page.get("category") or "concept")
        cat_dir = category_dir(category)
        filename = f"{flatten_concept_id_for_filename(page['concept_id'])}.md"
        rel_path = f"{cat_dir}/{filename}"

        frontmatter = page_frontmatter(
            page, relates_by_src.get(page["concept_id"], [])
        )
        body = page.get("body") or page.get("summary") or ""
        await asyncio.to_thread(
            _write, output_dir / rel_path, frontmatter + "\n" + body
        )

        report.files_written += 1
        report.categories[cat_dir] = report.categories.get(cat_dir, 0) + 1
        index_entries.append(
            (
                str(page.get("title") or page["concept_id"]),
                rel_path,
                str(page.get("summary") or ""),
            )
        )

    unknown = {
        e["dst"]
        for e in edges
        if e["dst"] not in known_targets and not e["dst"].startswith("src-")
    }
    if unknown:
        logger.debug(
            "export_okf_bundle: %d relates_to target(s) are not exported "
            "pages (OKF consumers must tolerate broken links)",
            len(unknown),
        )

    await asyncio.to_thread(
        _write,
        output_dir / "index.md",
        generate_index(wiki_name or "wiki", index_entries),
    )
    report.index_generated = True

    logger.info(
        "export_okf_bundle: %d page(s) → %s", report.files_written, output_dir
    )
    return report
