"""``bookstore export-wiki`` — project the book graph into a wikitoolkit plane.

CLI-only (spec §4 Non-Goals: no write tool over MCP). Every
``parrot.knowledge.wiki`` / ``graphindex.export_html`` import is lazy,
inside the functions here — the MCP read path (``toolkit.py``,
``library.py``'s non-export methods, ``mcp_server.py``) never imports
this module, so ``parrot.knowledge.wiki`` never enters ``sys.modules``
on that path (same discipline as ``library.py``'s
``parrot_loaders``/``ai-parrot-loaders`` imports).

Idempotency note: ``BaseWikiStore`` has no delete-edges API, so a
re-export cannot surgically drop stale ``book:*`` edges for relations
that no longer hold. The simplest correct strategy — and the one used
here — is to delete the plane's ``wiki.db`` and rebuild it from scratch
on every export.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .config import LibraryLocation
from .library import BookstoreError
from .models import BookCard, BookRelation

if TYPE_CHECKING:
    from parrot.knowledge.graphindex.communities import CommunitiesResult
    from parrot.knowledge.graphindex.assemble import GraphAssembler
    from parrot.knowledge.graphindex.inter_community import InterCommunityGraph
    from parrot.knowledge.wiki.store import WikiPageRecord

#: Namespace/wiki name this export always registers under (spec §2 step 5).
DEFAULT_WIKI_NAME = "bookstore"


def default_wiki_dir(location: LibraryLocation) -> Path:
    """Default export directory for one library location: ``<library>/wiki``."""
    return location.root / "wiki"


def card_to_page(card: BookCard) -> "WikiPageRecord":
    """Render one :class:`BookCard` as a ``category="book"`` wiki page.

    The body is the rendered ficha (authors, year, language, genre,
    traditions, period, topics, community label, summary) followed by
    the ToC digest — everything an agent querying the exported plane
    needs without a round trip back into the catalog.

    Args:
        card: The card to export.

    Returns:
        A :class:`~parrot.knowledge.wiki.store.WikiPageRecord` with
        ``concept_id=f"book:{book_id}"``, ``origin="ingest"``, and
        ``content_hash=card.source_sha256`` (so a re-export with the
        same source content is a stable, cache-friendly re-write).
    """
    from parrot.knowledge.wiki.store import WikiPageRecord

    lines: list[str] = [f"# {card.title}", ""]
    lines.append(f"Authors: {', '.join(card.authors) or '(unknown)'}")
    if card.year is not None:
        lines.append(f"Year: {card.year}")
    if card.language:
        lines.append(f"Language: {card.language}")
    if card.genre and card.genre != "other":
        lines.append(f"Genre: {card.genre}")
    if card.traditions:
        lines.append(f"Traditions: {', '.join(card.traditions)}")
    if card.period:
        lines.append(f"Period: {card.period}")
    if card.topics:
        lines.append(f"Topics: {', '.join(card.topics)}")
    if card.community_label:
        lines.append(f"Community: {card.community_label}")
    lines.append("")
    if card.summary:
        lines.append(card.summary)
        lines.append("")
    if card.toc_digest:
        lines.append("## Table of contents")
        lines.append(card.toc_digest)
    body = "\n".join(lines).strip() + "\n"

    return WikiPageRecord(
        concept_id=f"book:{card.book_id}",
        category="book",
        title=card.title,
        summary=card.summary.split("\n", 1)[0] if card.summary else card.title,
        body=body,
        source_id=card.source_path,
        origin="ingest",
        content_hash=card.source_sha256,
    )


def relation_to_edge(rel: BookRelation) -> tuple[str, str, str, str]:
    """One :class:`BookRelation` as a ``(src, dst, rel, provenance)`` wiki edge.

    Args:
        rel: The edge to export.

    Returns:
        ``(f"book:{src}", f"book:{dst}", rel.rel, provenance)`` where
        ``provenance`` is ``"inferred"`` for LLM-origin edges and
        ``"extracted"`` for everything else (deterministic/community).
    """
    provenance = "inferred" if rel.origin == "llm" else "extracted"
    return (f"book:{rel.src_book_id}", f"book:{rel.dst_book_id}", rel.rel, provenance)


async def export_plane(
    cards: list[BookCard],
    relations: list[BookRelation],
    communities_result: "CommunitiesResult",
    inter: "InterCommunityGraph",
    assembler: "GraphAssembler",
    out_dir: Path,
    *,
    wiki_name: str = DEFAULT_WIKI_NAME,
) -> dict[str, Any]:
    """Write the book graph into a dedicated wikitoolkit plane.

    Args:
        cards: Every visible card to export as a page.
        relations: Every edge to export (all origins, including
            ``same_community`` — the exported graph is a record of the
            whole book graph, not just the clustering input).
        communities_result: Partition to render into ``graph.html``.
        inter: Inter-community meta-graph, for the same HTML.
        assembler: The assembled graphindex graph backing
            ``communities_result``/``inter`` (its ``.graph`` is what
            ``export_graph`` renders).
        out_dir: Directory to write ``wiki.db``/``graph.html``/
            ``graph.json`` into. Created if missing.
        wiki_name: Name recorded in the wiki's own ``meta`` table.

    Returns:
        ``{"pages": int, "edges": int, "html": str, "json": str}``.

    Raises:
        BookstoreError: The wiki/graphindex packages are not importable.
    """
    try:
        from parrot.knowledge.graphindex.export_html import export_graph
        from parrot.knowledge.wiki.store import SQLiteWikiStore
    except ImportError as exc:
        raise BookstoreError(
            "export-wiki requires the wiki/graphindex packages " "(pip install ai-parrot[wiki])"
        ) from exc

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "wiki.db"
    if db_path.exists():
        # No delete-edges API on BaseWikiStore — rebuild from scratch
        # so relations that no longer hold don't linger (see module
        # docstring).
        db_path.unlink()

    store = SQLiteWikiStore(db_path, wiki_name=wiki_name)
    pages_written = await store.upsert_pages([card_to_page(card) for card in cards])
    edges_written = await store.add_edges([relation_to_edge(rel) for rel in relations])

    html_path, json_path = export_graph(
        assembler.graph,
        out_dir,
        communities=communities_result,
        inter_community=inter,
        title="Bookstore — Book Graph",
    )
    return {
        "pages": pages_written,
        "edges": edges_written,
        "html": str(html_path),
        "json": str(json_path),
    }


def register_namespace(
    store_dir: Path,
    *,
    scope: str,
    git_root: Optional[Path],
    name: str = DEFAULT_WIKI_NAME,
    description: str = "Bookstore book graph",
) -> Path:
    """Register ``name`` as a wikitoolkit namespace pointing at ``store_dir``.

    Mirrors ``wikitoolkit ns add``'s semantics (never imports
    ``wiki/cli.py`` — uses only the load/save primitives): a project
    entry stores its path relative to ``git_root`` (portable across
    checkouts, resolved against the registry's own directory when read
    back); a global entry stores an absolute path. Registering the
    *same* store again (idempotent re-export) is a no-op success; a
    *different* store under the same name is refused, and a name
    collision with the *other* registry is also refused — the caller
    always sees a clear error rather than a silently shadowed entry.

    Args:
        store_dir: The exported plane's directory (holds ``wiki.db``).
        scope: ``"project"`` or ``"global"`` — which registry to prefer.
            Downgraded to global when ``git_root`` is ``None`` (no git
            root / no ``.parrot/wiki.json`` found — spec §7 gotcha).
        git_root: Repository root for project-scope registration, or
            ``None`` (falls back to the global registry regardless of
            ``scope``).
        name: Namespace name.
        description: Shown by ``wikitoolkit ns list``.

    Returns:
        The registry file path written.

    Raises:
        BookstoreError: ``name`` already points at a *different* store
            in either registry.
    """
    from parrot.knowledge.wiki.project import (
        WikiNamespaceConfig,
        load_global_registry,
        load_project_config,
        save_global_registry,
        save_project_config,
    )

    is_global = scope == "global" or git_root is None

    if is_global:
        store_value = str(Path(store_dir).resolve())
        registry = load_global_registry()
        existing = registry.namespaces.get(name)
        if existing is not None:
            if existing.store != store_value:
                raise BookstoreError(
                    f"Namespace {name!r} already registered in the global "
                    f"registry with a different store ({existing.store}) — "
                    f"run `wikitoolkit ns remove {name} --global` first."
                )
            return save_global_registry(registry)
        if git_root is not None and name in load_project_config(git_root).namespaces:
            raise BookstoreError(
                f"Namespace {name!r} already exists in the project registry "
                f"— run `wikitoolkit ns remove {name}` first."
            )
        registry.namespaces[name] = WikiNamespaceConfig(
            store=store_value,
            backend="sqlite",
            description=description,
        )
        return save_global_registry(registry)

    config = load_project_config(git_root)
    try:
        store_value = str(Path(store_dir).resolve().relative_to(Path(git_root).resolve()))
    except ValueError as exc:
        raise BookstoreError(
            f"{store_dir} is outside the project git root ({git_root}) — "
            "project-scope namespace entries must store a path relative "
            "to it. Pass --global to register an absolute path instead."
        ) from exc
    existing = config.namespaces.get(name)
    if existing is not None:
        if existing.store != store_value:
            raise BookstoreError(
                f"Namespace {name!r} already registered with a different "
                f"store ({existing.store}) — run `wikitoolkit ns remove "
                f"{name}` first."
            )
        return save_project_config(git_root, config)
    if name in load_global_registry().namespaces:
        raise BookstoreError(
            f"Namespace {name!r} already exists in the global registry — "
            f"run `wikitoolkit ns remove {name} --global` first."
        )
    config.namespaces[name] = WikiNamespaceConfig(
        store=store_value,
        backend="sqlite",
        description=description,
    )
    return save_project_config(git_root, config)
