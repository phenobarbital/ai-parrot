"""``bookstore`` CLI — manage the personal indexed library.

Subcommands: ``add`` / ``add-folder`` / ``list`` / ``show`` / ``search`` /
``toc`` / ``card`` / ``related`` / ``relate`` / ``communities`` /
``export-wiki`` / ``optimize`` / ``ask`` / ``doctor`` / ``remove`` / ``mcp`` /
``locations`` (FEAT-858 adds ``ask``/``doctor``; FEAT-533 adds
``related``/``relate``/``communities``/``export-wiki`` — see
``wiki/knowledge/bookstore-graph.md``). Heavy parrot imports are deferred into
command bodies (the ``wiki/cli.py`` discipline) so ``bookstore --help``
stays fast and the ``mcp`` path keeps stdout clean.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Optional

import click

from .config import resolve_locations

# Captured at import time, BEFORE any command body lazily imports
# `.library` → parrot.knowledge.pageindex → navconfig, whose settings
# module chdir()s to the installed package root as an import side
# effect. Resolving the project scope from Path.cwd() after that would
# silently point at ai-parrot's own tree instead of the user's repo
# (same guard as mcp_server.py's _INVOCATION_CWD).
_INVOCATION_CWD = os.getcwd()


def _open_bookstore(
    llm_spec: Optional[str] = None,
    require_exists: bool = False,
    scope_needed: Optional[str] = None,
    use_llm: bool = True,
) -> Any:
    """Build a :class:`Bookstore` for the CLI invocation."""
    from ._llm import resolve_adapter
    from .library import Bookstore, BookstoreError

    locations = resolve_locations(cwd=Path(_INVOCATION_CWD), require_exists=require_exists)
    if scope_needed and not any(loc.scope == scope_needed for loc in locations):
        hint = (
            " — not inside a git repository; cd into your project, set " "PARROT_LIBRARY_DIR, or use --global"
            if scope_needed == "project"
            else ""
        )
        raise click.ClickException(f"No {scope_needed} library location available{hint}")
    if not locations:
        raise click.ClickException("No library found — add a book first with `bookstore add <file>`")
    adapter, light = (None, None)
    if use_llm:
        adapter, light, _client = resolve_adapter(llm_spec)
    try:
        return Bookstore(locations, adapter=adapter, lightweight_model=light)
    except BookstoreError as exc:
        raise click.ClickException(str(exc)) from exc


def _echo_card(card: Any) -> None:
    click.echo(f"[{card.book_id}] {card.title}")
    if card.authors:
        click.echo(f"  authors : {', '.join(card.authors)}")
    meta = " · ".join(
        str(part)
        for part in (
            card.year,
            card.language,
            f"{card.chapter_count} chapters",
            f"{card.page_count} pages" if card.page_count else None,
            card.scope,
        )
        if part
    )
    click.echo(f"  {meta}")
    if card.topics:
        click.echo(f"  topics  : {', '.join(card.topics)}")
    if card.summary:
        click.echo(f"  summary : {card.summary}")
    classification = " · ".join(
        str(part)
        for part in (
            card.genre if getattr(card, "genre", "other") != "other" else None,
            ", ".join(card.traditions) if getattr(card, "traditions", None) else None,
            card.period if getattr(card, "period", None) else None,
        )
        if part
    )
    if classification:
        click.echo(f"  class   : {classification}")
    if getattr(card, "community_label", None):
        click.echo(f"  community: {card.community_label}")


@click.group(name="bookstore")
def bookstore() -> None:
    """Personal indexed library (biblioteca) over PageIndex trees."""


@bookstore.command("add")
@click.argument("file")
@click.option("--global", "global_scope", is_flag=True, help="Add to ~/.parrot/library.")
@click.option("--title", default=None, help="Override the book title.")
@click.option("--author", "authors", multiple=True, help="Override authors.")
@click.option("--topic", "topics", multiple=True, help="Override topics.")
@click.option("--force", is_flag=True, help="Re-index even if already added.")
@click.option("--no-llm", is_flag=True, help="Skip LLM carding/summaries.")
@click.option("--relate", is_flag=True, help="Compute relations for this book after adding it.")
@click.option(
    "--llm",
    default=None,
    help="LLM spec 'provider:model' (default: $PARROT_BOOKSTORE_LLM).",
)
@click.option(
    "--import",
    "import_tree",
    is_flag=True,
    help="FILE is a PageIndex tree JSON (or an in-library tree name) to adopt without re-ingesting.",
)
@click.option(
    "--as",
    "as_kind",
    type=click.Choice(["book", "notes"]),
    default="book",
    show_default=True,
    help="Catalog the imported tree as a book or a notebook.",
)
@click.option("--for", "notes_for", default=None, help="With --as notes: the book these notes belong to.")
def add(
    file: str,
    global_scope: bool,
    title: Optional[str],
    authors: tuple[str, ...],
    topics: tuple[str, ...],
    force: bool,
    no_llm: bool,
    relate: bool,
    llm: Optional[str],
    import_tree: bool,
    as_kind: str,
    notes_for: Optional[str],
) -> None:
    """Index FILE (pdf/md/txt/epub/mobi/docx) and catalog its ficha.

    With ``--import``, FILE is an existing PageIndex tree (a ``.json`` path
    or an uncatalogued tree name inside the library) adopted as a book or,
    with ``--as notes``, as a notebook — nothing is re-ingested.
    """
    if not import_tree:
        if as_kind != "book":
            raise click.UsageError("--as notes requires --import")
        if notes_for is not None:
            raise click.UsageError("--for requires --import --as notes")
    elif notes_for is not None and as_kind != "notes":
        raise click.UsageError("--for requires --as notes")
    elif authors or topics or relate:
        raise click.UsageError("--author/--topic/--relate cannot be combined with --import")

    from .library import BookstoreError

    scope = "global" if global_scope else "project"
    if import_tree:
        # A path (``.json`` or an existing file) is anchored to the
        # invocation directory NOW — the heavy imports chdir() the process
        # (see _INVOCATION_CWD); anything else is an in-library tree name.
        candidate = Path(_INVOCATION_CWD) / Path(file).expanduser()
        source = str(candidate.resolve()) if file.endswith(".json") or candidate.is_file() else file
        store = _open_bookstore(llm_spec=llm, scope_needed=scope, use_llm=not no_llm)
        try:
            card, status = asyncio.run(
                store.import_tree(
                    source,
                    scope,
                    as_kind=as_kind,
                    notes_for=notes_for,
                    title=title,
                    force=force,
                )
            )
        except BookstoreError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(f"{status}: {card.book_id} ({scope})")
        return

    # Anchor a relative FILE to the invocation directory NOW — the heavy
    # imports below chdir() the process (see _INVOCATION_CWD).
    resolved = (Path(_INVOCATION_CWD) / file).resolve()
    if not resolved.exists():
        raise click.BadParameter(f"File {file!r} does not exist.", param_hint="'FILE'")
    if resolved.is_dir():
        raise click.BadParameter(f"File {file!r} is a directory.", param_hint="'FILE'")
    file = str(resolved)

    store = _open_bookstore(
        llm_spec=llm,
        scope_needed=scope,
        use_llm=not no_llm,
    )
    try:
        card, status = asyncio.run(
            store.add_book(
                file,
                scope=scope,
                title=title,
                authors=list(authors) or None,
                topics=list(topics) or None,
                force=force,
                relate=relate,
            )
        )
    except BookstoreError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"{status}: {card.book_id} ({card.chapter_count} chapters)")
    _echo_card(card)


@bookstore.command("add-folder")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("--recursive", "-r", is_flag=True, help="Descend into subdirectories.")
@click.option("--global", "global_scope", is_flag=True, help="Add to ~/.parrot/library.")
@click.option("--force", is_flag=True, help="Re-index files already added.")
@click.option("--no-llm", is_flag=True, help="Skip LLM carding/summaries.")
@click.option(
    "--relate",
    is_flag=True,
    help="Relate each new book, then compute communities once at the end.",
)
@click.option(
    "--llm",
    default=None,
    help="LLM spec 'provider:model' (default: $PARROT_BOOKSTORE_LLM).",
)
@click.option("--dry-run", is_flag=True, help="List what would be indexed, change nothing.")
def add_folder(
    folder: str,
    recursive: bool,
    global_scope: bool,
    force: bool,
    no_llm: bool,
    relate: bool,
    llm: Optional[str],
    dry_run: bool,
) -> None:
    """Index every supported file (pdf/md/txt/epub/mobi/docx) in FOLDER.

    Files are processed sequentially; a failing file is reported and the
    loop continues with the next one.
    """
    # Anchor a relative FOLDER to the invocation directory NOW — the
    # heavy imports below chdir() the process (see _INVOCATION_CWD).
    folder = str((Path(_INVOCATION_CWD) / folder).resolve())

    from .library import Bookstore, BookstoreError

    try:
        supported, ignored = Bookstore.iter_folder_files(folder, recursive=recursive)
    except BookstoreError as exc:
        raise click.ClickException(str(exc)) from exc
    if not supported:
        click.echo("No ingestable files found (pdf/md/txt/epub/mobi/docx).")
        return
    if dry_run:
        click.echo(f"Would index {len(supported)} file(s):")
        for path in supported:
            click.echo(f"  + {path}")
        for path in ignored:
            click.echo(f"  - (ignored) {path}")
        return

    scope = "global" if global_scope else "project"
    store = _open_bookstore(
        llm_spec=llm,
        scope_needed=scope,
        use_llm=not no_llm,
    )

    async def _run() -> list[dict]:
        results: list[dict] = []
        total = len(supported)
        any_succeeded = False
        for i, path in enumerate(supported, start=1):
            try:
                card, status = await store.add_book(path, scope=scope, force=force, relate=relate)
                results.append({"file": str(path), "status": status, "book_id": card.book_id})
                if status in ("added", "updated"):
                    any_succeeded = True
                click.echo(f"[{i}/{total}] {status}: {card.book_id}")
            except Exception as exc:  # noqa: BLE001 — keep the loop alive
                results.append({"file": str(path), "status": "failed", "error": str(exc)})
                click.echo(f"[{i}/{total}] FAILED: {path} — {exc}")
        if relate and any_succeeded:
            await store.relate_books(None, communities_only=True)
        return results

    results = asyncio.run(_run())
    counts: dict[str, int] = {}
    for entry in results:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    summary = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
    click.echo(f"Done — {summary}" + (f" (ignored: {len(ignored)})" if ignored else ""))
    failures = [e for e in results if e["status"] == "failed"]
    if failures and len(failures) == len(results):
        raise click.ClickException("every file failed to ingest")


@bookstore.command("list")
@click.option("--json", "as_json", is_flag=True, help="JSON output.")
@click.option("--by-community", is_flag=True, help="Group books by their community.")
@click.option("--notes", "show_notes", is_flag=True, help="List notebooks instead of books.")
def list_cmd(as_json: bool, by_community: bool, show_notes: bool) -> None:
    """List every book in the library (or, with ``--notes``, every notebook)."""
    store = _open_bookstore(require_exists=True, use_llm=False)
    if show_notes:
        notebooks = [
            (loc.scope, card) for loc in store.locations for card in store._catalog(loc.scope).list_cards(kind="notes")
        ]
        if as_json:
            click.echo(
                json.dumps(
                    [{**card.model_dump(mode="json"), "scope": scope} for scope, card in notebooks],
                    indent=2,
                )
            )
            return
        if not notebooks:
            click.echo("No notebooks yet — `bookstore notebook draft` or `bookstore add --import --as notes`.")
            return
        click.echo(f"{'tree_name':<32}{'scope':<10}notes_for")
        for scope, card in notebooks:
            click.echo(f"{_inline(card.tree_name):<32}{scope:<10}{_inline(card.notes_for) or '-'}")
        return
    cards = store.list_books()
    if by_community:
        cards = sorted(
            cards,
            key=lambda c: (c.community_label or "￿", c.title.lower()),
        )
    if as_json:
        click.echo(json.dumps([c.model_dump(mode="json") for c in cards], indent=2))
        return
    if not cards:
        click.echo("Library is empty — `bookstore add <file>` to start.")
        return
    if by_community:
        _unset = object()
        current_label: Any = _unset
        for card in cards:
            if card.community_label != current_label:
                current_label = card.community_label
                click.echo(f"\n=== {current_label or '(no community)'} ===")
            _echo_card(card)
        return
    for card in cards:
        _echo_card(card)


@bookstore.command("show")
@click.argument("book_id")
@click.option("--json", "as_json", is_flag=True, help="JSON output.")
def show(book_id: str, as_json: bool) -> None:
    """Show the full catalog card (ficha) of one book."""
    from .library import BookstoreError

    store = _open_bookstore(require_exists=True, use_llm=False)
    try:
        card = store.get_card(book_id)
    except BookstoreError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(card.model_dump_json(indent=2))
        return
    _echo_card(card)
    if card.toc_digest:
        click.echo("  toc:")
        for line in card.toc_digest.splitlines():
            click.echo(f"    {line}")


@bookstore.command("toc")
@click.argument("book_id")
def toc(book_id: str) -> None:
    """Print a book's table of contents with node ids."""
    from .library import BookstoreError

    store = _open_bookstore(require_exists=True, use_llm=False)
    try:
        data = store.get_toc(book_id)
    except BookstoreError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"{data['title']} — sections:")
    for entry in data["entries"]:
        pages = ""
        if entry["start_page"] is not None:
            pages = f"  (pp. {entry['start_page']}-{entry['end_page'] or entry['start_page']})"
        indent = "  " * entry["depth"]
        click.echo(f"{indent}{entry['node_id']}  {entry['title']}{pages}")


@bookstore.command("search")
@click.argument("query")
@click.option("--book", "book_id", default=None, help="Search inside one book.")
@click.option("--catalog-only", is_flag=True, help="Only search the catalog cards.")
@click.option(
    "--llm",
    default=None,
    help="LLM spec 'provider:model' for tree-walk search.",
)
def search(
    query: str,
    book_id: Optional[str],
    catalog_only: bool,
    llm: Optional[str],
) -> None:
    """Search the library — catalog cards, one book, or cross-book."""
    from .library import BookstoreError

    store = _open_bookstore(llm_spec=llm, require_exists=True, use_llm=not catalog_only)
    try:
        if catalog_only:
            result: Any = [c.brief() for c in store.catalog_search(query)]
        elif book_id:
            result = asyncio.run(store.search_book(book_id, query))
        else:
            result = asyncio.run(store.search(query))
    except BookstoreError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result, indent=2, default=str))


@bookstore.command("card")
@click.argument("book_id")
@click.option("--refresh", is_flag=True, help="Re-run carding on the tree.")
@click.option(
    "--llm",
    default=None,
    help="LLM spec 'provider:model' for carding.",
)
def card_cmd(book_id: str, refresh: bool, llm: Optional[str]) -> None:
    """Refresh a book's ficha (e.g. after configuring an LLM)."""
    from .library import BookstoreError

    if not refresh:
        raise click.ClickException("Nothing to do — pass --refresh")
    store = _open_bookstore(llm_spec=llm, require_exists=True)
    try:
        card = asyncio.run(store.refresh_card(book_id))
    except BookstoreError as exc:
        raise click.ClickException(str(exc)) from exc
    _echo_card(card)


@bookstore.command("update")
@click.argument("book_id")
@click.option("--title", default=None, help="New title.")
@click.option("--author", "authors", multiple=True, help="Replace the authors (repeatable).")
@click.option("--topic", "topics", multiple=True, help="Replace the topics (repeatable).")
@click.option("--summary", default=None, help="New summary.")
@click.option("--clear-authors", is_flag=True, help="Remove all authors.")
@click.option("--clear-topics", is_flag=True, help="Remove all topics.")
def update_cmd(
    book_id: str,
    title: Optional[str],
    authors: tuple[str, ...],
    topics: tuple[str, ...],
    summary: Optional[str],
    clear_authors: bool,
    clear_topics: bool,
) -> None:
    """Edit a book's ficha fields without re-indexing (marks the card as manual).

    ``--clear-authors`` / ``--clear-topics`` remove the whole list.
    """
    from .library import BookstoreError

    if clear_authors and authors:
        raise click.ClickException("--clear-authors cannot be combined with --author")
    if clear_topics and topics:
        raise click.ClickException("--clear-topics cannot be combined with --topic")
    if title is None and not authors and not topics and summary is None and not clear_authors and not clear_topics:
        raise click.ClickException(
            "Nothing to do — pass --title, --author, --topic, --summary, --clear-authors or --clear-topics"
        )
    store = _open_bookstore(require_exists=True, use_llm=False)
    try:
        card = store.update_card(
            book_id,
            title=title,
            authors=[] if clear_authors else (list(authors) or None),
            topics=[] if clear_topics else (list(topics) or None),
            summary=summary,
        )
    except BookstoreError as exc:
        raise click.ClickException(str(exc)) from exc
    _echo_card(card)


@bookstore.command("related")
@click.argument("book_id")
@click.option("--rel", default=None, help="Filter to one relation kind.")
@click.option("--depth", default=1, type=int, help="Hops to walk (1 or 2).")
@click.option("--json", "as_json", is_flag=True, help="JSON output.")
def related(book_id: str, rel: Optional[str], depth: int, as_json: bool) -> None:
    """List books related to BOOK_ID (deterministic/LLM/community edges)."""
    from .library import BookstoreError

    store = _open_bookstore(require_exists=True, use_llm=False)
    try:
        results = store.related_books(book_id, rel=rel, depth=depth)
    except BookstoreError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(results, indent=2, default=str))
        return
    if not results:
        click.echo("No related books found.")
        return
    click.echo(f"{'rel':<16}{'book':<20}{'title':<30}{'origin':<14}{'weight':<8}confidence")
    for item in results:
        confidence = item["confidence"]
        click.echo(
            f"{item['rel']:<16}{item['book']['book_id']:<20}"
            f"{item['book']['title'][:28]:<30}{item['origin']:<14}"
            f"{item['weight']:<8.2f}"
            f"{'' if confidence is None else f'{confidence:.2f}'}"
        )


@bookstore.command("relate")
@click.argument("book_ids", nargs=-1)
@click.option("--all", "relate_all", is_flag=True, help="Relate every visible book.")
@click.option("--no-llm", is_flag=True, help="Deterministic relations only (Stage 1).")
@click.option("--communities-only", is_flag=True, help="Skip Stages 1-2, only compute communities.")
@click.option("--force", is_flag=True, help="Re-judge pairs already logged.")
@click.option("--resolution", default=1.0, type=float, help="Community detection resolution.")
@click.option(
    "--llm",
    default=None,
    help="LLM spec 'provider:model' for Stage 2 (default: $PARROT_BOOKSTORE_LLM).",
)
@click.option("--from-notes", is_flag=True, help="Turn notebook relation sheets into manual edges.")
def relate(
    book_ids: tuple[str, ...],
    relate_all: bool,
    no_llm: bool,
    communities_only: bool,
    force: bool,
    resolution: float,
    llm: Optional[str],
    from_notes: bool,
) -> None:
    """Compute deterministic + LLM relations for BOOK_IDS (or --all).

    ``--from-notes`` first turns notebook relation sheets into ``manual``
    edges; it can run alone or before the normal stages.
    """
    from .library import BookstoreError

    run_stages = relate_all or bool(book_ids)
    if not run_stages and not from_notes:
        raise click.ClickException("Pass --all or at least one BOOK_ID")

    store = _open_bookstore(llm_spec=llm, require_exists=True, use_llm=run_stages and not no_llm)
    if from_notes:
        from .notebooks import apply_relation_sheets

        try:
            written = asyncio.run(apply_relation_sheets(store))
        except BookstoreError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(f"notebook relation edges: {written}")
        if not run_stages:
            return
    try:
        summary = asyncio.run(
            store.relate_books(
                None if relate_all else list(book_ids),
                use_llm=not no_llm,
                communities_only=communities_only,
                force=force,
                resolution=resolution,
            )
        )
    except BookstoreError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"targets: {len(summary.targets)}")
    click.echo(f"deterministic edges: {summary.deterministic_edges}")
    click.echo(f"LLM prompts: {summary.llm_prompts}  LLM edges: {summary.llm_edges}")
    if summary.skipped_llm_reason:
        click.echo(f"LLM skipped: {summary.skipped_llm_reason}")
    if summary.failed:
        click.echo(f"failed: {len(summary.failed)}")
        for book_id, error in summary.failed.items():
            click.echo(f"  {book_id}: {error}")
    for note in summary.notes:
        click.echo(f"note: {note}")


@bookstore.command("communities")
@click.option("--json", "as_json", is_flag=True, help="JSON output.")
def communities_cmd(as_json: bool) -> None:
    """List every detected community (run `bookstore relate` first)."""
    store = _open_bookstore(require_exists=True, use_llm=False)
    result = store.communities()
    if as_json:
        click.echo(json.dumps([c.model_dump(mode="json") for c in result], indent=2))
        return
    if not result:
        click.echo("No communities yet — run `bookstore relate --all` first.")
        return
    click.echo(f"{'id':<18}{'label':<30}{'algorithm':<12}{'size':<6}cohesion")
    for community in result:
        click.echo(
            f"{community.community_id:<18}{community.label[:28]:<30}"
            f"{community.algorithm:<12}{community.size:<6}{community.cohesion:.2f}"
        )


@bookstore.command("export-wiki")
@click.option(
    "--out",
    "out_dir",
    default=None,
    help="Output directory (default: <library>/wiki).",
)
@click.option(
    "--global",
    "global_scope",
    is_flag=True,
    help="Export the global library instead of the project one.",
)
@click.option(
    "--no-register",
    is_flag=True,
    help="Skip wikitoolkit namespace registration.",
)
def export_wiki(out_dir: Optional[str], global_scope: bool, no_register: bool) -> None:
    """Project the book graph into a wikitoolkit plane (CLI-only)."""
    from .library import BookstoreError

    # Anchor a relative --out to the invocation directory NOW — the
    # heavy imports below chdir() the process (see _INVOCATION_CWD),
    # same guard as `add`/`add-folder`'s FILE/FOLDER arguments.
    resolved_out = (Path(_INVOCATION_CWD) / out_dir).resolve() if out_dir else None

    scope = "global" if global_scope else "project"
    store = _open_bookstore(require_exists=True, use_llm=False, scope_needed=scope)
    try:
        result = asyncio.run(
            store.export_wiki(
                resolved_out,
                scope=scope,
                register=not no_register,
            )
        )
    except BookstoreError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"pages: {result['pages']}  edges: {result['edges']}")
    click.echo(f"graph: {result['html']}")
    if result.get("registered_in"):
        click.echo(f"registered namespace 'bookstore' in {result['registered_in']}")
    else:
        click.echo("namespace registration skipped")


@bookstore.command("optimize")
@click.argument("book_id")
@click.option("--global", "global_scope", is_flag=True, help="Use the global library.")
@click.option("--apply", is_flag=True, help="Publish the optimized tree and rebuild the card TOC.")
@click.option("--no-llm", is_flag=True, help="Skip model-backed optimizer passes.")
@click.option(
    "--llm",
    default=None,
    help="LLM spec 'provider:model' (default: $PARROT_BOOKSTORE_LLM).",
)
@click.option("--json", "as_json", is_flag=True, help="JSON output.")
def optimize_cmd(
    book_id: str,
    global_scope: bool,
    apply: bool,
    no_llm: bool,
    llm: Optional[str],
    as_json: bool,
) -> None:
    """Optimize a book's PageIndex tree; dry-run unless ``--apply`` is passed."""
    from .library import BookstoreError

    scope = "global" if global_scope else "project"
    store = _open_bookstore(
        llm_spec=llm,
        scope_needed=scope,
        use_llm=not no_llm,
    )
    try:
        report = asyncio.run(
            store.optimize_book(
                book_id,
                apply=apply,
                llm_passes=False if no_llm else None,
            )
        )
    except BookstoreError as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        click.echo(json.dumps(report, indent=2, default=str))
        return
    mode = "applied" if apply else "dry-run"
    click.echo(f"{mode}: {book_id}")
    click.echo(
        f"nodes: {report.get('nodes_before', 0)} -> {report.get('nodes_after', 0)}; "
        f"merged: {len(report.get('merged', []))}; expanded: {len(report.get('expanded', []))}"
    )
    click.echo(f"llm: {report.get('llm_passes', 'unknown')}")
    for error in report.get("errors", []):
        click.echo(f"error: {error}", err=True)


def _inline(value: Any) -> str:
    """Collapse a provider-supplied value to one printable line."""
    text = "" if value is None else str(value)
    return " ".join("".join(ch if ch.isprintable() else " " for ch in text).split())


def _safe_text(value: Any) -> str:
    """Neutralise terminal control sequences in book- or model-derived text, keeping newlines and tabs."""
    text = "" if value is None else str(value)
    return "".join(ch if ch in "\n\t" or ch.isprintable() else " " for ch in text)


def _echo_identity(store: Any) -> None:
    """Report the resolved provider/model on stderr (never stdout)."""
    adapter = getattr(store, "adapter", None)
    if adapter is None:
        return
    client = getattr(adapter, "client", None)
    provider = getattr(client, "client_name", None) or type(client).__name__
    model = getattr(adapter, "model", None)
    line = f"model: {_inline(provider)}:{_inline(model)}"
    light = getattr(store, "lightweight_model", None)
    if light:
        line += f" (light: {_inline(light)})"
    click.echo(line, err=True)


@bookstore.command("ask")
@click.argument("book_id")
@click.argument("query")
@click.option(
    "--llm",
    default=None,
    help="LLM spec 'provider:model' (default: $PARROT_BOOKSTORE_LLM).",
)
@click.option("--budget-chars", type=int, default=None, help="Maximum characters read from the book.")
@click.option("--max-reads", type=int, default=None, help="Maximum read operations.")
@click.option("--timeout", "timeout_s", type=float, default=None, help="Total timeout in seconds.")
@click.option("--json", "as_json", is_flag=True, help="JSON output (the full evidence bundle).")
def ask_cmd(
    book_id: str,
    query: str,
    llm: Optional[str],
    budget_chars: Optional[int],
    max_reads: Optional[int],
    timeout_s: Optional[float],
    as_json: bool,
) -> None:
    """Research one book with cited evidence."""
    from .library import BookstoreError

    store = _open_bookstore(llm_spec=llm, require_exists=True)
    if getattr(store, "adapter", None) is None:
        raise click.ClickException(
            "agentic retrieval requires an LLM — pass --llm provider:model or set PARROT_BOOKSTORE_LLM"
        )
    _echo_identity(store)
    try:
        bundle = asyncio.run(
            store.agentic_retrieve(
                book_id,
                query,
                draft_answer=True,
                budget_chars=budget_chars,
                max_reads=max_reads,
                timeout_s=timeout_s,
            )
        )
    except (BookstoreError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        click.echo(json.dumps(bundle, indent=2, default=str))
        return
    answer = bundle.get("answer")
    click.echo(_safe_text(answer) if answer else "(no answer drafted)")
    rendered = bundle.get("rendered_citations")
    if rendered:
        click.echo(f"\ncitations: {_safe_text(rendered)}")
    else:
        click.echo("\ncitations: (none)")
    click.echo(
        f"grounded: {bundle.get('grounded')}  stopped: {bundle.get('stopped')}  "
        f"chars_read: {bundle.get('chars_read')}"
    )


@bookstore.command("doctor")
@click.option("--global", "global_scope", is_flag=True, help="Examine the global library instead of the project one.")
@click.option("--repair", is_flag=True, help="Repair drifted catalog cards from their live trees.")
@click.option("--relate", is_flag=True, help="Build relations for books with no judgements.")
@click.option("--no-llm", is_flag=True, help="Deterministic relations only (with --relate).")
@click.option(
    "--llm",
    default=None,
    help="LLM spec 'provider:model' for --relate (default: $PARROT_BOOKSTORE_LLM).",
)
@click.option("--json", "as_json", is_flag=True, help="JSON output (the full report).")
@click.option("--notes", "check_notes", is_flag=True, help="Also check notebooks and anchors.")
def doctor_cmd(
    global_scope: bool,
    repair: bool,
    relate: bool,
    no_llm: bool,
    llm: Optional[str],
    as_json: bool,
    check_notes: bool,
) -> None:
    """Report recovery and drift, optionally repair cards and build missing judgements."""
    from .library import BookstoreError

    scope = "global" if global_scope else "project"
    use_llm = relate and not no_llm
    store = _open_bookstore(
        llm_spec=llm,
        require_exists=True,
        scope_needed=scope,
        use_llm=use_llm,
    )
    if use_llm:
        _echo_identity(store)
    try:
        # ``notes`` is passed only when requested so the default call is unchanged.
        extra: dict[str, Any] = {"notes": True} if check_notes else {}
        report = asyncio.run(store.doctor(scope=scope, repair=repair, relate=relate, use_llm=not no_llm, **extra))
    except (BookstoreError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        click.echo(json.dumps(report, indent=2, default=str))
        return
    click.echo(f"scope: {scope}")
    reserved = report.get("reserved", [])
    click.echo(f"reserved trees: {len(reserved)}")
    for entry in reserved:
        click.echo(f"  {_inline(entry.get('action'))}: {_inline(entry.get('name'))} ({_inline(entry.get('reason'))})")
    books = report.get("books", [])
    problems = [entry for entry in books if entry.get("status") != "ok"]
    repaired = sum(1 for entry in books if entry.get("repaired"))
    click.echo(f"books: {len(books)}  issues: {len(problems)}  repaired: {repaired}")
    for entry in problems:
        suffix = " (repaired)" if entry.get("repaired") else ""
        click.echo(f"  {_inline(entry.get('status'))}: {_inline(entry.get('book_id'))}{suffix}")
    unjudged = report.get("unjudged_book_ids", [])
    click.echo(f"unjudged books: {len(unjudged)}")
    summary = report.get("relate_summary")
    if summary:
        click.echo(
            f"relate: targets {len(summary.get('targets', []))}, "
            f"deterministic edges {summary.get('deterministic_edges', 0)}, "
            f"LLM edges {summary.get('llm_edges', 0)}"
        )
        if summary.get("skipped_llm_reason"):
            click.echo(f"  LLM skipped: {summary['skipped_llm_reason']}")
    if check_notes:
        for notes_scope, notes in (report.get("notes") or {}).items():
            click.echo(
                f"notes ({_inline(notes_scope)}): notebooks {notes.get('notebooks', 0)}, "
                f"orphans {len(notes.get('orphans', []))}, "
                f"malformed anchors {len(notes.get('malformed_anchors', []))}, "
                f"stale anchors {notes.get('stale_anchors', 0)}, "
                f"broken bindings {len(notes.get('broken_bindings', []))}"
            )
            for orphan in notes.get("orphans", []):
                click.echo(f"  orphan: {_inline(orphan)}")
            for entry in notes.get("broken_bindings", []):
                click.echo(f"  broken: {_inline(entry.get('book_id'))} ({_inline(entry.get('reason'))})")
    for error in report.get("errors", []):
        target = error.get("book_id") or error.get("name") or error.get("scope") or "-"
        click.echo(f"error: {_inline(target)}: {_inline(error.get('error'))}", err=True)


@bookstore.command("remove")
@click.argument("book_id")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--with-notes", is_flag=True, help="Also delete the book's notebook.")
def remove(book_id: str, yes: bool, with_notes: bool) -> None:
    """Remove a book (catalog card + indexed tree; ``--with-notes`` also its notebook)."""
    from .library import BookstoreError

    store = _open_bookstore(require_exists=True, use_llm=False)
    try:
        card = store.get_card(book_id)
    except BookstoreError as exc:
        raise click.ClickException(str(exc)) from exc
    if not yes:
        extra = " and notebook" if with_notes else ""
        click.confirm(f"Remove {card.title!r} ({card.scope}) and its index{extra}?", abort=True)
    try:
        removed = asyncio.run(store.remove_book(book_id, with_notes=with_notes))
    except BookstoreError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("removed" if removed else "nothing removed")


@bookstore.group("notebook")
def notebook() -> None:
    """Notebooks: per-book notes and the library's sector index."""


@notebook.command("draft")
@click.option("--library", "library", is_flag=True, help="Draft sectors into the library notebook.")
@click.option("--book", "book_id", default=None, help="Draft a reading-guide skeleton for one book.")
@click.option("--global", "global_scope", is_flag=True, help="Target the global library (with --library).")
@click.option("--no-llm", is_flag=True, help="Communities map 1:1 to sectors; no model calls.")
@click.option("--json", "as_json", is_flag=True, help="JSON output.")
def notebook_draft(library: bool, book_id: Optional[str], global_scope: bool, no_llm: bool, as_json: bool) -> None:
    """Propose notebook structure (drafts never overwrite your own notes)."""
    if library == (book_id is not None):
        raise click.UsageError("Pass exactly one of --library or --book <id>")
    if global_scope and not library:
        raise click.UsageError("--global only applies to --library")

    from .library import BookstoreError
    from .notebooks import draft_book_notebook, draft_library_notebook

    scope = "global" if global_scope else "project"
    store = _open_bookstore(
        require_exists=True,
        scope_needed=scope if library else None,
        use_llm=library and not no_llm,
    )
    try:
        if library:
            counts = asyncio.run(draft_library_notebook(store, scope, use_llm=not no_llm))
        else:
            counts = asyncio.run(draft_book_notebook(store, book_id))
    except BookstoreError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(counts, indent=2))
        return
    target = f"library notebook ({scope})" if library else f"notebook of {book_id}"
    click.echo(
        f"{target}: created {counts.get('created', 0)}, updated {counts.get('updated', 0)}, "
        f"skipped (human) {counts.get('skipped_human', 0)}"
    )


@bookstore.command("mcp")
def mcp() -> None:
    """Start the bookstore as a local MCP stdio server.

    Exposes the ten read-only bookstore_* tools (catalog search, ToC,
    in-book hybrid search, section read, cross-book search, related
    books, communities) over JSON-RPC on stdin/stdout for Claude Code
    and other MCP clients.
    """
    from .mcp_server import main as mcp_main

    mcp_main()


@bookstore.command("locations")
def locations_cmd() -> None:
    """Show the resolved library locations and their state."""
    for loc in resolve_locations(cwd=Path(_INVOCATION_CWD)):
        state = "initialized" if loc.exists() else "empty"
        click.echo(f"{loc.scope:8} {loc.root}  [{state}]")


def main() -> None:
    """Console-script entry point for ``bookstore``."""
    bookstore()


if __name__ == "__main__":
    main()
