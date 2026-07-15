---
type: Wiki Summary
title: parrot_tools.graphindex.toolkit
id: mod:parrot_tools.graphindex.toolkit
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: GraphIndex Toolkit — Agent-Facing Tools.
relates_to:
- concept: class:parrot_tools.graphindex.toolkit.GraphIndexToolkit
  rel: defines
- concept: mod:parrot.knowledge.graphindex.analytics
  rel: references
- concept: mod:parrot.knowledge.graphindex.assemble
  rel: references
- concept: mod:parrot.knowledge.graphindex.communities
  rel: references
- concept: mod:parrot.knowledge.graphindex.embed
  rel: references
- concept: mod:parrot.knowledge.graphindex.export_html
  rel: references
- concept: mod:parrot.knowledge.graphindex.retriever
  rel: references
- concept: mod:parrot.knowledge.graphindex.schema
  rel: references
- concept: mod:parrot.knowledge.graphindex.signals
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
- concept: mod:parrot.utils.faiss_logging
  rel: references
---

# `parrot_tools.graphindex.toolkit`

GraphIndex Toolkit — Agent-Facing Tools.

Exposes the knowledge graph to AI agents as a set of 19 callable tools
via ``GraphIndexToolkit(AbstractToolkit)``.  All public async methods
are auto-discovered and registered as tools by the ``AbstractToolkit``
base class.

Hot read queries operate over the in-memory ``rustworkx.PyDiGraph``
and FAISS index. Write tools mutate the same in-memory state through
the ``GraphAssembler`` reference (when supplied) so the graph stays
consistent; agents can build the wiki from inside a tool call.

Optional integrations:

* ``GraphIndexEmbedder`` — when injected, replaces the placeholder
  query encoder with a real ``model.encode`` call and embeds freshly
  created nodes so ``find_node`` and ``search_hybrid`` see them.
* ``SignalRelevanceConfig`` (FEAT-190) — drives ``relevance()`` and
  ``neighborhood_by_relevance()``. Lazy-imported.
* FEAT-191 communities — ``list_communities`` / ``find_community``
  cache the partition until a write tool runs. Lazy-imported.

Tool surface:

  # READ
  find_node, find_references, get_neighborhood, traverse,
  search_hybrid, find_central_nodes, shortest_path, explain,
  relevance, neighborhood_by_relevance, list_communities,
  find_community, export_graph_html

  # WRITE
  create_concept, create_node, link_nodes, unlink_nodes,
  attach_summary, tag_node, merge_nodes

## Classes

- **`GraphIndexToolkit(AbstractToolkit)`** — Agent-facing tools for querying AND mutating the GraphIndex graph.
