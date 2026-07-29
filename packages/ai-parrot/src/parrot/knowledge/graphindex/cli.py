"""GraphIndex CLI — build a knowledge graph from a code repository.

A local-first, Graphify-style command that turns an existing code repository
into a ``graphindex`` directory containing:

* ``graph.html``   — an interactive, clickable force-directed map (communities
  as colours, god nodes highlighted);
* ``graph.json``   — the serialized graph for programmatic reuse;
* ``GRAPH_REPORT.md`` — a deterministic report (god nodes, communities,
  surprising connections, suggested questions).

The code pass is **deterministic and LLM-free**: files are parsed with
tree-sitter, the graph is assembled in-process with ``rustworkx``, communities
come from Louvain, and centrality identifies god nodes. Nothing leaves the
machine and no API keys, database, or embedding model are required.

Usage::

    parrot-graphindex .                     # index the current repo
    parrot-graphindex ./src -o ./graphindex # choose the output directory
    parrot-graphindex . --no-communities    # skip community detection
    python -m parrot.knowledge.graphindex .

The heavy semantic pass over docs/PDFs/media (which does use a model) lives in
the full :class:`~parrot.knowledge.graphindex.builder.GraphIndexBuilder`
pipeline; this CLI intentionally covers only the local code path.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

import pathspec

from parrot.knowledge.graphindex.analytics import compute_analytics, generate_report
from parrot.knowledge.graphindex.assemble import GraphAssembler
from parrot.knowledge.graphindex.communities import detect_communities
from parrot.knowledge.graphindex.export_html import export_graph
from parrot.knowledge.graphindex.extractors.code import CodeExtractor
from parrot.knowledge.graphindex.schema import UniversalEdge, UniversalNode

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIRNAME = "graphindex"

#: Directories skipped during discovery regardless of any ignore file.
_ALWAYS_SKIP: frozenset[str] = frozenset({
    ".git", ".hg", ".svn", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".venv", "venv", "node_modules", ".tox", "build", "dist",
    ".eggs", ".idea", ".vscode",
})


def discover_python_files(
    root: Path, ignore_spec: Optional[pathspec.PathSpec] = None
) -> list[Path]:
    """Recursively find Python source files under ``root``.

    Skips well-known noise directories (``.git``, ``__pycache__``,
    ``node_modules``, virtualenvs, build output, …) and any path matching the
    optional gitignore-style ``ignore_spec``.

    Args:
        root: Repository root (or a single ``.py`` file).
        ignore_spec: Optional compiled ``pathspec`` for ``.graphindexignore``.

    Returns:
        A sorted list of ``.py`` file paths (deterministic order).
    """
    if root.is_file():
        return [root] if root.suffix == ".py" else []

    files: list[Path] = []
    for path in root.rglob("*.py"):
        if any(part in _ALWAYS_SKIP for part in path.relative_to(root).parts):
            continue
        if ignore_spec is not None:
            rel = path.relative_to(root).as_posix()
            if ignore_spec.match_file(rel):
                continue
        files.append(path)
    return sorted(files)


async def build_code_graph(
    paths: Sequence[Path],
    output_dir: Path,
    *,
    tenant_id: str = "default",
    detect_comms: bool = True,
    community_resolution: float = 1.0,
    ignore_file: Optional[Path] = None,
    title: Optional[str] = None,
    allow_cdn_fallback: bool = True,
) -> dict:
    """Build the code knowledge graph and write the ``graphindex`` artefacts.

    Args:
        paths: Repository roots and/or individual ``.py`` files to index.
        output_dir: Directory to write ``graph.html`` / ``graph.json`` /
            ``GRAPH_REPORT.md`` into (created if missing).
        tenant_id: Tenant id used for node namespacing.
        detect_comms: Whether to run Louvain community detection.
        community_resolution: Louvain γ resolution (>1.0 → smaller communities).
        ignore_file: Optional ``.graphindexignore`` path (gitignore syntax).
        title: Graph title shown in the page header; defaults to the first
            path's name.
        allow_cdn_fallback: Fall back to the ECharts CDN when the vendored
            offline asset is unavailable.

    Returns:
        A summary dict with counts, output paths, top god nodes and top
        communities.
    """
    ignore_spec: Optional[pathspec.PathSpec] = None
    if ignore_file is not None and ignore_file.is_file():
        ignore_spec = pathspec.PathSpec.from_lines(
            "gitwildmatch", ignore_file.read_text(encoding="utf-8").splitlines()
        )

    extractor = CodeExtractor(
        ignore_file=str(ignore_file) if ignore_file else None
    )

    all_nodes: list[UniversalNode] = []
    all_edges: list[UniversalEdge] = []
    files_indexed = 0
    errors: list[str] = []

    for base in paths:
        base = base.resolve()
        discovery_root = base if base.is_dir() else base.parent
        for file_path in discover_python_files(base, ignore_spec):
            try:
                source = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                errors.append(f"read failed: {file_path}: {exc}")
                continue
            try:
                rel = file_path.relative_to(discovery_root).as_posix()
            except ValueError:
                rel = str(file_path)
            nodes, edges = await extractor.extract(rel, source)
            all_nodes.extend(nodes)
            all_edges.extend(edges)
            files_indexed += 1

    logger.info(
        "Extracted %d nodes and %d edges from %d files",
        len(all_nodes), len(all_edges), files_indexed,
    )

    assembler = GraphAssembler(tenant_id=tenant_id)
    assembler.add_nodes(all_nodes)
    assembler.add_edges(all_edges)

    communities = None
    if detect_comms and assembler.graph.num_nodes() > 0:
        communities = detect_communities(
            assembler.graph,
            all_nodes,
            resolution=community_resolution,
            write_back_to_nodes=False,
        )

    analytics = compute_analytics(assembler.graph, all_nodes, all_edges)
    analytics.communities = communities

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report_path = generate_report(analytics, output_dir, tenant_id=tenant_id)
    html_path, json_path = export_graph(
        assembler.graph,
        output_dir,
        communities=communities,
        analytics=analytics,
        title=title or f"GraphIndex — {Path(paths[0]).resolve().name}",
        allow_cdn_fallback=allow_cdn_fallback,
    )

    return {
        "files_indexed": files_indexed,
        "node_count": assembler.graph.num_nodes(),
        "edge_count": assembler.graph.num_edges(),
        "community_count": len(communities.communities) if communities else 0,
        "modularity": communities.modularity if communities else None,
        "graph_html": str(html_path),
        "graph_json": str(json_path),
        "report": str(report_path),
        "god_nodes": analytics.god_nodes[:10],
        "communities": (
            [
                {"label": c.label or c.community_id[:8], "size": c.size}
                for c in communities.communities[:10]
            ]
            if communities
            else []
        ),
        "errors": errors,
    }


def _print_summary(summary: dict, output_dir: Path) -> None:
    """Print a human-readable run summary to stdout.

    Args:
        summary: The dict returned by :func:`build_code_graph`.
        output_dir: The output directory (for the closing hint).
    """
    print(f"\nGraphIndex built for {summary['files_indexed']} file(s):")
    print(f"  nodes:       {summary['node_count']}")
    print(f"  edges:       {summary['edge_count']}")
    if summary["modularity"] is not None:
        print(
            f"  communities: {summary['community_count']} "
            f"(modularity {summary['modularity']:.4f})"
        )
    if summary["god_nodes"]:
        print("\nGod nodes (most connected):")
        for i, node in enumerate(summary["god_nodes"][:5], start=1):
            print(f"  {i}. {node.get('title', '?')}  [{node.get('kind', '')}]")
    if summary["communities"]:
        print("\nTop communities:")
        for comm in summary["communities"][:5]:
            print(f"  • {comm['label']}  ({comm['size']} nodes)")
    print("\nArtifacts:")
    print(f"  {summary['graph_html']}")
    print(f"  {summary['graph_json']}")
    print(f"  {summary['report']}")
    if summary["errors"]:
        print(f"\n{len(summary['errors'])} non-fatal error(s) during indexing.")
    print(f"\nOpen {Path(summary['graph_html'])} in a browser to explore.")


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser."""
    parser = argparse.ArgumentParser(
        prog="parrot-graphindex",
        description=(
            "Build an interactive knowledge graph (graph.html + graph.json + "
            "GRAPH_REPORT.md) from a code repository — local-first, no LLM."
        ),
    )
    parser.add_argument(
        "path", nargs="?", default=".",
        help="Repository root or file to index (default: current directory).",
    )
    parser.add_argument(
        "-o", "--output", default=None,
        help=(
            "Output directory for the artefacts "
            f"(default: <path>/{DEFAULT_OUTPUT_DIRNAME})."
        ),
    )
    parser.add_argument(
        "--tenant", default="default", help="Tenant id for node namespacing."
    )
    parser.add_argument(
        "--no-communities", action="store_true",
        help="Skip Louvain community detection (nodes render uncoloured).",
    )
    parser.add_argument(
        "--resolution", type=float, default=1.0,
        help="Louvain resolution γ (>1.0 finds smaller/tighter communities).",
    )
    parser.add_argument(
        "--ignore-file", default=None,
        help="Path to a .graphindexignore file (gitignore syntax).",
    )
    parser.add_argument("--title", default=None, help="Graph title for the page header.")
    parser.add_argument(
        "--no-cdn-fallback", action="store_true",
        help="Fail instead of referencing the ECharts CDN when the offline "
             "asset is unavailable.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging."
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (0 on success, non-zero on error).
    """
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    target = Path(args.path)
    if not target.exists():
        print(f"error: path does not exist: {target}", file=sys.stderr)
        return 2

    default_base = target if target.is_dir() else target.parent
    output_dir = Path(args.output) if args.output else default_base / DEFAULT_OUTPUT_DIRNAME
    ignore_file = Path(args.ignore_file) if args.ignore_file else None

    try:
        summary = asyncio.run(
            build_code_graph(
                [target],
                output_dir,
                tenant_id=args.tenant,
                detect_comms=not args.no_communities,
                community_resolution=args.resolution,
                ignore_file=ignore_file,
                title=args.title,
                allow_cdn_fallback=not args.no_cdn_fallback,
            )
        )
    except Exception as exc:  # noqa: BLE001 — surface a clean CLI error
        logger.error("GraphIndex build failed: %s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if summary["node_count"] == 0:
        print("No Python files found to index.", file=sys.stderr)
        return 1

    _print_summary(summary, output_dir)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
