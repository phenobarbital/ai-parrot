---
type: Wiki Summary
title: parrot.knowledge.graphindex.export_html
id: mod:parrot.knowledge.graphindex.export_html
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: GraphIndex HTML export — interactive, self-contained knowledge-graph map.
relates_to:
- concept: class:parrot.knowledge.graphindex.export_html.GraphExportCategory
  rel: defines
- concept: class:parrot.knowledge.graphindex.export_html.GraphExportEdge
  rel: defines
- concept: class:parrot.knowledge.graphindex.export_html.GraphExportNode
  rel: defines
- concept: class:parrot.knowledge.graphindex.export_html.GraphExportPayload
  rel: defines
- concept: func:parrot.knowledge.graphindex.export_html.build_export_payload
  rel: defines
- concept: func:parrot.knowledge.graphindex.export_html.community_color
  rel: defines
- concept: func:parrot.knowledge.graphindex.export_html.export_graph
  rel: defines
- concept: func:parrot.knowledge.graphindex.export_html.write_graph_html
  rel: defines
- concept: func:parrot.knowledge.graphindex.export_html.write_graph_json
  rel: defines
---

# `parrot.knowledge.graphindex.export_html`

GraphIndex HTML export — interactive, self-contained knowledge-graph map.

Emits two sibling artefacts from an assembled :class:`rustworkx.PyDiGraph`:

* ``graph.json`` — the serialized graph (nodes, edges, communities) for
  programmatic reuse, mirroring Graphify's ``graph.json`` artefact.
* ``graph.html`` — a fully offline, clickable force-directed visualization.
  Every node is a concept, its colour is the detected community, and its size
  scales with centrality so "god nodes" (the most-connected concepts) stand
  out. Clicking a node opens a detail panel; the legend toggles communities;
  a search box filters nodes by title.

Design goals mirror the rest of GraphIndex:

* **Deterministic** — no LLM calls; community colours come from a fixed
  palette keyed by display order, so the same graph renders identically.
* **Local-first** — the ECharts runtime is inlined from the vendored asset
  shipped by ``ai-parrot-visualizations`` (``parrot.outputs.formats.assets``),
  so the produced page works with no network access ("nothing leaves your
  machine"). A CDN ``<script>`` fallback is emitted only when the asset cannot
  be located, accompanied by a logged warning.

The public surface is intentionally decoupled from the analytics/communities
models: :func:`build_export_payload` accepts plain dicts/lists so it can be
unit-tested without those modules, while :func:`export_graph` adapts a
``CommunitiesResult`` / ``AnalyticsResult`` into that payload and writes both
files in one call (used by the builder and the agent toolkit).

## Classes

- **`GraphExportNode(BaseModel)`** — A single node in the export payload / ECharts ``graph`` series.
- **`GraphExportEdge(BaseModel)`** — A single directed edge in the export payload / ECharts ``links``.
- **`GraphExportCategory(BaseModel)`** — A community category (an ECharts legend entry + colour).
- **`GraphExportPayload(BaseModel)`** — The complete, serializable graph export.

## Functions

- `def community_color(index: int) -> str` — Return the deterministic colour for a community display index.
- `def build_export_payload(graph: 'rustworkx.PyDiGraph', *, node_to_community: Optional[dict[str, str]]=None, community_order: Optional[list[str]]=None, community_labels: Optional[dict[str, str]]=None, community_sizes: Optional[dict[str, int]]=None, god_scores: Optional[dict[str, float]]=None, god_node_ids: Optional[list[str]]=None, title: str='GraphIndex Knowledge Map', modularity: Optional[float]=None) -> GraphExportPayload` — Build a :class:`GraphExportPayload` from an assembled graph.
- `def write_graph_json(payload: GraphExportPayload, output_dir: Path) -> Path` — Write ``graph.json`` to ``output_dir``.
- `def write_graph_html(payload: GraphExportPayload, output_dir: Path, *, echarts_js: Optional[str]=None, allow_cdn_fallback: bool=True) -> Path` — Write a self-contained ``graph.html`` to ``output_dir``.
- `def export_graph(graph: 'rustworkx.PyDiGraph', output_dir: Path, *, communities: Optional[Any]=None, analytics: Optional[Any]=None, god_top_k: int=15, title: str='GraphIndex Knowledge Map', echarts_js: Optional[str]=None, allow_cdn_fallback: bool=True) -> tuple[Path, Path]` — Build the payload and write both ``graph.json`` and ``graph.html``.
