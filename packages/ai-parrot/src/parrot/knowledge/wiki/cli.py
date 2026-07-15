"""``wikitoolkit`` — machine-first CLI over the LLM Wiki retrieval plane.

Gives agents (and humans) scoped, token-budgeted access to a codebase
knowledge base built from the current repository — fully offline: the
build path is deterministic (:mod:`parrot.knowledge.wiki.repo_scan`)
and queries run on the SQLite FTS5/BM25 plane (FEAT-260).

Exposed two ways:

- ``wikitoolkit <command>`` — standalone console script, so coding
  assistants can run ``wikitoolkit query "<question>"`` cheaply;
- ``parrot wiki <command>`` — subcommand of the main parrot CLI.

Commands:
    build    Generate/refresh the KB graph from the repository.
    upsert   Incrementally re-ingest specific/changed files.
    query    Scoped question → token-budgeted context pack.
    page     Read one wiki page (progressive disclosure).
    related  Follow typed edges from a page.
    status   Plane statistics + staleness report.
    export   Export the wiki as a human-readable markdown bundle.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path, PurePosixPath
import subprocess
from typing import Any, Optional

import click

from parrot.knowledge.wiki.context import (
    DEFAULT_BUDGET_TOKENS,
    pack_results,
    truncate_to_tokens,
)
from parrot.knowledge.wiki.project import (
    WikiConfigError,
    WikiProjectConfig,
    find_project_root,
    load_project_config,
    save_project_config,
)
from parrot.knowledge.wiki.repo_scan import (
    is_wiki_relevant,
    scan_repository,
)
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import BaseWikiStore, create_wiki_store


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

#: Shared `--path` option — every command resolves the repo root the same way.
path_option = click.option(
    "--path", "path_", default=None, help="Repo root (default: auto-detect)."
)

def _resolve_project(path: Optional[str]) -> tuple[Path, WikiProjectConfig]:
    """Resolve the repo root + config, aborting with guidance if absent."""
    if path:
        root = Path(path).resolve()
        if not root.is_dir():
            raise click.ClickException(f"Not a directory: {root}")
    else:
        found = find_project_root()
        if found is None:
            raise click.ClickException(
                "No wiki project found (no .parrot/wiki.json or .git "
                "upwards from here). Run inside a repository or pass "
                "--path."
            )
        root = found
    try:
        return root, load_project_config(root)
    except WikiConfigError as exc:
        raise click.ClickException(str(exc)) from exc


def _require_built(root: Path, config: WikiProjectConfig) -> BaseWikiStore:
    """Open the store, aborting when the wiki was never built."""
    if not config.is_built(root):
        raise click.ClickException(
            f"Wiki not built yet for {root}. "
            "Run `wikitoolkit build` first."
        )
    return _open_store(root, config)


def _open_store(root: Path, config: WikiProjectConfig) -> BaseWikiStore:
    """Create the retrieval-plane store for a repo."""
    storage = config.storage_path(root)
    storage.mkdir(parents=True, exist_ok=True)
    return create_wiki_store(
        storage, wiki_name=config.wiki_name, backend=config.backend
    )


def _open_sources(root: Path, config: WikiProjectConfig) -> SourceCollectionManager:
    """Create the source manifest manager matching the store backend."""
    storage = config.storage_path(root)
    if config.backend == "sqlite":
        return SourceCollectionManager(
            storage / "sources", db_path=storage / "wiki.db"
        )
    return SourceCollectionManager(storage / "sources", backend="json")


def _normalize_scores(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Min-max normalise raw FTS scores into [0, 1] for packing."""
    if not rows:
        return rows
    scores = [float(r.get("score", 0.0)) for r in rows]
    lo, hi = min(scores), max(scores)
    span = hi - lo
    for row, score in zip(rows, scores):
        row["score"] = 1.0 if span <= 0 else (score - lo) / span
    return rows


def _run(coro: Any) -> Any:
    """Run an async store operation from a sync click command."""
    return asyncio.run(coro)


# --------------------------------------------------------------------------
# Build / upsert pipeline
# --------------------------------------------------------------------------


async def _ingest_files(
    store: BaseWikiStore,
    sources: SourceCollectionManager,
    root: Path,
    scan: Any,
    force: bool = False,
) -> dict[str, int]:
    """Ingest scanned file slices into the plane (incremental).

    Unchanged files (same hash + mtime as the manifest) are skipped
    unless ``force`` is set; changed/new files replace their previous
    slice atomically so re-builds never accumulate duplicates (and
    ``replace_source_slice`` preserves incoming edges to stable
    concept ids). On a fresh, empty plane the per-slice path is
    skipped in favour of one bulk ``upsert_pages``/``add_edges`` write.

    Sync manifest I/O (hashing, SQLite writes) is offloaded via
    ``asyncio.to_thread`` so the event loop is never blocked.
    """
    written = 0
    unchanged = 0
    edges_by_src: dict[str, list[tuple[str, str, str]]] = {}
    for edge in scan.import_edges:
        edges_by_src.setdefault(edge[0], []).append(edge)

    stats = await store.stats()
    fresh = int(stats.get("pages", 0)) == 0
    bulk_records = []
    bulk_edges: list[tuple[str, str, str]] = []

    for fs in scan.files:
        abs_path = root / fs.rel_path
        uri = str(abs_path.resolve())
        source_id = await asyncio.to_thread(sources.find_by_uri, uri)
        if source_id is None:
            entry = await asyncio.to_thread(sources.add_source, abs_path)
            source_id = entry.source_id
        elif not force and not await asyncio.to_thread(
            sources.is_stale, source_id
        ):
            unchanged += 1
            continue
        fs.record.source_id = source_id
        slice_edges = edges_by_src.get(fs.record.concept_id, [])
        if fresh:
            bulk_records.append(fs.record)
            bulk_edges.extend(slice_edges)
        else:
            await store.replace_source_slice(
                source_id, [fs.record], slice_edges
            )
        await asyncio.to_thread(
            sources.mark_ingested, source_id, [fs.record.concept_id]
        )
        written += 1

    if bulk_records:
        await store.upsert_pages(bulk_records)
    if bulk_edges:
        await store.add_edges(bulk_edges)
    return {"written": written, "unchanged": unchanged}


async def _prune_removed(
    store: BaseWikiStore,
    sources: SourceCollectionManager,
    root: Path,
    scan: Any,
) -> int:
    """Drop pages/sources no longer in scan scope (full builds only).

    Covers deleted files as well as files that fell out of scope
    (newly ignored directories, changed suffix filters).
    """
    expected_files = {fs.record.concept_id for fs in scan.files}
    expected_dirs = {r.concept_id for r in scan.dir_records}
    expected_uris = {
        str((root / fs.rel_path).resolve()) for fs in scan.files
    }
    removed = 0

    for entry in await asyncio.to_thread(sources.list_sources):
        if entry.source_uri not in expected_uris:
            await store.replace_source_slice(entry.source_id, [], [])
            await asyncio.to_thread(sources.remove_source, entry.source_id)
            removed += 1

    stubs = await store.list_pages(limit=1_000_000)
    for stub in stubs:
        cid = str(stub.get("concept_id", ""))
        if cid.startswith("file:") and cid not in expected_files:
            if await store.delete_page(cid):
                removed += 1
        elif cid.startswith("dir:") and cid not in expected_dirs:
            if await store.delete_page(cid):
                removed += 1
    return removed


# --------------------------------------------------------------------------
# CLI group
# --------------------------------------------------------------------------


@click.group(name="wiki")
def wiki() -> None:
    """LLM Wiki — codebase knowledge base for agents (FEAT-260).

    Build a machine-first knowledge graph of the current repository
    and query it with scoped, token-budgeted questions instead of
    grepping raw files.
    """


@wiki.command()
@path_option
@click.option("--name", default=None, help="Wiki name (default: repo directory name).")
@click.option(
    "--backend",
    type=click.Choice(["sqlite", "memory"]),
    default=None,
    help="Retrieval-plane backend (default: sqlite).",
)
@click.option("--force", is_flag=True, help="Re-ingest every file, ignoring staleness.")
@click.option("--no-git", is_flag=True, help="Do not use git for file discovery.")
@click.option("--quiet", "-q", is_flag=True, help="Only print the final summary line.")
def build(
    path_: Optional[str],
    name: Optional[str],
    backend: Optional[str],
    force: bool,
    no_git: bool,
    quiet: bool,
) -> None:
    """Generate (or refresh) the KB graph from the current repository.

    Deterministic and offline: scans source files (respecting
    .gitignore), extracts summaries/API outlines, and writes pages +
    typed edges into the wiki retrieval plane under .parrot/wiki.
    """
    root, config = _resolve_project(path_)
    if name:
        config.wiki_name = name
    if backend:
        config.backend = backend  # type: ignore[assignment]

    if not quiet:
        click.echo(f"Scanning {root} ...")
    scan = scan_repository(
        root,
        suffixes=config.include_suffixes or None,
        exclude_dirs=config.exclude_dirs,
        body_max_chars=config.body_max_chars,
        max_file_bytes=config.max_file_kb * 1024,
        use_git=not no_git,
    )

    async def _pipeline() -> dict[str, Any]:
        store = _open_store(root, config)
        sources = _open_sources(root, config)
        counts = await _ingest_files(store, sources, root, scan, force=force)
        await store.upsert_pages(scan.dir_records)
        await store.add_edges(scan.dir_edges)
        counts["removed"] = await _prune_removed(store, sources, root, scan)
        counts["stats"] = await store.stats()
        return counts

    counts = _run(_pipeline())
    save_project_config(root, config)

    stats = counts["stats"]
    click.echo(
        f"Wiki '{config.wiki_name}' built at "
        f"{config.storage_path(root)} — "
        f"{counts['written']} ingested, {counts['unchanged']} unchanged, "
        f"{counts['removed']} removed; "
        f"{stats.get('pages', 0)} pages, {stats.get('edges', 0)} edges."
    )
    if scan.skipped and not quiet:
        click.echo(f"Skipped {len(scan.skipped)} binary/oversized files.")


def _changed_files_from_git(root: Path) -> list[str]:
    """Relative paths touched by the last commit (post-commit hook).

    Uses ``-z`` so paths with spaces/unicode are not C-quoted,
    ``--root`` so the very first commit of a repository also reports
    its files, and ``-m --first-parent`` so **merge commits** report the
    files they bring in relative to the first parent. Without the latter,
    a plain ``diff-tree HEAD`` emits the (usually empty) combined diff for
    a merge, so every file a ``git merge`` introduces would silently stay
    stale in the wiki until the next full ``wikitoolkit build``.
    """
    try:
        proc = subprocess.run(
            [
                "git", "-C", str(root), "diff-tree", "--no-commit-id",
                "--name-only", "-z", "-r", "-m", "--first-parent",
                "--root", "HEAD",
            ],
            capture_output=True,
            timeout=30,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    out = proc.stdout.decode("utf-8", errors="replace")
    # `-m` can repeat a path across parent sections; dedupe while
    # preserving first-seen order.
    seen: set[str] = set()
    result: list[str] = []
    for p in out.split("\0"):
        if p and p not in seen:
            seen.add(p)
            result.append(p)
    return result


@wiki.command()
@click.argument("paths", nargs=-1)
@path_option
@click.option(
    "--changed",
    is_flag=True,
    help="Upsert the files touched by the last git commit.",
)
@click.option("--quiet", "-q", is_flag=True, help="Suppress output (for git hooks).")
def upsert(
    paths: tuple[str, ...],
    path_: Optional[str],
    changed: bool,
    quiet: bool,
) -> None:
    """Incrementally re-ingest specific files (or last-commit changes).

    Used by the git post-commit hook installed via
    `parrot claude install` to keep the wiki fresh. Deleted files have
    their pages removed. Directory overview pages are refreshed by the
    next full `wikitoolkit build`.
    """
    root, config = _resolve_project(path_)
    if not config.is_built(root):
        if not quiet:
            click.echo("Wiki not built yet — run `wikitoolkit build` first.")
        return

    rel_paths = list(paths)
    if changed:
        rel_paths.extend(_changed_files_from_git(root))
    if not rel_paths:
        if not quiet:
            click.echo("Nothing to upsert (no paths given).")
        return

    normalized: list[str] = []
    for rel in rel_paths:
        p = Path(rel)
        if p.is_absolute():
            try:
                rel = p.resolve().relative_to(root).as_posix()
            except ValueError:
                continue
        rel = PurePosixPath(rel).as_posix()
        # Same selection filter as full discovery — the two paths must
        # never disagree about what belongs in the wiki.
        if is_wiki_relevant(
            rel,
            suffixes=config.include_suffixes or None,
            exclude_dirs=config.exclude_dirs,
        ):
            normalized.append(rel)

    existing = [rel for rel in normalized if (root / rel).is_file()]
    deleted = [rel for rel in normalized if not (root / rel).is_file()]
    if not existing and not deleted:
        if not quiet:
            click.echo("No wiki-relevant files in the given set.")
        return

    scan = scan_repository(
        root,
        suffixes=config.include_suffixes or None,
        exclude_dirs=config.exclude_dirs,
        body_max_chars=config.body_max_chars,
        max_file_bytes=config.max_file_kb * 1024,
        rel_paths=existing,
    )

    async def _pipeline() -> dict[str, int]:
        store = _open_store(root, config)
        sources = _open_sources(root, config)
        counts = await _ingest_files(store, sources, root, scan, force=True)
        removed = 0
        for rel in deleted:
            uri = str((root / rel).resolve())
            source_id = await asyncio.to_thread(sources.find_by_uri, uri)
            if source_id:
                await store.replace_source_slice(source_id, [], [])
                await asyncio.to_thread(sources.remove_source, source_id)
                removed += 1
        counts["removed"] = removed
        return counts

    counts = _run(_pipeline())
    if not quiet:
        click.echo(
            f"Upserted {counts['written']} page(s), "
            f"removed {counts['removed']}."
        )


@wiki.command()
@click.argument("question")
@path_option
@click.option("--top-k", default=12, show_default=True, help="Max results to rank.")
@click.option(
    "--budget",
    default=DEFAULT_BUDGET_TOKENS,
    show_default=True,
    help="Token budget for the packed context.",
)
@click.option("--category", default=None, help="Filter by page category.")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON results.")
def query(
    question: str,
    path_: Optional[str],
    top_k: int,
    budget: int,
    category: Optional[str],
    as_json: bool,
) -> None:
    """Scoped question against the codebase KB (lexical BM25 search).

    Returns a token-budgeted context pack of page stubs. Follow up
    with `wikitoolkit page <id>` to read a full page, or
    `wikitoolkit related <id>` to walk the graph.
    """
    root, config = _resolve_project(path_)
    store = _require_built(root, config)
    rows = _run(store.search_fts(question, category=category, limit=top_k))
    rows = _normalize_scores(rows)

    if as_json:
        click.echo(json.dumps(rows, indent=2, default=str))
        return
    if not rows:
        click.echo(
            f"No wiki results for {question!r}. The wiki may be stale — "
            "try `wikitoolkit build`, or fall back to code search."
        )
        return
    packed = pack_results(rows, budget_tokens=budget)
    click.echo(f"# Wiki results for: {question}\n")
    click.echo(packed.text)
    click.echo(
        f"\n({packed.results_packed}/{packed.total_available} results, "
        f"~{packed.tokens_used} tokens)"
    )
    click.echo(
        "Next: `wikitoolkit page <id>` for a full page · "
        "`wikitoolkit related <id>` for linked pages."
    )


@wiki.command()
@click.argument("page_id")
@path_option
@click.option(
    "--max-tokens",
    default=None,
    type=int,
    help="Truncate the body to roughly this many tokens.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def page(
    page_id: str,
    path_: Optional[str],
    max_tokens: Optional[int],
    as_json: bool,
) -> None:
    """Read one wiki page in full (progressive disclosure)."""
    root, config = _resolve_project(path_)
    store = _require_built(root, config)
    data = _run(store.get_page(page_id, include_body=True))
    if data is None:
        raise click.ClickException(
            f"Page {page_id!r} not found. "
            f"Search first: wikitoolkit query \"...\""
        )
    if as_json:
        click.echo(json.dumps(data, indent=2, default=str))
        return
    body = str(data.get("body") or "")
    truncated = False
    if max_tokens is not None:
        body, truncated = truncate_to_tokens(body, max_tokens)
    click.echo(f"# {data.get('title')}  [{data.get('concept_id')}]")
    click.echo(f"category: {data.get('category')}")
    if data.get("summary"):
        click.echo(f"summary: {data.get('summary')}\n")
    click.echo(body)
    if truncated:
        click.echo("\n[... body truncated — re-run without --max-tokens]")


@wiki.command()
@click.argument("page_id")
@path_option
@click.option("--rel", default=None, help="Filter by edge relation (e.g. contains).")
@click.option(
    "--direction",
    type=click.Choice(["out", "in", "both"]),
    default="both",
    show_default=True,
)
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def related(
    page_id: str,
    path_: Optional[str],
    rel: Optional[str],
    direction: str,
    as_json: bool,
) -> None:
    """List pages linked to PAGE_ID by typed edges."""
    root, config = _resolve_project(path_)
    store = _require_built(root, config)
    rows = _run(store.neighbors(page_id, rel=rel, direction=direction))
    if as_json:
        click.echo(json.dumps(rows, indent=2, default=str))
        return
    if not rows:
        click.echo(f"No edges from {page_id!r}.")
        return
    for row in rows:
        arrow = "→" if row.get("direction") == "out" else "←"
        click.echo(
            f"{arrow} [{row.get('concept_id')}] "
            f"({row.get('rel')}) {row.get('title', '')}"
        )


@wiki.command()
@path_option
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def status(path_: Optional[str], as_json: bool) -> None:
    """Show wiki plane statistics and source staleness."""
    root, config = _resolve_project(path_)
    if not config.is_built(root):
        click.echo(f"Wiki not built for {root} — run `wikitoolkit build`.")
        return
    store = _open_store(root, config)
    sources = _open_sources(root, config)
    stats = _run(store.stats())
    entries = sources.list_sources()
    stale = [e.source_id for e in entries if sources.is_stale(e.source_id)]
    payload = {
        "root": str(root),
        "wiki_name": config.wiki_name,
        "backend": config.backend,
        "storage_dir": str(config.storage_path(root)),
        "stats": stats,
        "sources": len(entries),
        "stale_sources": len(stale),
    }
    if as_json:
        click.echo(json.dumps(payload, indent=2, default=str))
        return
    click.echo(f"Wiki      : {config.wiki_name} ({config.backend})")
    click.echo(f"Root      : {root}")
    click.echo(f"Storage   : {payload['storage_dir']}")
    click.echo(
        f"Plane     : {stats.get('pages', 0)} pages, "
        f"{stats.get('edges', 0)} edges, "
        f"~{stats.get('total_tokens', 0)} tokens"
    )
    click.echo(f"Categories: {stats.get('categories', {})}")
    click.echo(f"Sources   : {len(entries)} tracked, {len(stale)} stale")
    if stale:
        click.echo("Run `wikitoolkit build` to refresh stale sources.")


@wiki.command()
@path_option
@click.option(
    "--output",
    "-o",
    default="docs/wiki",
    show_default=True,
    help="Output directory for the markdown bundle (relative to root).",
)
def export(path_: Optional[str], output: str) -> None:
    """Export the wiki as a human-readable markdown bundle.

    Writes one markdown file per page (YAML frontmatter + body) plus a
    root index.md — the `--wiki` action of the /parrotwiki command.
    """
    from parrot.knowledge.wiki.export import export_okf_bundle

    root, config = _resolve_project(path_)
    store = _require_built(root, config)
    out_dir = Path(output)
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    report = _run(
        export_okf_bundle(store, out_dir, wiki_name=config.wiki_name)
    )
    # Exclude the export output from future scans, or the next build
    # would ingest the wiki's own exported markdown back into itself.
    try:
        export_rel = out_dir.resolve().relative_to(root).as_posix()
    except ValueError:
        export_rel = None
    if export_rel and export_rel not in config.exclude_dirs:
        config.exclude_dirs.append(export_rel)
        save_project_config(root, config)
    click.echo(
        f"Exported {report.files_written} pages to {out_dir} "
        f"(index: {'yes' if report.index_generated else 'no'})."
    )


@wiki.command(name="claude-hook", hidden=True)
def claude_hook() -> None:
    """Claude Code PreToolUse hook runtime (reads stdin JSON).

    Configured by `parrot claude install` in .claude/settings.json;
    emits a non-blocking nudge toward `wikitoolkit query` before
    search-style tool calls. Always exits 0.
    """
    import sys

    from parrot.knowledge.wiki.claude_code.hook import run_pre_tool_use_hook

    sys.exit(run_pre_tool_use_hook())


def main() -> None:
    """Console-script entry point for ``wikitoolkit``."""
    wiki()


if __name__ == "__main__":
    main()
