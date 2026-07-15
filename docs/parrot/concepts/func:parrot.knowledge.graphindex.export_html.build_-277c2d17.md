---
type: Concept
title: build_export_payload()
id: func:parrot.knowledge.graphindex.export_html.build_export_payload
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build a :class:`GraphExportPayload` from an assembled graph.
---

# build_export_payload

```python
def build_export_payload(graph: 'rustworkx.PyDiGraph', *, node_to_community: Optional[dict[str, str]]=None, community_order: Optional[list[str]]=None, community_labels: Optional[dict[str, str]]=None, community_sizes: Optional[dict[str, int]]=None, god_scores: Optional[dict[str, float]]=None, god_node_ids: Optional[list[str]]=None, title: str='GraphIndex Knowledge Map', modularity: Optional[float]=None) -> GraphExportPayload
```

Build a :class:`GraphExportPayload` from an assembled graph.

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
