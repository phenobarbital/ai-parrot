---
type: Wiki Summary
title: parrot.knowledge.graphindex.cli
id: mod:parrot.knowledge.graphindex.cli
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: GraphIndex CLI — build a knowledge graph from a code repository.
relates_to:
- concept: func:parrot.knowledge.graphindex.cli.build_code_graph
  rel: defines
- concept: func:parrot.knowledge.graphindex.cli.discover_python_files
  rel: defines
- concept: func:parrot.knowledge.graphindex.cli.main
  rel: defines
- concept: mod:parrot.knowledge.graphindex.analytics
  rel: references
- concept: mod:parrot.knowledge.graphindex.assemble
  rel: references
- concept: mod:parrot.knowledge.graphindex.communities
  rel: references
- concept: mod:parrot.knowledge.graphindex.export_html
  rel: references
- concept: mod:parrot.knowledge.graphindex.extractors.code
  rel: references
- concept: mod:parrot.knowledge.graphindex.schema
  rel: references
---

# `parrot.knowledge.graphindex.cli`

GraphIndex CLI — build a knowledge graph from a code repository.

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

## Functions

- `def discover_python_files(root: Path, ignore_spec: Optional[pathspec.PathSpec]=None) -> list[Path]` — Recursively find Python source files under ``root``.
- `async def build_code_graph(paths: Sequence[Path], output_dir: Path, *, tenant_id: str='default', detect_comms: bool=True, community_resolution: float=1.0, ignore_file: Optional[Path]=None, title: Optional[str]=None, allow_cdn_fallback: bool=True) -> dict` — Build the code knowledge graph and write the ``graphindex`` artefacts.
- `def main(argv: Optional[Sequence[str]]=None) -> int` — CLI entry point.
