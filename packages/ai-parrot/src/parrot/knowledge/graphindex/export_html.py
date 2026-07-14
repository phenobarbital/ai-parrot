"""GraphIndex HTML export — interactive, self-contained knowledge-graph map.

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
"""

from __future__ import annotations

import html
import json
import logging
from importlib.resources import files as _resource_files
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids heavy imports
    import rustworkx

logger = logging.getLogger(__name__)

JSON_FILENAME = "graph.json"
HTML_FILENAME = "graph.html"

#: Default CDN used only when the vendored ECharts asset cannot be located.
ECHARTS_CDN_URL = "https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"

#: Deterministic, colour-blind-friendly palette for community categories.
#: Colours are assigned by community display order (largest first), so a
#: given partition always renders with the same colours.
_PALETTE: tuple[str, ...] = (
    "#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
    "#86bcb6", "#d37295", "#a0cbe8", "#ffbe7d", "#8cd17d",
    "#b6992d", "#499894", "#fabfd2", "#79706e", "#d4a6c8",
)

#: Colour used for nodes that belong to no detected community.
_UNCLUSTERED_COLOR = "#c8c8c8"
_UNCLUSTERED_LABEL = "Unclustered"

# Node-size scaling (pixels). God nodes are pushed toward the maximum.
_MIN_SYMBOL_SIZE = 8.0
_MAX_SYMBOL_SIZE = 46.0
_GOD_SYMBOL_BOOST = 10.0


def community_color(index: int) -> str:
    """Return the deterministic colour for a community display index.

    Args:
        index: Zero-based position of the community in display order.

    Returns:
        A hex colour string. Indices beyond the palette wrap around.
    """
    return _PALETTE[index % len(_PALETTE)]


class GraphExportNode(BaseModel):
    """A single node in the export payload / ECharts ``graph`` series.

    Field names ``id``/``name``/``category``/``symbolSize``/``value`` match the
    ECharts graph-series schema so the payload can be handed to ECharts with no
    remapping. The remaining fields feed the click-through detail panel.

    Args:
        id: The graph ``node_id``.
        name: Human-readable title shown as the node label.
        kind: :class:`NodeKind` value (e.g. ``"symbol"``, ``"concept"``).
        category: Index into the payload's ``categories`` list (community).
        symbolSize: Rendered node diameter in pixels (centrality-scaled).
        value: Ranking score (centrality when available, else degree).
        community_id: Stable id of the owning community, if any.
        community_label: Human-readable community label, if any.
        source_uri: Source artefact URI for the detail panel.
        summary: Optional short summary for the detail panel.
        provenance: How the node was created (``extracted``/``inferred``/...).
        degree: Total (in + out) degree in the graph.
        is_god: True when the node ranks among the top god nodes.
    """

    id: str
    name: str
    kind: str
    category: int
    symbolSize: float
    value: float = 0.0
    community_id: Optional[str] = None
    community_label: Optional[str] = None
    source_uri: str = ""
    summary: Optional[str] = None
    provenance: str = "extracted"
    degree: int = 0
    is_god: bool = False


class GraphExportEdge(BaseModel):
    """A single directed edge in the export payload / ECharts ``links``.

    Args:
        source: Tail ``node_id``.
        target: Head ``node_id``.
        kind: :class:`EdgeKind` value (e.g. ``"references"``).
        provenance: How the edge was created.
        confidence: Cosine similarity for inferred edges, else ``None``.
    """

    source: str
    target: str
    kind: str = "references"
    provenance: str = "extracted"
    confidence: Optional[float] = None


class GraphExportCategory(BaseModel):
    """A community category (an ECharts legend entry + colour).

    Args:
        index: Display index (also the value stored on member nodes).
        community_id: Stable community id, or ``None`` for the unclustered bin.
        label: Human-readable legend label.
        color: Hex colour shared by the legend swatch and member nodes.
        size: Number of member nodes.
    """

    index: int
    community_id: Optional[str]
    label: str
    color: str
    size: int


class GraphExportPayload(BaseModel):
    """The complete, serializable graph export.

    Serialized verbatim to ``graph.json`` and embedded into ``graph.html``.

    Args:
        title: Human-readable graph title shown in the page header.
        nodes: All exported nodes.
        edges: All exported edges.
        categories: Community categories in display order.
        god_node_ids: Ids of the highlighted god nodes (most connected).
        modularity: Global modularity Q of the partition, if known.
        meta: Free-form metadata (counts, generator, etc.).
    """

    title: str = "GraphIndex Knowledge Map"
    nodes: list[GraphExportNode] = Field(default_factory=list)
    edges: list[GraphExportEdge] = Field(default_factory=list)
    categories: list[GraphExportCategory] = Field(default_factory=list)
    god_node_ids: list[str] = Field(default_factory=list)
    modularity: Optional[float] = None
    meta: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Payload construction (pure — no analytics/communities imports required)
# ---------------------------------------------------------------------------


def _scale_symbol_size(value: float, max_value: float, is_god: bool) -> float:
    """Map a ranking score to a node diameter in pixels.

    Args:
        value: The node's ranking score (centrality or degree).
        max_value: The largest score across all nodes (for normalisation).
        is_god: Whether the node is a god node (gets a size boost).

    Returns:
        A diameter in ``[_MIN_SYMBOL_SIZE, _MAX_SYMBOL_SIZE]``.
    """
    if max_value <= 0.0:
        base = _MIN_SYMBOL_SIZE
    else:
        frac = max(0.0, min(1.0, value / max_value))
        base = _MIN_SYMBOL_SIZE + frac * (_MAX_SYMBOL_SIZE - _MIN_SYMBOL_SIZE)
    if is_god:
        base = min(_MAX_SYMBOL_SIZE, base + _GOD_SYMBOL_BOOST)
    return round(base, 2)


def build_export_payload(
    graph: "rustworkx.PyDiGraph",
    *,
    node_to_community: Optional[dict[str, str]] = None,
    community_order: Optional[list[str]] = None,
    community_labels: Optional[dict[str, str]] = None,
    community_sizes: Optional[dict[str, int]] = None,
    god_scores: Optional[dict[str, float]] = None,
    god_node_ids: Optional[list[str]] = None,
    title: str = "GraphIndex Knowledge Map",
    modularity: Optional[float] = None,
) -> GraphExportPayload:
    """Build a :class:`GraphExportPayload` from an assembled graph.

    Pure and deterministic: it reads only the node/edge payload dicts stored on
    the ``rustworkx.PyDiGraph`` plus the plain community/god-node lookups, so it
    needs neither the analytics nor the communities modules. :func:`export_graph`
    supplies these lookups from the richer result objects.

    Args:
        graph: The assembled ``rustworkx.PyDiGraph``. Node payloads must be
            dicts carrying at least ``node_id``, ``kind`` and ``title``; edge
            payloads carry ``source_id``/``target_id``/``kind``.
        node_to_community: Map ``node_id`` → ``community_id``. Nodes absent from
            this map are placed in the ``Unclustered`` category.
        community_order: Community ids in display order (largest first). Defines
            the colour assignment. Ids missing here are appended in first-seen
            order.
        community_labels: Map ``community_id`` → human-readable label.
        community_sizes: Map ``community_id`` → member count (for the legend).
        god_scores: Map ``node_id`` → centrality score used for node sizing.
        god_node_ids: Ids to flag as god nodes (highlighted + size boost).
        title: Graph title for the page header.
        modularity: Global modularity Q, recorded in metadata.

    Returns:
        A fully populated :class:`GraphExportPayload`.
    """
    node_to_community = node_to_community or {}
    community_labels = community_labels or {}
    community_sizes = community_sizes or {}
    god_scores = god_scores or {}
    god_ids = set(god_node_ids or [])

    # --- Establish the community display order → category index mapping. ---
    ordered_cids: list[str] = list(community_order or [])
    seen_cids = set(ordered_cids)
    for cid in node_to_community.values():
        if cid not in seen_cids:
            ordered_cids.append(cid)
            seen_cids.add(cid)
    cid_to_index: dict[str, int] = {cid: i for i, cid in enumerate(ordered_cids)}

    # --- Degree lookup (in + out) keyed by node_id. ---
    degree_by_id: dict[str, int] = {}
    for idx in graph.node_indices():
        payload = graph[idx]
        if not isinstance(payload, dict):
            continue
        nid = payload.get("node_id")
        if not nid:
            continue
        degree_by_id[nid] = graph.in_degree(idx) + graph.out_degree(idx)

    # --- Build nodes. ---
    export_nodes: list[GraphExportNode] = []
    used_cids: set[str] = set()
    max_score = max(god_scores.values(), default=0.0)
    max_degree = float(max(degree_by_id.values(), default=0))

    for idx in graph.node_indices():
        payload = graph[idx]
        if not isinstance(payload, dict):
            continue
        nid = payload.get("node_id")
        if not nid:
            continue
        cid = node_to_community.get(nid)
        if cid is not None and cid in cid_to_index:
            category = cid_to_index[cid]
            used_cids.add(cid)
            clabel = community_labels.get(cid)
        else:
            cid = None
            category = len(ordered_cids)  # the unclustered bin
            clabel = None
        is_god = nid in god_ids
        # Prefer centrality for sizing; fall back to normalised degree.
        if god_scores:
            score = god_scores.get(nid, 0.0)
            symbol_size = _scale_symbol_size(score, max_score, is_god)
            value = score
        else:
            deg = float(degree_by_id.get(nid, 0))
            symbol_size = _scale_symbol_size(deg, max_degree, is_god)
            value = deg
        export_nodes.append(
            GraphExportNode(
                id=nid,
                name=payload.get("title", nid),
                kind=str(payload.get("kind", "")),
                category=category,
                symbolSize=symbol_size,
                value=round(float(value), 6),
                community_id=cid,
                community_label=clabel,
                source_uri=payload.get("source_uri", "") or "",
                summary=payload.get("summary"),
                provenance=str(payload.get("provenance", "extracted")),
                degree=degree_by_id.get(nid, 0),
                is_god=is_god,
            )
        )

    # --- Build categories in display order, then the unclustered bin. ---
    categories: list[GraphExportCategory] = []
    for i, cid in enumerate(ordered_cids):
        categories.append(
            GraphExportCategory(
                index=i,
                community_id=cid,
                label=community_labels.get(cid) or f"Community {i + 1}",
                color=community_color(i),
                size=community_sizes.get(
                    cid, sum(1 for n in export_nodes if n.community_id == cid)
                ),
            )
        )
    unclustered_size = sum(1 for n in export_nodes if n.community_id is None)
    if unclustered_size:
        categories.append(
            GraphExportCategory(
                index=len(ordered_cids),
                community_id=None,
                label=_UNCLUSTERED_LABEL,
                color=_UNCLUSTERED_COLOR,
                size=unclustered_size,
            )
        )

    # --- Build edges. ---
    export_edges: list[GraphExportEdge] = []
    for _src, _tgt, epayload in graph.weighted_edge_list():
        if not isinstance(epayload, dict):
            continue
        source = epayload.get("source_id")
        target = epayload.get("target_id")
        if not source or not target:
            continue
        export_edges.append(
            GraphExportEdge(
                source=source,
                target=target,
                kind=str(epayload.get("kind", "references")),
                provenance=str(epayload.get("provenance", "extracted")),
                confidence=epayload.get("confidence"),
            )
        )

    return GraphExportPayload(
        title=title,
        nodes=export_nodes,
        edges=export_edges,
        categories=categories,
        god_node_ids=[n.id for n in export_nodes if n.is_god],
        modularity=modularity,
        meta={
            "node_count": len(export_nodes),
            "edge_count": len(export_edges),
            "community_count": len(ordered_cids),
            "generated_by": "parrot.knowledge.graphindex.export_html",
        },
    )


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def write_graph_json(payload: GraphExportPayload, output_dir: Path) -> Path:
    """Write ``graph.json`` to ``output_dir``.

    Args:
        payload: The export payload.
        output_dir: Destination directory (created if missing).

    Returns:
        The path to the written ``graph.json``.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / JSON_FILENAME
    path.write_text(
        json.dumps(payload.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Wrote %s (%d nodes, %d edges)", path, len(payload.nodes), len(payload.edges))
    return path


def _locate_echarts_asset() -> Optional[str]:
    """Return the inline JS of the vendored ECharts asset, if available.

    Looks up ``echarts.min.js`` shipped by ``ai-parrot-visualizations`` under
    the ``parrot.outputs.formats.assets`` namespace package.

    Returns:
        The JavaScript source as a string, or ``None`` when not found.
    """
    try:
        resource = _resource_files("parrot.outputs.formats.assets") / "echarts.min.js"
        if resource.is_file():
            return resource.read_text(encoding="utf-8")
    except (ModuleNotFoundError, FileNotFoundError, OSError) as exc:
        logger.debug("Vendored ECharts asset not available: %s", exc)
    return None


def _render_html(payload: GraphExportPayload, echarts_script_tag: str) -> str:
    """Render the full ``graph.html`` document.

    Args:
        payload: The export payload to embed.
        echarts_script_tag: A complete ``<script>...</script>`` tag providing
            the ECharts runtime (inline asset or CDN reference).

    Returns:
        The complete HTML document as a string.
    """
    # Embed the payload inside an inline <script>. Node summaries can contain
    # arbitrary source text — including the literal "</script>" (any web or
    # template repo) — which would otherwise close the script tag early and
    # dump the rest of the page as raw text. "<", ">" and "&" only ever occur
    # inside JSON *string* values (JSON structure never uses them), so escaping
    # them to \uXXXX yields equivalent JSON that JSON.parse restores exactly.
    # U+2028/U+2029 are valid JSON but break JS string parsing when embedded
    # raw (ensure_ascii=False leaves them literal), so escape them too.
    payload_json = (
        json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )
    safe_title = html.escape(payload.title)
    node_count = len(payload.nodes)
    edge_count = len(payload.edges)
    community_count = sum(1 for c in payload.categories if c.community_id is not None)
    god_count = len(payload.god_node_ids)
    modularity = "n/a" if payload.modularity is None else f"{payload.modularity:.4f}"

    return _HTML_TEMPLATE.format(
        title=safe_title,
        echarts_script_tag=echarts_script_tag,
        payload_json=payload_json,
        node_count=node_count,
        edge_count=edge_count,
        community_count=community_count,
        god_count=god_count,
        modularity=modularity,
    )


def write_graph_html(
    payload: GraphExportPayload,
    output_dir: Path,
    *,
    echarts_js: Optional[str] = None,
    allow_cdn_fallback: bool = True,
) -> Path:
    """Write a self-contained ``graph.html`` to ``output_dir``.

    Args:
        payload: The export payload.
        output_dir: Destination directory (created if missing).
        echarts_js: Explicit ECharts runtime JavaScript to inline. When
            ``None``, the vendored asset is located automatically.
        allow_cdn_fallback: When the asset cannot be located and this is True,
            reference the ECharts CDN and log a warning (the page then needs
            network access). When False, raise instead.

    Returns:
        The path to the written ``graph.html``.

    Raises:
        RuntimeError: When no ECharts runtime is available and CDN fallback is
            disabled.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    js = echarts_js if echarts_js is not None else _locate_echarts_asset()
    if js is not None:
        # Inline the runtime so the page is fully offline.
        script_tag = f"<script>{js}</script>"
    elif allow_cdn_fallback:
        logger.warning(
            "Vendored ECharts asset not found; falling back to CDN %s. "
            "The generated graph.html will require network access. Install "
            "ai-parrot-visualizations for a fully offline export.",
            ECHARTS_CDN_URL,
        )
        script_tag = f'<script src="{ECHARTS_CDN_URL}"></script>'
    else:
        raise RuntimeError(
            "ECharts runtime unavailable and CDN fallback disabled; "
            "pass echarts_js= or install ai-parrot-visualizations."
        )

    path = output_dir / HTML_FILENAME
    path.write_text(_render_html(payload, script_tag), encoding="utf-8")
    logger.info("Wrote interactive graph to %s", path)
    return path


# ---------------------------------------------------------------------------
# High-level convenience (adapts CommunitiesResult / AnalyticsResult)
# ---------------------------------------------------------------------------


def export_graph(
    graph: "rustworkx.PyDiGraph",
    output_dir: Path,
    *,
    communities: Optional[Any] = None,
    analytics: Optional[Any] = None,
    god_top_k: int = 15,
    title: str = "GraphIndex Knowledge Map",
    echarts_js: Optional[str] = None,
    allow_cdn_fallback: bool = True,
) -> tuple[Path, Path]:
    """Build the payload and write both ``graph.json`` and ``graph.html``.

    Adapts a ``CommunitiesResult`` and an ``AnalyticsResult`` into the plain
    lookups :func:`build_export_payload` consumes, then writes both artefacts.

    Args:
        graph: The assembled ``rustworkx.PyDiGraph``.
        output_dir: Destination directory.
        communities: Optional ``CommunitiesResult`` for node colouring/labels.
        analytics: Optional ``AnalyticsResult`` whose ``god_nodes`` drive node
            sizing and highlighting.
        god_top_k: Number of top god nodes to highlight.
        title: Graph title for the page header.
        echarts_js: Explicit ECharts runtime to inline (else auto-located).
        allow_cdn_fallback: See :func:`write_graph_html`.

    Returns:
        ``(html_path, json_path)``.
    """
    node_to_community: dict[str, str] = {}
    community_order: list[str] = []
    community_labels: dict[str, str] = {}
    community_sizes: dict[str, int] = {}
    modularity: Optional[float] = None

    if communities is not None:
        node_to_community = dict(getattr(communities, "node_to_community", {}) or {})
        modularity = getattr(communities, "modularity", None)
        for community in getattr(communities, "communities", []) or []:
            cid = community.community_id
            community_order.append(cid)
            community_sizes[cid] = community.size
            label = getattr(community, "label", "") or ""
            if not label:
                top = getattr(community, "top_titles", None) or []
                label = top[0] if top else cid[:8]
            community_labels[cid] = label

    god_scores: dict[str, float] = {}
    god_node_ids: list[str] = []
    if analytics is not None:
        for entry in (getattr(analytics, "god_nodes", None) or [])[:god_top_k]:
            nid = entry.get("node_id")
            if not nid:
                continue
            # Prefer betweenness, then eigenvector, then any 'centrality_score'.
            score = (
                entry.get("betweenness")
                or entry.get("eigenvector")
                or entry.get("centrality_score")
                or 0.0
            )
            god_scores[nid] = float(score)
            god_node_ids.append(nid)

    payload = build_export_payload(
        graph,
        node_to_community=node_to_community,
        community_order=community_order,
        community_labels=community_labels,
        community_sizes=community_sizes,
        god_scores=god_scores,
        god_node_ids=god_node_ids,
        title=title,
        modularity=modularity,
    )

    json_path = write_graph_json(payload, output_dir)
    html_path = write_graph_html(
        payload,
        output_dir,
        echarts_js=echarts_js,
        allow_cdn_fallback=allow_cdn_fallback,
    )
    return html_path, json_path


# ---------------------------------------------------------------------------
# HTML template (single-file, offline, theme-aware)
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
    Roboto, Helvetica, Arial, sans-serif; background: #f7f8fa; color: #1f2328;
  }}
  header {{
    padding: 12px 18px; background: #22272e; color: #f0f3f6;
    display: flex; flex-wrap: wrap; align-items: baseline; gap: 16px;
  }}
  header h1 {{ font-size: 16px; margin: 0; font-weight: 600; }}
  header .stats {{ font-size: 12px; opacity: 0.85; display: flex; gap: 14px; flex-wrap: wrap; }}
  header .stats b {{ color: #7ee3c1; font-weight: 600; }}
  #wrap {{ display: flex; height: calc(100vh - 49px); }}
  #chart {{ flex: 1 1 auto; min-width: 0; }}
  #side {{
    width: 320px; flex: 0 0 320px; border-left: 1px solid #d0d7de;
    background: #ffffff; overflow-y: auto; padding: 14px;
  }}
  #search {{
    width: 100%; padding: 8px 10px; border: 1px solid #d0d7de; border-radius: 6px;
    font-size: 13px; margin-bottom: 10px;
  }}
  .panel-title {{ font-size: 12px; text-transform: uppercase; letter-spacing: .04em;
    color: #656d76; margin: 10px 0 6px; }}
  #detail {{ font-size: 13px; line-height: 1.5; }}
  #detail .empty {{ color: #8b949e; }}
  #detail .k {{ color: #656d76; }}
  #detail .badge {{ display: inline-block; padding: 1px 7px; border-radius: 10px;
    font-size: 11px; color: #fff; margin-left: 4px; }}
  #detail pre {{ white-space: pre-wrap; word-break: break-word; background: #f6f8fa;
    padding: 8px; border-radius: 6px; font-size: 12px; }}
  #results {{ list-style: none; padding: 0; margin: 0; max-height: 40vh; overflow-y: auto; }}
  #results li {{ padding: 6px 8px; border-radius: 5px; cursor: pointer; font-size: 13px;
    display: flex; align-items: center; gap: 7px; }}
  #results li:hover {{ background: #f0f3f6; }}
  #results .dot {{ width: 9px; height: 9px; border-radius: 50%; flex: 0 0 9px; }}
  #results .gd {{ font-size: 10px; color: #e15759; font-weight: 700; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #0d1117; color: #e6edf3; }}
    #side {{ background: #161b22; border-color: #30363d; }}
    #search {{ background: #0d1117; color: #e6edf3; border-color: #30363d; }}
    #detail pre {{ background: #0d1117; }}
    #results li:hover {{ background: #21262d; }}
  }}
</style>
{echarts_script_tag}
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="stats">
    <span><b>{node_count}</b> nodes</span>
    <span><b>{edge_count}</b> edges</span>
    <span><b>{community_count}</b> communities</span>
    <span><b>{god_count}</b> god nodes</span>
    <span>modularity <b>{modularity}</b></span>
  </div>
</header>
<div id="wrap">
  <div id="chart"></div>
  <aside id="side">
    <input id="search" type="search" placeholder="Search concepts…" autocomplete="off"/>
    <div class="panel-title">Selection</div>
    <div id="detail"><span class="empty">Click a node to inspect it.</span></div>
    <div class="panel-title">Matches</div>
    <ul id="results"></ul>
  </aside>
</div>
<script>
const GRAPH = {payload_json};
const catColor = i => (GRAPH.categories[i] && GRAPH.categories[i].color) || "#888";
const nodeById = {{}};
GRAPH.nodes.forEach(n => {{ nodeById[n.id] = n; }});

const chart = echarts.init(document.getElementById("chart"), null, {{ renderer: "canvas" }});
const option = {{
  tooltip: {{
    confine: true,
    formatter: p => p.dataType === "node"
      ? `<b>${{p.data.name}}</b><br/>${{p.data.kind}}` +
        (p.data.community_label ? `<br/><span style="opacity:.7">${{p.data.community_label}}</span>` : "")
      : `${{p.data.kind || "edge"}}`
  }},
  legend: [{{
    type: "scroll", top: 6, left: 6, right: 6,
    data: GRAPH.categories.map(c => c.label),
    textStyle: {{ color: getComputedStyle(document.body).color }}
  }}],
  series: [{{
    type: "graph", layout: "force", roam: true, draggable: true,
    focusNodeAdjacency: true,
    label: {{ show: GRAPH.nodes.length <= 250, position: "right", fontSize: 11,
      color: getComputedStyle(document.body).color, formatter: "{{b}}" }},
    labelLayout: {{ hideOverlap: true }},
    force: {{ repulsion: 140, edgeLength: [50, 190], gravity: 0.06, friction: 0.16 }},
    lineStyle: {{ color: "source", opacity: 0.45, curveness: 0.08, width: 1 }},
    emphasis: {{ focus: "adjacency", lineStyle: {{ width: 2.5, opacity: 0.9 }} }},
    categories: GRAPH.categories.map(c => ({{ name: c.label, itemStyle: {{ color: c.color }} }})),
    data: GRAPH.nodes.map(n => ({{
      id: n.id, name: n.name, category: n.category, value: n.value,
      symbolSize: n.symbolSize,
      itemStyle: {{ borderColor: n.is_god ? "#e15759" : "rgba(0,0,0,0.25)",
        borderWidth: n.is_god ? 2.5 : 0.6 }}
    }})),
    links: GRAPH.edges.map(e => ({{
      source: e.source, target: e.target,
      lineStyle: e.provenance === "inferred" ? {{ type: "dashed" }} : {{}}
    }}))
  }}]
}};
chart.setOption(option);
window.addEventListener("resize", () => chart.resize());

const detail = document.getElementById("detail");
function showDetail(n) {{
  const cat = GRAPH.categories[n.category];
  const color = cat ? cat.color : "#888";
  detail.innerHTML =
    `<div style="font-weight:600;font-size:14px">${{esc(n.name)}}` +
      (n.is_god ? `<span class="badge" style="background:#e15759">GOD</span>` : "") + `</div>` +
    `<div><span class="badge" style="background:${{color}}">${{esc(cat ? cat.label : "—")}}</span> ` +
      `<span class="badge" style="background:#57606a">${{esc(n.kind)}}</span></div>` +
    `<div style="margin-top:6px"><span class="k">provenance:</span> ${{esc(n.provenance)}} ` +
      `&middot; <span class="k">degree:</span> ${{n.degree}}</div>` +
    (n.source_uri ? `<div><span class="k">source:</span> ${{esc(n.source_uri)}}</div>` : "") +
    (n.summary ? `<pre>${{esc(n.summary)}}</pre>` : "");
}}
function esc(s) {{
  return String(s == null ? "" : s).replace(/[&<>"]/g, c =>
    ({{ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }}[c]));
}}
chart.on("click", p => {{ if (p.dataType === "node" && nodeById[p.data.id]) showDetail(nodeById[p.data.id]); }});

const results = document.getElementById("results");
const search = document.getElementById("search");
function renderResults(q) {{
  q = q.trim().toLowerCase();
  results.innerHTML = "";
  if (!q) return;
  const hits = GRAPH.nodes
    .filter(n => n.name.toLowerCase().includes(q))
    .sort((a, b) => b.value - a.value).slice(0, 40);
  hits.forEach(n => {{
    const li = document.createElement("li");
    const dot = `<span class="dot" style="background:${{catColor(n.category)}}"></span>`;
    li.innerHTML = dot + `<span>${{esc(n.name)}}</span>` + (n.is_god ? ` <span class="gd">god</span>` : "");
    li.onclick = () => {{
      showDetail(n);
      chart.dispatchAction({{ type: "focusNodeAdjacency", seriesIndex: 0, dataIndex: idxOf(n.id) }});
      chart.dispatchAction({{ type: "highlight", seriesIndex: 0, dataIndex: idxOf(n.id) }});
    }};
    results.appendChild(li);
  }});
}}
const idOrder = GRAPH.nodes.map(n => n.id);
function idxOf(id) {{ return idOrder.indexOf(id); }}
search.addEventListener("input", e => renderResults(e.target.value));
</script>
</body>
</html>
"""
