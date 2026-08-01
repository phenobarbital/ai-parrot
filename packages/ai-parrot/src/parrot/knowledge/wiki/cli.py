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
    build        Generate/refresh the KB graph from the repository.
    upsert       Incrementally re-ingest specific/changed files.
    query        Scoped question → token-budgeted context pack.
    page         Read one wiki page (progressive disclosure).
    related      Follow typed edges from a page.
    communities  Community detection + inter-community relations (FEAT-401).
    status       Plane statistics + staleness report.
    export       Export the wiki as a human-readable markdown bundle.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from datetime import UTC
from pathlib import Path, PurePosixPath
from typing import Any

import click

from parrot.knowledge.wiki.context import (
    DEFAULT_BUDGET_TOKENS,
    pack_results,
    truncate_to_tokens,
)
from parrot.knowledge.wiki.languages import all_scanners
from parrot.knowledge.wiki.project import (
    WikiConfigError,
    WikiProjectConfig,
    find_project_root,
    load_project_config,
    save_project_config,
    wiki_write_lock,
)
from parrot.knowledge.wiki.repo_scan import (
    is_inside_wiki_bundle,
    is_wiki_relevant,
    scan_repository,
)
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import BaseWikiStore, create_wiki_store

_cli_logger = logging.getLogger("wikitoolkit.cli")

#: How long `upsert` waits for a contended store lock before skipping.
#: Long enough to outlast a peer upsert (sub-second), short enough that
#: a commit hook never stalls behind a multi-minute build.
UPSERT_LOCK_WAIT_SECONDS = 3.0


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

#: Shared `--path` option — every command resolves the repo root the same way.
path_option = click.option(
    "--path", "path_", default=None, help="Repo root (default: auto-detect)."
)

def _resolve_project(path: str | None) -> tuple[Path, WikiProjectConfig]:
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


def _env_setting(name: str) -> str | None:
    """Read a wiki env setting (``WIKI_STORE`` / ``WIKI_STORE_BACKEND``).

    Prefers navconfig (so values in ``.env`` are honoured, matching the
    legacy ``parrot llmwiki`` behaviour) and falls back to ``os.environ``
    when navconfig is unavailable.
    """
    try:
        from navconfig import config as _nav

        value = _nav.get(name, fallback=None)
    except Exception:  # noqa: BLE001 — navconfig optional; env is enough
        import os

        value = os.environ.get(name)
    return value or None


def _resolve_read_store(
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
) -> BaseWikiStore:
    """Open a store for a read command (``query`` / ``page`` / ``related``).

    With ``--store`` the CLI reads an arbitrary pre-built wiki store
    directly — e.g. the rich ``docs/parrot`` bundle produced by
    ``scripts/build_llm_wiki.py`` — instead of the project's own
    ``.parrot/wiki`` plane. Otherwise the project config resolves the
    plane exactly as ``build`` writes it.

    Resolution precedence (an *explicit* target always wins over the
    ambient env, so a ``--path``-scoped invocation is never silently
    redirected by ``WIKI_STORE``)::

        --store  >  --path project  >  WIKI_STORE env  >  auto-detected project
    """
    store_override = store_opt
    if not store_override and not path_:
        # Only consult the env when neither an explicit store nor an
        # explicit project path was given.
        store_override = _env_setting("WIKI_STORE")
    if store_override:
        backend = backend_opt or _env_setting("WIKI_STORE_BACKEND") or "sqlite"
        storage_dir = Path(store_override).expanduser()
        if not storage_dir.is_dir():
            raise click.ClickException(f"No wiki store directory: {storage_dir}")
        if backend == "sqlite" and not (storage_dir / "wiki.db").exists():
            raise click.ClickException(
                f"No wiki database at {storage_dir / 'wiki.db'}. Build it "
                "first, or point --store at the right root."
            )
        return create_wiki_store(storage_dir, backend=backend)
    root, config = _resolve_project(path_)
    return _require_built(root, config)


#: Shared `--store`/`--backend` options for the read commands.
def _store_options(func: Any) -> Any:
    """Attach ``--store`` and ``--backend`` to a read command."""
    func = click.option(
        "--backend",
        "backend_opt",
        type=click.Choice(["sqlite", "memory"]),
        default=None,
        help="Backend for --store (default: sqlite / WIKI_STORE_BACKEND).",
    )(func)
    func = click.option(
        "--store",
        "store_opt",
        default=None,
        help="Read a pre-built wiki store directly (e.g. docs/parrot); "
        "defaults to WIKI_STORE env or the project's own plane.",
    )(func)
    return func


def _render_results_table(
    rows: list[dict[str, Any]], question: str, show_body: bool
) -> None:
    """Pretty-print ranked results as a Rich table (+ optional body panel).

    Human-facing counterpart to the machine-first context pack — ported
    from the legacy ``parrot llmwiki`` renderer so ``wiki query --table``
    keeps the same at-a-glance output.
    """
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    table = Table(title=f"LLM Wiki · {question!r}", title_justify="left")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Score", justify="right", style="cyan")
    table.add_column("Category", style="magenta")
    table.add_column("Title", style="bold")
    table.add_column("Summary")
    for idx, row in enumerate(rows, start=1):
        score = row.get("score")
        score_str = f"{score:.3f}" if isinstance(score, (int, float)) else "-"
        summary = (row.get("summary") or "").strip().replace("\n", " ")
        if len(summary) > 140:
            summary = summary[:137] + "..."
        table.add_row(
            str(idx),
            score_str,
            str(row.get("category", "")),
            str(row.get("title", "")),
            summary,
        )
    console.print(table)
    if show_body and rows:
        top = rows[0]
        body = (top.get("body") or "").strip()
        if body:
            console.print(
                Panel(
                    Markdown(body),
                    title=f"{top.get('title', '')} · {top.get('concept_id', '')}",
                    border_style="green",
                )
            )


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
# Post-build: OKF export + graph.html
# --------------------------------------------------------------------------

_CATEGORY_TO_NODE_KIND: dict[str, str] = {
    "module": "WIKI_PAGE",
    "document": "DOCUMENT",
    "config": "DOCUMENT",
    "overview": "DOCUMENT",
    "summary": "WIKI_PAGE",
    "entity": "SYMBOL",
    "concept": "SYMBOL",
}

_REL_TO_EDGE_KIND: dict[str, str] = {
    "contains": "CONTAINS",
    "defines": "DEFINES",
    "references": "REFERENCES",
    "extends": "EXTENDS",
    "mentions": "MENTIONS",
    "explains": "EXPLAINS",
}


async def _export_okf(
    store: BaseWikiStore,
    output_dir: Path,
    wiki_name: str,
) -> dict[str, Any]:
    """Export the OKF markdown bundle and return a report dict."""
    from parrot.knowledge.wiki.export import export_okf_bundle

    report = await export_okf_bundle(store, output_dir, wiki_name=wiki_name)
    return {
        "files_written": report.files_written,
        "index_generated": report.index_generated,
    }


async def _load_graphindex_nodes_edges(
    store: BaseWikiStore,
    graph_kinds: frozenset[str],
) -> tuple[list[Any], list[Any]]:
    """Reconstruct ``UniversalNode``/``UniversalEdge`` lists from the wiki
    store's pages + typed edges, filtered to ``graph_kinds`` categories.

    Shared by the ``build`` graph.html export and the on-demand
    ``communities`` CLI command (FEAT-401) — both need the same
    wiki-page → GraphIndex-schema adaptation. Returns ``([], [])`` when
    no pages match ``graph_kinds``.
    """
    from parrot.knowledge.graphindex.schema import (
        EdgeKind,
        NodeKind,
        UniversalEdge,
        UniversalNode,
    )

    pages = await store.dump_pages()
    edges = await store.dump_edges()

    kind_pages = [
        p for p in pages
        if p.get("category", "") in graph_kinds
    ]
    if not kind_pages:
        return [], []

    node_ids = {p["concept_id"] for p in kind_pages}

    nodes: list[UniversalNode] = []
    for p in kind_pages:
        nk_name = _CATEGORY_TO_NODE_KIND.get(p.get("category", ""), "WIKI_PAGE")
        nodes.append(UniversalNode(
            node_id=p["concept_id"],
            kind=NodeKind[nk_name],
            title=p.get("title", ""),
            source_uri=p.get("source_id", "") or p.get("concept_id", ""),
            summary=p.get("summary"),
            domain_tags={"category": p.get("category", "")},
        ))

    graph_edges: list[UniversalEdge] = []
    for e in edges:
        src, dst = e.get("src", ""), e.get("dst", "")
        if src in node_ids and dst in node_ids:
            ek_name = _REL_TO_EDGE_KIND.get(e.get("rel", ""), "REFERENCES")
            graph_edges.append(UniversalEdge(
                source_id=src,
                target_id=dst,
                kind=EdgeKind[ek_name],
            ))

    return nodes, graph_edges


async def _export_graph_html(
    store: BaseWikiStore,
    output_dir: Path,
    wiki_name: str,
    graph_kinds: frozenset[str],
) -> dict[str, Any]:
    """Build the interactive graph.html from the wiki store contents."""
    try:
        from parrot.knowledge.graphindex.assemble import GraphAssembler
        from parrot.knowledge.graphindex.export_html import export_graph
    except ImportError as exc:
        _cli_logger.warning("graph export unavailable: %s", exc)
        return {"exported": False, "reason": str(exc)}

    nodes, graph_edges = await _load_graphindex_nodes_edges(store, graph_kinds)
    if not nodes:
        return {"nodes": 0, "edges": 0, "exported": False}

    assembler = GraphAssembler(tenant_id=wiki_name)
    assembler.add_nodes(nodes)
    assembler.add_edges(graph_edges)

    communities = None
    analytics = None
    try:
        from parrot.knowledge.graphindex.communities import detect_communities
        communities = detect_communities(
            graph=assembler.graph, nodes=nodes, write_back_to_nodes=True,
        )
    except Exception as exc:  # noqa: BLE001
        _cli_logger.warning("community detection skipped: %s", exc)
    try:
        from parrot.knowledge.graphindex.analytics import compute_analytics
        analytics = compute_analytics(assembler.graph, nodes, graph_edges)
    except Exception as exc:  # noqa: BLE001
        _cli_logger.warning("analytics skipped: %s", exc)

    try:
        html_path, json_path = export_graph(
            assembler.graph,
            output_dir,
            communities=communities,
            analytics=analytics,
            title=f"{wiki_name} — Knowledge Map",
        )
    except Exception as exc:  # noqa: BLE001
        _cli_logger.error("graph export failed: %s", exc)
        return {"nodes": len(nodes), "edges": len(graph_edges), "exported": False}

    result: dict[str, Any] = {
        "nodes": len(nodes),
        "edges": len(graph_edges),
        "exported": True,
        "html": str(html_path.name),
        "json": str(json_path.name),
    }
    if communities:
        result["communities"] = len(communities.communities)
        result["modularity"] = round(communities.modularity, 4)
    return result


def _write_build_stats(
    output_dir: Path,
    wiki_name: str,
    store_stats: dict[str, Any],
    okf_report: dict[str, Any] | None,
    graph_stats: dict[str, Any] | None,
) -> None:
    """Write wiki_stats.json and README.md into the output directory."""
    from datetime import datetime

    stats: dict[str, Any] = {
        "wiki_name": wiki_name,
        "generated_at": datetime.now(tz=UTC).strftime(
            "%Y-%m-%dT%H:%M:%S+00:00"
        ),
        "pages": store_stats.get("pages", 0),
        "edges": store_stats.get("edges", 0),
        "categories": store_stats.get("categories", {}),
        "okf": okf_report,
        "graph": graph_stats,
        "languages": {name: s.mode for name, s in all_scanners().items()},
    }
    (output_dir / "wiki_stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8",
    )

    lines = [
        f"# {wiki_name} — LLM Wiki",
        "",
        "> Machine-first knowledge base compiled from this repository by "
        "`parrot wiki build`, using the AI-Parrot `parrot.knowledge.wiki` "
        "retrieval plane (FEAT-260).",
        "",
        "## What's here",
        "",
        "| Artefact | Purpose |",
        "| --- | --- |",
        "| `wiki.db` | SQLite retrieval plane (FTS5/BM25 + typed edges). |",
    ]
    if okf_report and okf_report.get("files_written"):
        lines.append(
            "| `index.md` + category folders | OKF v0.1 markdown bundle "
            "— the human-browsable projection of every page. |"
        )
    if graph_stats and graph_stats.get("exported"):
        lines.append(
            "| `graph.html` | Interactive, offline knowledge-graph map "
            "(open in a browser). |"
        )
        lines.append(
            "| `graph.json` | Serialized graph (nodes, edges, communities). |"
        )
    lines.append("| `wiki_stats.json` | Full build report. |")
    lines += [
        "",
        "## Contents",
        "",
        f"- **{stats['pages']}** pages, **{stats['edges']}** edges",
    ]
    cats = stats.get("categories", {})
    if cats:
        lines += ["", "### Pages by category", ""]
        lines += [f"- `{k}`: {v}" for k, v in sorted(cats.items())]
    if graph_stats and graph_stats.get("exported"):
        lines += [
            "",
            "### Knowledge map",
            "",
            f"- [`graph.html`](./graph.html) — {graph_stats['nodes']} nodes, "
            f"{graph_stats['edges']} edges"
            + (
                f", {graph_stats.get('communities', 0)} communities "
                f"(modularity {graph_stats.get('modularity')})"
                if graph_stats.get("communities")
                else ""
            ),
        ]
    lines += [
        "",
        "## Querying",
        "",
        "```bash",
        "wikitoolkit query \"your question\" --path .",
        "```",
        "",
        f"_Generated {stats['generated_at']}._",
        "",
    ]
    (output_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


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
@click.option(
    "--no-export",
    is_flag=True,
    help="Skip OKF markdown bundle export.",
)
@click.option(
    "--no-graph",
    is_flag=True,
    help="Skip graph.html / graph.json generation.",
)
@click.option(
    "--graph-kinds",
    default="module,document,overview",
    show_default=True,
    help="Comma list of page categories included in graph.html.",
)
def build(
    path_: str | None,
    name: str | None,
    backend: str | None,
    force: bool,
    no_git: bool,
    quiet: bool,
    no_export: bool,
    no_graph: bool,
    graph_kinds: str,
) -> None:
    """Generate (or refresh) the KB graph from the current repository.

    Deterministic and offline: scans source files (respecting
    .gitignore), extracts summaries/API outlines, and writes pages +
    typed edges into the wiki retrieval plane.

    By default also produces an OKF markdown bundle (index.md +
    per-page files), an interactive graph.html / graph.json knowledge
    map, a wiki_stats.json build report, and a README.md entry point.
    """
    root, config = _resolve_project(path_)
    with wiki_write_lock(config.storage_path(root)) as _acquired:
        if not _acquired:
            click.echo(
                "Another wiki writer is in progress (build or upsert) — "
                "refusing to run two writers against the same store. Wait "
                "for it to finish, then retry."
            )
            raise SystemExit(1)
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

        output_dir = config.storage_path(root)

        async def _pipeline() -> dict[str, Any]:
            store = _open_store(root, config)
            sources = _open_sources(root, config)
            counts = await _ingest_files(store, sources, root, scan, force=force)
            await store.upsert_pages(scan.dir_records)
            await store.add_edges(scan.dir_edges)
            counts["removed"] = await _prune_removed(store, sources, root, scan)
            counts["stats"] = await store.stats()

            okf_report: dict[str, Any] | None = None
            if not no_export:
                okf_report = await _export_okf(
                    store, output_dir, config.wiki_name,
                )
                # Exclude the export output from future scans.
                try:
                    export_rel = output_dir.resolve().relative_to(root).as_posix()
                except ValueError:
                    export_rel = None
                if export_rel and export_rel not in config.exclude_dirs:
                    config.exclude_dirs.append(export_rel)
            counts["okf"] = okf_report

            graph_stats: dict[str, Any] | None = None
            if not no_graph:
                kinds = frozenset(
                    k.strip() for k in graph_kinds.split(",") if k.strip()
                )
                graph_stats = await _export_graph_html(
                    store, output_dir, config.wiki_name, kinds,
                )
            counts["graph"] = graph_stats

            return counts

        counts = _run(_pipeline())
        save_project_config(root, config)

        stats = counts["stats"]

        # Write wiki_stats.json + README.md.
        _write_build_stats(
            output_dir, config.wiki_name, stats,
            counts.get("okf"), counts.get("graph"),
        )

        click.echo(
            f"Wiki '{config.wiki_name}' built at "
            f"{output_dir} — "
            f"{counts['written']} ingested, {counts['unchanged']} unchanged, "
            f"{counts['removed']} removed; "
            f"{stats.get('pages', 0)} pages, {stats.get('edges', 0)} edges."
        )
        okf = counts.get("okf")
        if okf and not quiet:
            click.echo(f"OKF bundle: {okf['files_written']} files exported.")
        graph = counts.get("graph")
        if graph and graph.get("exported") and not quiet:
            click.echo(
                f"Graph: {graph['nodes']} nodes, {graph['edges']} edges "
                f"→ {graph['html']}"
            )
        if scan.skipped and not quiet:
            click.echo(f"Skipped {len(scan.skipped)} binary/oversized files.")
            if len(scan.skipped) <= 10:
                for path in scan.skipped:
                    click.echo(f"  - {path}")


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
    path_: str | None,
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
    # Wait out a peer upsert (sub-second) rather than dropping the
    # commit's files; give up quickly if a multi-minute build holds it.
    with wiki_write_lock(
        config.storage_path(root), timeout=UPSERT_LOCK_WAIT_SECONDS
    ) as _acquired:
        if not _acquired:
            if not quiet:
                click.echo(
                    "Another wiki writer is in progress (likely a full "
                    "build) — skipping this upsert; the build will cover "
                    "these files."
                )
            return
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
            # never disagree about what belongs in the wiki. The bundle
            # guardrail is checked per path (ancestor walk) rather than by
            # discovering every bundle in the repo, so a docs-only commit
            # keeps its O(1) fast path.
            if is_wiki_relevant(
                rel,
                suffixes=config.include_suffixes or None,
                exclude_dirs=config.exclude_dirs,
            ) and not is_inside_wiki_bundle(root, rel):
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
@click.option(
    "--top-k", "-n", default=12, show_default=True, help="Max results to rank."
)
@click.option(
    "--budget",
    default=DEFAULT_BUDGET_TOKENS,
    show_default=True,
    help="Token budget for the packed context.",
)
@click.option("--category", default=None, help="Filter by page category.")
@_store_options
@click.option(
    "--table",
    "as_table",
    is_flag=True,
    help="Render a human-facing Rich table instead of the context pack.",
)
@click.option(
    "--body",
    "-b",
    "show_body",
    is_flag=True,
    help="Also fetch/render the full body of the top-ranked page.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON results.")
def query(
    question: str,
    path_: str | None,
    top_k: int,
    budget: int,
    category: str | None,
    store_opt: str | None,
    backend_opt: str | None,
    as_table: bool,
    show_body: bool,
    as_json: bool,
) -> None:
    """Scoped question against the codebase KB (lexical BM25 search).

    Returns a token-budgeted context pack of page stubs (or a
    human-facing Rich table with `--table`). Point `--store` at any
    pre-built wiki (e.g. `docs/parrot`) to query it directly. Follow up
    with `wikitoolkit page <id>` to read a full page, or
    `wikitoolkit related <id>` to walk the graph.
    """
    store = _resolve_read_store(path_, store_opt, backend_opt)
    rows = _run(store.search_fts(question, category=category, limit=top_k))
    rows = _normalize_scores(rows)

    # Hydrate the top hit's body once, for --body across every renderer.
    if show_body and rows:
        top = _run(store.get_page(rows[0]["concept_id"], include_body=True))
        if top:
            rows[0] = {**rows[0], **top}

    if as_json:
        click.echo(json.dumps(rows, indent=2, default=str))
        return
    if not rows:
        click.echo(
            f"No wiki results for {question!r}. The wiki may be stale — "
            "try `wikitoolkit build`, or fall back to code search."
        )
        return
    if as_table:
        _render_results_table(rows, question, show_body=show_body)
        return
    packed = pack_results(rows, budget_tokens=budget)
    click.echo(f"# Wiki results for: {question}\n")
    click.echo(packed.text)
    click.echo(
        f"\n({packed.results_packed}/{packed.total_available} results, "
        f"~{packed.tokens_used} tokens)"
    )
    if show_body and rows[0].get("body"):
        click.echo(f"\n## {rows[0].get('title')}\n{rows[0]['body']}")
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
@_store_options
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def page(
    page_id: str,
    path_: str | None,
    max_tokens: int | None,
    store_opt: str | None,
    backend_opt: str | None,
    as_json: bool,
) -> None:
    """Read one wiki page in full (progressive disclosure)."""
    store = _resolve_read_store(path_, store_opt, backend_opt)
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
@_store_options
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def related(
    page_id: str,
    path_: str | None,
    rel: str | None,
    direction: str,
    store_opt: str | None,
    backend_opt: str | None,
    as_json: bool,
) -> None:
    """List pages linked to PAGE_ID by typed edges."""
    store = _resolve_read_store(path_, store_opt, backend_opt)
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
def status(path_: str | None, as_json: bool) -> None:
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
        "languages": {name: s.mode for name, s in all_scanners().items()},
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
    click.echo(f"Languages : {payload['languages']}")
    click.echo(f"Sources   : {len(entries)} tracked, {len(stale)} stale")
    if stale:
        click.echo("Run `wikitoolkit build` to refresh stale sources.")


@wiki.command()
@path_option
@click.option(
    "--graph-kinds",
    default="module,document,overview",
    show_default=True,
    help="Comma list of page categories included in the community graph.",
)
@click.option(
    "--inter",
    "show_inter",
    is_flag=True,
    help="Also compute and print inter-community relations (FEAT-401).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def communities(
    path_: str | None,
    graph_kinds: str,
    show_inter: bool,
    as_json: bool,
) -> None:
    """Show detected communities, or inter-community relations with --inter.

    Runs Leiden (falling back to Louvain, FEAT-401) community detection
    on demand from the current wiki store contents — no need to re-run
    `wikitoolkit build` or regenerate graph.html. With `--inter`, also
    computes the inter-community meta-graph (which community pairs are
    connected, coupling ratios, edge direction) for cross-subsystem
    questions like "how do the auth and payment areas relate?". Output
    is token-budgeted for LLM-agent consumption.
    """
    root, config = _resolve_project(path_)
    if not config.is_built(root):
        click.echo(f"Wiki not built for {root} — run `wikitoolkit build`.")
        return
    store = _open_store(root, config)

    kinds = frozenset(k.strip() for k in graph_kinds.split(",") if k.strip())
    nodes, graph_edges = _run(_load_graphindex_nodes_edges(store, kinds))
    if not nodes:
        click.echo(
            "No pages found for --graph-kinds="
            f"{graph_kinds!r}. Run `wikitoolkit build` first, or widen "
            "--graph-kinds."
        )
        return

    from parrot.knowledge.graphindex.assemble import GraphAssembler
    from parrot.knowledge.graphindex.communities import detect_communities

    assembler = GraphAssembler(tenant_id=config.wiki_name)
    assembler.add_nodes(nodes)
    assembler.add_edges(graph_edges)
    communities_result = detect_communities(
        assembler.graph, nodes, write_back_to_nodes=False,
    )

    if not show_inter:
        if as_json:
            click.echo(json.dumps(
                communities_result.model_dump(mode="json"), indent=2,
            ))
            return
        click.echo(
            f"# Communities ({len(communities_result.communities)}, "
            f"algorithm={communities_result.algorithm}, "
            f"modularity={communities_result.modularity:.4f})\n"
        )
        if not communities_result.communities:
            click.echo("(no communities detected)")
            return
        for c in communities_result.communities:
            click.echo(f"| `{c.community_id}` | {c.label or '(unlabeled)'} | {c.size} members |")
        return

    from parrot.knowledge.graphindex.inter_community import (
        compute_inter_community_graph,
    )

    inter = compute_inter_community_graph(assembler.graph, communities_result)

    if as_json:
        click.echo(json.dumps(inter.model_dump(mode="json"), indent=2))
        return

    click.echo(
        f"Inter-Community Relations (density: {inter.density:.1%}, "
        f"{inter.connected_pairs}/{inter.total_possible_pairs} pairs)\n"
    )
    if not inter.relations:
        click.echo("(no cross-community edges detected)")
        return
    for rel in inter.relations:
        arrow = "→" if rel.directed_edge_count >= rel.reverse_edge_count else "←"
        src = rel.source_label or rel.source_community_id
        tgt = rel.target_label or rel.target_community_id
        click.echo(
            f"| {src} {arrow} {tgt} | {rel.directed_edge_count}→, "
            f"{rel.reverse_edge_count}← | coupling: {rel.coupling_ratio:.2f} |"
        )


@wiki.command()
@path_option
@click.option(
    "--output",
    "-o",
    default="docs/wiki",
    show_default=True,
    help="Output directory for the markdown bundle (relative to root).",
)
def export(path_: str | None, output: str) -> None:
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


# --------------------------------------------------------------------------
# Authoring / persistent-memory commands ("save things in the brain")
# --------------------------------------------------------------------------

def _authoring_identity(by: str | None) -> str:
    """Resolve who is asserting a write.

    Precedence: explicit ``--by`` > ``CLAUDE_AGENT_ID`` /
    ``PARROT_AGENT_ID`` env (prefixed ``agent:``) > the local user
    (prefixed ``human:``).
    """
    import getpass
    import os

    if by:
        return by
    for env_name in ("CLAUDE_AGENT_ID", "PARROT_AGENT_ID"):
        value = os.environ.get(env_name)
        if value:
            return f"agent:{value}"
    try:
        return f"human:{getpass.getuser()}"
    except Exception:  # noqa: BLE001 — no user db in some containers
        return "human:unknown"


def _authoring_run_id() -> str | None:
    """Session/run identifier from the ambient environment, if any."""
    import os

    for env_name in ("CLAUDE_SESSION_ID", "PARROT_RUN_ID"):
        value = os.environ.get(env_name)
        if value:
            return value
    return None


def _resolve_write_store(
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
) -> tuple[BaseWikiStore, Path, Path | None, WikiProjectConfig | None]:
    """Open a store for an authoring command, creating the plane lazily.

    Same precedence as ``_resolve_read_store`` (``--store`` > ``--path``
    project > ``WIKI_STORE`` env > auto-detected project), but a wiki
    that was never built is initialised on first write instead of
    aborting — remembering something must work from a blank slate.

    Returns:
        ``(store, storage_dir, root, config)`` — ``root``/``config`` are
        ``None`` for ``--store`` targets (no project context).
    """
    store_override = store_opt
    if not store_override and not path_:
        store_override = _env_setting("WIKI_STORE")
    if store_override:
        backend = backend_opt or _env_setting("WIKI_STORE_BACKEND") or "sqlite"
        storage_dir = Path(store_override).expanduser()
        storage_dir.mkdir(parents=True, exist_ok=True)
        return create_wiki_store(storage_dir, backend=backend), storage_dir, None, None
    root, config = _resolve_project(path_)
    return _open_store(root, config), config.storage_path(root), root, config


def _sync_memory_to_graph(
    root: Path,
    config: WikiProjectConfig,
    store: BaseWikiStore,
    page_id: str,
    title: str,
    text: str,
    links: list[tuple[str, str]],
    asserted_by: str,
    run_id: str | None,
) -> str | None:
    """Mirror a remembered fact into the project's GraphIndex plane.

    Publishes one audited commit containing a ``CONCEPT`` node for the
    memory (plus stub nodes for linked wiki pages so no edge dangles)
    into ``.parrot/graph/``. GraphIndex imports stay inside this
    function so the wiki CLI works without the graphindex extra.

    Returns:
        The commit id, or ``None`` when sync failed/unavailable.
    """
    try:
        from parrot.knowledge.graphindex.factory import make_stub_tenant_context
        from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
        from parrot.knowledge.graphindex.publish import GraphPublisher
        from parrot.knowledge.graphindex.schema import (
            EdgeKind,
            GraphUpdate,
            NodeKind,
            Provenance,
            UniversalEdge,
            UniversalNode,
        )
    except ImportError as exc:
        click.echo(f"[graph sync skipped: graphindex unavailable — {exc}]")
        return None

    try:
        ctx = make_stub_tenant_context(config.wiki_name)
        persistence = SQLitePersistence(config.graph_path(root))
        publisher = GraphPublisher(persistence, ctx)

        nodes = [
            UniversalNode(
                node_id=page_id,
                kind=NodeKind.CONCEPT,
                title=title,
                source_uri=f"wiki://{config.wiki_name}/{page_id}",
                summary=text[:300],
                provenance=Provenance.ASSERTED,
            )
        ]
        edges = []
        for target_id, rel in links:
            target = _run(store.get_page(target_id, include_body=False))
            if target is None:
                continue
            nodes.append(
                UniversalNode(
                    node_id=target_id,
                    kind=NodeKind.CONCEPT,
                    title=str(target.get("title") or target_id),
                    source_uri=f"wiki://{config.wiki_name}/{target_id}",
                    summary=str(target.get("summary") or "")[:300],
                )
            )
            try:
                kind = EdgeKind(rel)
            except ValueError:
                kind = EdgeKind.REFERENCES
            edges.append(
                UniversalEdge(source_id=page_id, target_id=target_id, kind=kind)
            )
        receipt = _run(
            publisher.publish(
                GraphUpdate(
                    nodes=nodes,
                    edges=edges,
                    agent_id=asserted_by.split(":", 1)[-1],
                    run_id=run_id,
                    asserted_by=asserted_by,
                    source=f"wiki://{config.wiki_name}/{page_id}",
                    op="remember",
                )
            )
        )
        return receipt.commit_id
    except Exception as exc:  # noqa: BLE001 — sync must never block the save
        click.echo(f"[graph sync failed: {exc}]")
        return None


def _extract_into_graph(
    root: Path,
    config: WikiProjectConfig,
    text: str,
    source_uri: str,
    asserted_by: str,
    run_id: str | None,
) -> dict[str, Any] | None:
    """Run LLM entity/relation extraction into the project graph plane.

    Requires a ``WIKI_EXTRACT_LLM`` provider spec (env / .env, e.g.
    ``anthropic:claude-haiku-4-5``). All heavyweight imports are lazy;
    every failure degrades to ``None`` so the plain remember always
    succeeds.

    Returns:
        Extraction summary dict, or ``None`` when unavailable/failed.
    """
    spec = _env_setting("WIKI_EXTRACT_LLM")
    if not spec:
        click.echo(
            "[extract skipped: set WIKI_EXTRACT_LLM (e.g."
            " 'anthropic:claude-haiku-4-5') to enable]"
        )
        return None
    try:
        from parrot.clients.factory import LLMFactory
        from parrot.knowledge.graphindex.extractors.llm import LLMGraphExtractor
        from parrot.knowledge.graphindex.factory import make_stub_tenant_context
        from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
        from parrot.knowledge.graphindex.publish import GraphPublisher

        client = LLMFactory.create(spec, model_args={"temperature": 0.0})
        ctx = make_stub_tenant_context(config.wiki_name)
        publisher = GraphPublisher(
            SQLitePersistence(config.graph_path(root)), ctx
        )
        extractor = LLMGraphExtractor(client, publisher)
        result = _run(
            extractor.extract_and_publish(
                text,
                source_uri=source_uri,
                agent_id=asserted_by.split(":", 1)[-1],
                run_id=run_id,
            )
        )
        return {
            "entities": len(result.extracted.entities),
            "relations": len(result.extracted.relations),
            "nodes_written": len(result.update.nodes),
            "commit_id": result.receipt.commit_id,
        }
    except Exception as exc:  # noqa: BLE001 — extraction is best-effort
        click.echo(f"[extract failed: {exc}]")
        return None


@wiki.command()
@click.argument("text")
@path_option
@_store_options
@click.option("--title", default=None, help="Short title (default: first line).")
@click.option(
    "--category",
    default="note",
    help="Memory category: note | decision | lesson | concept.",
)
@click.option(
    "--link",
    "links",
    multiple=True,
    help="Existing page id to link the memory to (repeatable).",
)
@click.option("--rel", default="references", help="Relation for --link edges.")
@click.option("--source", "source_uri", default=None, help="Citation URI.")
@click.option("--by", default=None, help="Identity asserting this memory.")
@click.option(
    "--extract",
    "extract_",
    is_flag=True,
    help="Also run LLM entity/relation extraction over the text into the"
    " project graph (requires sync_graph and a WIKI_EXTRACT_LLM provider"
    " spec, e.g. 'anthropic:claude-haiku-4-5'; degrades to a plain"
    " remember when unavailable).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def remember(
    text: str,
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
    title: str | None,
    category: str,
    links: tuple[str, ...],
    rel: str,
    source_uri: str | None,
    by: str | None,
    extract_: bool,
    as_json: bool,
) -> None:
    """Save a fact, decision, or lesson into the wiki (persistent memory).

    The page id is a deterministic hash of title+category, so
    re-remembering the same thing updates the existing memory instead of
    duplicating it. With ``sync_graph`` enabled in ``.parrot/wiki.json``
    the memory is also mirrored into the project's knowledge graph as an
    audited commit.
    """
    import hashlib

    store, storage_dir, root, config = _resolve_write_store(
        path_, store_opt, backend_opt
    )
    asserted_by = _authoring_identity(by)
    run_id = _authoring_run_id()

    resolved_title = (title or text.strip().splitlines()[0][:80]).strip()
    if not resolved_title:
        raise click.ClickException("Cannot remember empty text.")
    page_id = "mem-" + hashlib.sha1(
        f"{resolved_title}::{category}".encode()
    ).hexdigest()[:12]

    from parrot.knowledge.wiki.store import WikiPageRecord, estimate_tokens

    existing = _run(store.get_page(page_id, include_body=False))
    body = text if not source_uri else f"{text}\n\n> Source: {source_uri}"
    _run(
        store.upsert_pages([
            WikiPageRecord(
                concept_id=page_id,
                node_id=page_id,
                title=resolved_title,
                category=category,
                summary=text[:300],
                body=body,
                token_count=estimate_tokens(body),
                origin="memory",
                asserted_by=asserted_by,
            )
        ])
    )

    linked: list[tuple[str, str]] = []
    skipped_links: list[str] = []
    for target in links:
        page = _run(store.get_page(target, include_body=False))
        if page is None:
            skipped_links.append(target)
            continue
        _run(store.add_edges([(page_id, page["concept_id"], rel, "asserted")]))
        linked.append((page["concept_id"], rel))

    from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper

    WikiBookkeeper().log_operation(
        storage_dir,
        "REMEMBER",
        f"page_id: {page_id}, title: {resolved_title!r}, "
        f"category: {category}, by: {asserted_by}"
        + (f", run: {run_id}" if run_id else ""),
    )

    commit_id: str | None = None
    if root is not None and config is not None and config.sync_graph:
        commit_id = _sync_memory_to_graph(
            root, config, store, page_id, resolved_title, text,
            linked, asserted_by, run_id,
        )

    extraction: dict[str, Any] | None = None
    if extract_ and root is not None and config is not None:
        extraction = _extract_into_graph(
            root, config, text,
            source_uri or f"wiki://{config.wiki_name}/{page_id}",
            asserted_by, run_id,
        )

    result = {
        "page_id": page_id,
        "title": resolved_title,
        "category": category,
        "status": "updated" if existing else "created",
        "asserted_by": asserted_by,
        "linked": [t for t, _ in linked],
        "skipped_links": skipped_links,
    }
    if commit_id:
        result["graph_commit"] = commit_id
    if extraction:
        result["extraction"] = extraction
    if as_json:
        click.echo(json.dumps(result, indent=2))
        return
    click.echo(
        f"{'Updated' if existing else 'Saved'} memory {page_id} "
        f"({category}): {resolved_title!r}"
    )
    for target, rel_name in linked:
        click.echo(f"  linked → {target} ({rel_name})")
    for target in skipped_links:
        click.echo(f"  [skipped link: no page {target!r}]")
    if commit_id:
        click.echo(f"  graph commit: {commit_id}")
    if extraction:
        click.echo(
            f"  extracted: {extraction.get('entities', 0)} entities,"
            f" {extraction.get('relations', 0)} relations"
            f" (commit {extraction.get('commit_id', '?')})"
        )


@wiki.command()
@click.argument("page_id")
@click.argument("text")
@path_option
@_store_options
@click.option("--by", default=None, help="Identity asserting this note.")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def note(
    page_id: str,
    text: str,
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
    by: str | None,
    as_json: bool,
) -> None:
    """Append an attributed note to an existing wiki page."""
    from datetime import datetime

    store, storage_dir, _root, _config = _resolve_write_store(
        path_, store_opt, backend_opt
    )
    page = _run(store.get_page(page_id, include_body=True))
    if page is None:
        raise click.ClickException(
            f"Page {page_id!r} not found. Search first: wikitoolkit query \"...\""
        )
    asserted_by = _authoring_identity(by)
    stamp = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    body = str(page.get("body") or "")
    body += f"\n\n> **Note ({stamp}, {asserted_by}):** {text}"

    from parrot.knowledge.wiki.store import WikiPageRecord, estimate_tokens

    _run(
        store.upsert_pages([
            WikiPageRecord(
                concept_id=page["concept_id"],
                node_id=page.get("node_id"),
                title=page.get("title") or page["concept_id"],
                category=page.get("category") or "concept",
                summary=page.get("summary") or "",
                body=body,
                source_id=page.get("source_id"),
                token_count=estimate_tokens(body),
                origin=page.get("origin") or "ingest",
                asserted_by=asserted_by,
            )
        ])
    )
    from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper

    WikiBookkeeper().log_operation(
        storage_dir,
        "NOTE",
        f"page_id: {page['concept_id']}, by: {asserted_by}",
    )
    result = {"page_id": page["concept_id"], "status": "noted", "by": asserted_by}
    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"Noted on {page['concept_id']} (by {asserted_by}).")


@wiki.command()
@click.argument("src")
@click.argument("dst")
@path_option
@_store_options
@click.option("--rel", default="references", help="Edge relation.")
@click.option("--by", default=None, help="Identity asserting this link.")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def link(
    src: str,
    dst: str,
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
    rel: str,
    by: str | None,
    as_json: bool,
) -> None:
    """Connect two existing wiki pages with an asserted, typed edge."""
    store, storage_dir, _root, _config = _resolve_write_store(
        path_, store_opt, backend_opt
    )
    pages = {}
    for label, cid in (("src", src), ("dst", dst)):
        page = _run(store.get_page(cid, include_body=False))
        if page is None:
            raise click.ClickException(f"{label} page {cid!r} not found.")
        pages[label] = page["concept_id"]
    asserted_by = _authoring_identity(by)
    _run(store.add_edges([(pages["src"], pages["dst"], rel, "asserted")]))

    from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper

    WikiBookkeeper().log_operation(
        storage_dir,
        "LINK",
        f"{pages['src']} -{rel}-> {pages['dst']}, by: {asserted_by}",
    )
    result = {
        "src": pages["src"],
        "dst": pages["dst"],
        "rel": rel,
        "status": "linked",
        "by": asserted_by,
    }
    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"Linked {pages['src']} -{rel}-> {pages['dst']}.")


@wiki.command()
@path_option
@_store_options
@click.option("--category", default=None, help="Filter by category.")
@click.option("--limit", default=50, type=int, help="Maximum rows.")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def memories(
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
    category: str | None,
    limit: int,
    as_json: bool,
) -> None:
    """List saved memories and agent-authored pages (newest first)."""
    store, _storage_dir, _root, _config = _resolve_write_store(
        path_, store_opt, backend_opt
    )
    rows = _run(
        store.list_pages(
            category=category, limit=limit, origin=["memory", "authored"]
        )
    )
    if as_json:
        click.echo(json.dumps(rows, indent=2, default=str))
        return
    if not rows:
        click.echo("No memories saved yet. Save one: wikitoolkit remember \"...\"")
        return
    for row in rows:
        click.echo(
            f"{row['concept_id']}  [{row.get('category')}]"
            f"  {row.get('title')!r}"
            f"  — {row.get('asserted_by') or '?'} @ {row.get('updated_at')}"
        )


@wiki.command()
@path_option
@_store_options
@click.option("--limit", default=30, type=int, help="Maximum entries per plane.")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def audit(
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
    limit: int,
    as_json: bool,
) -> None:
    """Show the wiki operation log and graph write commits (audit trail)."""
    _store, storage_dir, root, config = _resolve_write_store(
        path_, store_opt, backend_opt
    )
    from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper

    log_text = WikiBookkeeper().read_log(storage_dir, last_n=limit)

    graph_commits: list[dict[str, Any]] = []
    if root is not None and config is not None:
        graph_db = config.graph_path(root) / f"{config.wiki_name}.db"
        if graph_db.exists():
            try:
                from parrot.knowledge.graphindex.factory import (
                    make_stub_tenant_context,
                )
                from parrot.knowledge.graphindex.persist_sqlite import (
                    SQLitePersistence,
                )

                persistence = SQLitePersistence(config.graph_path(root))
                ctx = make_stub_tenant_context(config.wiki_name)
                graph_commits = _run(persistence.list_commits(ctx, limit=limit))
            except Exception as exc:  # noqa: BLE001
                click.echo(f"[graph audit unavailable: {exc}]")

    if as_json:
        click.echo(
            json.dumps(
                {"log": log_text.splitlines(), "graph_commits": graph_commits},
                indent=2,
                default=str,
            )
        )
        return
    click.echo("## Wiki operation log")
    click.echo(log_text or "(empty)")
    if graph_commits:
        click.echo("\n## Graph write commits")
        for c in graph_commits:
            reverted = " [REVERTED]" if c.get("reverted_at") else ""
            click.echo(
                f"{c['commit_id']}  {c['op']}  by {c['asserted_by']}"
                f"  @ {c['committed_at']}{reverted}"
            )


@wiki.command()
@click.argument("claim")
@path_option
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def ground(
    claim: str,
    path_: str | None,
    as_json: bool,
) -> None:
    """Check a claim against the project knowledge graph (grounding).

    Requires the project graph plane (``.parrot/graph/``) created by
    ``remember`` with ``sync_graph`` enabled or by ``--extract``.
    Returns cited edge-level evidence, or a structured revise
    instruction listing the missing evidence.
    """
    root, config = _resolve_project(path_)
    graph_db = config.graph_path(root) / f"{config.wiki_name}.db"
    if not graph_db.exists():
        raise click.ClickException(
            f"No graph plane at {graph_db}. Save graph-synced knowledge"
            " first (enable sync_graph in .parrot/wiki.json, then"
            " `wikitoolkit remember ...`)."
        )
    try:
        from parrot.knowledge.graphindex.assemble import GraphAssembler
        from parrot.knowledge.graphindex.factory import (
            HashingGraphEmbedder,
            make_stub_tenant_context,
        )
        from parrot.knowledge.graphindex.grounding import GroundingEvaluator
        from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever
    except ImportError as exc:
        raise click.ClickException(f"graphindex unavailable: {exc}") from exc

    async def _ground() -> dict[str, Any]:
        persistence = SQLitePersistence(config.graph_path(root))
        ctx = make_stub_tenant_context(config.wiki_name)
        nodes, edges = await persistence.load_graph(ctx)
        assembler = GraphAssembler(tenant_id=config.wiki_name)
        for node in nodes:
            assembler.add_node(node)
        for edge in edges:
            assembler.add_edge(edge)
        embedder = HashingGraphEmbedder()
        if nodes:
            await embedder.embed_nodes(nodes)
        retriever = GraphExpandedRetriever(
            graph=assembler.graph, nodes=nodes, embedder=embedder
        )
        result = await GroundingEvaluator(retriever).ground_claim(claim)
        return result.model_dump()

    data = _run(_ground())
    if as_json:
        click.echo(json.dumps(data, indent=2))
        return
    click.echo(f"Decision: {data['decision'].upper()}")
    click.echo(f"Reason:   {data['reason']}")
    if data.get("supported_paths"):
        click.echo("Evidence paths (stable edge ids):")
        for path in data["supported_paths"]:
            click.echo(f"  - {' ; '.join(path)}")
    if data.get("contradictions"):
        click.echo(f"Contradictions: {', '.join(data['contradictions'])}")
    for needed in data.get("required_evidence", []):
        click.echo(f"Required: {needed}")


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


# --------------------------------------------------------------------------
# Coding-agent integration commands (codex / claude / gemini)
# --------------------------------------------------------------------------


def _register_agent_command(name: str) -> None:
    """Create a ``wiki <agent> install|hook`` subcommand dynamically."""
    from parrot.knowledge.wiki import coding_agents

    @wiki.command(name)
    @click.option(
        "--path",
        type=click.Path(file_okay=False, path_type=Path),
        default=Path.cwd,
    )
    @click.argument("action", type=click.Choice(["install", "hook"]))
    def command(path: Path, action: str) -> None:
        """Install wiki integration or run its lifecycle hook."""
        if action == "hook":
            raise click.exceptions.Exit(coding_agents.hook(name))
        for item in coding_agents.install(name, path):
            click.echo(f"  ✓ {item}")


for _agent_name in ("codex", "claude", "gemini"):
    _register_agent_command(_agent_name)
