---
type: Concept
title: build_code_graph()
id: func:parrot.knowledge.graphindex.cli.build_code_graph
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Build the code knowledge graph and write the ``graphindex`` artefacts.
---

# build_code_graph

```python
async def build_code_graph(paths: Sequence[Path], output_dir: Path, *, tenant_id: str='default', detect_comms: bool=True, community_resolution: float=1.0, ignore_file: Optional[Path]=None, title: Optional[str]=None, allow_cdn_fallback: bool=True) -> dict
```

Build the code knowledge graph and write the ``graphindex`` artefacts.

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
