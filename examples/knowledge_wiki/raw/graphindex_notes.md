# GraphIndex Notes

GraphIndex is the knowledge-graph half of the wiki. Nodes are typed
(`document`, `section`, `symbol`, `concept`, `rationale`, `skill`) and edges are
typed too (`contains`, `references`, `defines`, `mentions`, `explains`). The
graph lives in memory for hot traversal, alongside a FAISS index over node
embeddings for semantic lookup.

## Querying

The toolkit exposes read tools for finding the closest node to a query,
listing references, walking a neighbourhood, computing shortest paths, and
explaining a node. A five-signal `relevance` score (direct edges, shared
sources, Adamic-Adar, type affinity, and embedding similarity) ranks how
related two nodes are, and `neighborhood_by_relevance` returns the most related
nodes around a given one.

## Communities

Louvain community detection groups related nodes into clusters. `list_communities`
and `find_community` surface that structure, and the partition is cached until a
write tool changes the graph.

## Writing — the agent contributes

The defining feature: the agent maintains the graph itself. `create_concept`
mints and embeds a new concept node; `link_nodes` and `unlink_nodes` manage
typed edges; `attach_summary` and `tag_node` enrich a node; `merge_nodes`
collapses duplicates. Because writes update the same in-memory graph and FAISS
index the read tools use, a concept the agent files mid-conversation becomes
immediately searchable — the LLM is doing the cross-referencing and filing that
a human wiki editor would otherwise do by hand.
