"""``bookstore`` CLI — manage the personal indexed library.

Subcommands: ``add`` / ``list`` / ``show`` / ``search`` / ``toc`` /
``card`` / ``remove`` / ``mcp``. Heavy parrot imports are deferred into
command bodies (the ``wiki/cli.py`` discipline) so ``bookstore --help``
stays fast and the ``mcp`` path keeps stdout clean.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
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

    locations = resolve_locations(
        cwd=Path(_INVOCATION_CWD), require_exists=require_exists
    )
    if scope_needed and not any(
        loc.scope == scope_needed for loc in locations
    ):
        hint = (
            " — not inside a git repository; cd into your project, set "
            "PARROT_LIBRARY_DIR, or use --global"
            if scope_needed == "project"
            else ""
        )
        raise click.ClickException(
            f"No {scope_needed} library location available{hint}"
        )
    if not locations:
        raise click.ClickException(
            "No library found — add a book first with `bookstore add <file>`"
        )
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


@click.group(name="bookstore")
def bookstore() -> None:
    """Personal indexed library (biblioteca) over PageIndex trees."""


@bookstore.command("add")
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--global", "global_scope", is_flag=True, help="Add to ~/.parrot/library."
)
@click.option("--title", default=None, help="Override the book title.")
@click.option("--author", "authors", multiple=True, help="Override authors.")
@click.option("--topic", "topics", multiple=True, help="Override topics.")
@click.option("--force", is_flag=True, help="Re-index even if already added.")
@click.option("--no-llm", is_flag=True, help="Skip LLM carding/summaries.")
@click.option(
    "--llm",
    default=None,
    help="LLM spec 'provider:model' (default: $PARROT_BOOKSTORE_LLM).",
)
def add(
    file: str,
    global_scope: bool,
    title: Optional[str],
    authors: tuple[str, ...],
    topics: tuple[str, ...],
    force: bool,
    no_llm: bool,
    llm: Optional[str],
) -> None:
    """Index FILE (pdf/md/txt/epub) and catalog its ficha."""
    # Anchor a relative FILE to the invocation directory NOW — the heavy
    # imports below chdir() the process (see _INVOCATION_CWD).
    file = str((Path(_INVOCATION_CWD) / file).resolve())

    from .library import BookstoreError

    scope = "global" if global_scope else "project"
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
            )
        )
    except BookstoreError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"{status}: {card.book_id} ({card.chapter_count} chapters)")
    _echo_card(card)


@bookstore.command("add-folder")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("--recursive", "-r", is_flag=True, help="Descend into subdirectories.")
@click.option(
    "--global", "global_scope", is_flag=True, help="Add to ~/.parrot/library."
)
@click.option("--force", is_flag=True, help="Re-index files already added.")
@click.option("--no-llm", is_flag=True, help="Skip LLM carding/summaries.")
@click.option(
    "--llm",
    default=None,
    help="LLM spec 'provider:model' (default: $PARROT_BOOKSTORE_LLM).",
)
@click.option(
    "--dry-run", is_flag=True, help="List what would be indexed, change nothing."
)
def add_folder(
    folder: str,
    recursive: bool,
    global_scope: bool,
    force: bool,
    no_llm: bool,
    llm: Optional[str],
    dry_run: bool,
) -> None:
    """Index every supported file (pdf/md/txt/epub/docx) in FOLDER.

    Files are processed sequentially; a failing file is reported and the
    loop continues with the next one.
    """
    # Anchor a relative FOLDER to the invocation directory NOW — the
    # heavy imports below chdir() the process (see _INVOCATION_CWD).
    folder = str((Path(_INVOCATION_CWD) / folder).resolve())

    from .library import Bookstore, BookstoreError

    try:
        supported, ignored = Bookstore.iter_folder_files(
            folder, recursive=recursive
        )
    except BookstoreError as exc:
        raise click.ClickException(str(exc)) from exc
    if not supported:
        click.echo("No ingestable files found (pdf/md/txt/epub/docx).")
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
        for i, path in enumerate(supported, start=1):
            try:
                card, status = await store.add_book(
                    path, scope=scope, force=force
                )
                results.append(
                    {"file": str(path), "status": status, "book_id": card.book_id}
                )
                click.echo(f"[{i}/{total}] {status}: {card.book_id}")
            except Exception as exc:  # noqa: BLE001 — keep the loop alive
                results.append(
                    {"file": str(path), "status": "failed", "error": str(exc)}
                )
                click.echo(f"[{i}/{total}] FAILED: {path} — {exc}")
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
def list_cmd(as_json: bool) -> None:
    """List every book in the library."""
    store = _open_bookstore(require_exists=True, use_llm=False)
    cards = store.list_books()
    if as_json:
        click.echo(json.dumps([c.model_dump(mode="json") for c in cards], indent=2))
        return
    if not cards:
        click.echo("Library is empty — `bookstore add <file>` to start.")
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
@click.option(
    "--catalog-only", is_flag=True, help="Only search the catalog cards."
)
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

    store = _open_bookstore(
        llm_spec=llm, require_exists=True, use_llm=not catalog_only
    )
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


@bookstore.command("remove")
@click.argument("book_id")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
def remove(book_id: str, yes: bool) -> None:
    """Remove a book (catalog card + indexed tree)."""
    from .library import BookstoreError

    store = _open_bookstore(require_exists=True, use_llm=False)
    try:
        card = store.get_card(book_id)
    except BookstoreError as exc:
        raise click.ClickException(str(exc)) from exc
    if not yes:
        click.confirm(
            f"Remove {card.title!r} ({card.scope}) and its index?", abort=True
        )
    removed = asyncio.run(store.remove_book(book_id))
    click.echo("removed" if removed else "nothing removed")


@bookstore.command("mcp")
def mcp() -> None:
    """Start the bookstore as a local MCP stdio server.

    Exposes the seven read-only bookstore_* tools (catalog search, ToC,
    in-book hybrid search, section read, cross-book search) over
    JSON-RPC on stdin/stdout for Claude Code and other MCP clients.
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
