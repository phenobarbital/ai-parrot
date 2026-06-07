# PageIndex Notes

PageIndex stores a document as a *lean tree*: a JSON table-of-contents that
keeps titles, summaries and metadata, while each node's markdown body lives in a
separate content store keyed by node id. The persisted ToC never carries inline
body text, which keeps it small and fast to walk.

## Ingest

Raw sources are compiled into pages with a Two-Step Chain-of-Thought ingest. A
lightweight model first analyses the content, then a second pass produces clean
markdown that is parsed into a subtree and spliced into the wiki. Whole files
and folders can be imported in one call.

## Search

Retrieval is hybrid. A BM25 sparse index handles lexical matches, an LLM
tree-walk reasons about which section to descend into, and the two candidate
sets are fused with reciprocal-rank fusion. An optional reranker can reorder the
final list. `retrieve` runs the search and then aggregates the per-node markdown
bodies into a single grounded context block, with section titles for citation.

## Authoring

PageIndex is writable, not just readable. `add_node` registers a single page
under a parent in one atomic call; `insert_content` ingests raw text as a new
branch; `tag_node` merges categories and metadata; `update_node_content` revises
a body in place. This is what lets an agent file its own findings as durable
pages instead of throwing them away after answering.
