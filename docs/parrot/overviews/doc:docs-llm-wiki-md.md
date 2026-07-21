---
type: Wiki Overview
title: LLM Wiki — an agent-maintained knowledge repository
id: doc:docs-llm-wiki-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Classic RAG re-synthesises an answer from raw text on every query and throws
  the
relates_to:
- concept: mod:parrot.knowledge.graphindex.embed
  rel: mentions
- concept: mod:parrot.knowledge.ontology
  rel: mentions
- concept: mod:parrot.knowledge.pageindex
  rel: mentions
- concept: mod:parrot_tools.graphindex
  rel: mentions
---

# LLM Wiki — an agent-maintained knowledge repository

> A worked pattern that composes **PageIndex + GraphIndex + Ontology** into a
> single knowledge repository an agent compiles, queries, and **contributes to**.
> Runnable example: [`examples/knowledge_wiki/`](../examples/knowledge_wiki/).

## The idea

Classic RAG re-synthesises an answer from raw text on every query and throws the
work away. An *LLM wiki* (after Andrej Karpathy's framing) flips that: the agent
compiles sources into **durable, cross-linked pages**, and **files its own
knowledge back** into the repository. The LLM does the editorial bookkeeping —
cross-referencing, summarising, filing — that a human wiki maintainer would do
by hand. Each conversation can leave the knowledge base *better than it found
it*.

AI-Parrot already ships every piece needed to build this; the example wires them
together without changing the framework.

## How the pieces map

| LLM-Wiki concept    | AI-Parrot subsystem | Module |
| ------------------- | ------------------- | ------ |
| `raw/` sources      | seed documents      | `examples/knowledge_wiki/raw/` |
| `wiki/` pages       | **PageIndex**       | `parrot.knowledge.pageindex` |
| the knowledge graph | **GraphIndex**      | `parrot_tools.graphindex.GraphIndexToolkit` |
| entity layer        | **Ontology**        | `parrot.knowledge.ontology.OntologyRAGMixin` |
| `lint`              | health report       | `examples/knowledge_wiki/wiki.py::wiki_lint` |

### PageIndex — the wiki pages

PageIndex stores a document as a *lean tree*: a JSON table-of-contents (titles,
summaries, metadata) plus per-node markdown sidecars. It is **writable** — an
agent authors durable pages with `add_node`, `insert_content`, `tag_node`, and
`update_node_content`, and retrieves them with hybrid BM25 + LLM-walk search
that returns citable section titles. See [PageIndex](./pageindex.md).

### GraphIndex — the knowledge graph the agent grows

`GraphIndexToolkit` exposes **19 tools**, of which **7 are write tools**:
`create_concept`, `create_node`, `link_nodes`, `unlink_nodes`, `attach_summary`,
`tag_node`, `merge_nodes`. They mutate the same in-memory graph and FAISS index
the read tools use, so a concept the agent files mid-conversation is immediately
searchable via `find_node` / `relevance` and joins the Louvain communities
surfaced by `list_communities`. **This is the mechanism that lets the LLM
contribute its own knowledge** rather than only consume a static corpus.

### Ontology — the structured entity layer (optional)

`OntologyRAGMixin` adds tenant-scoped, authority-aware retrieval over a graph
database. It is built for graceful degradation: with no `tenant_manager` it
returns `not_configured`; with ArangoDB unreachable it returns `vector_only` —
**it never raises**. The example therefore runs end-to-end without it, and lights
it up when an ArangoDB-backed stack is supplied.

## Wiring it together

The example keeps all glue inline in
[`examples/knowledge_wiki/wiki.py`](../examples/knowledge_wiki/wiki.py):

- `build_pageindex_toolkit(...)` / `seed_wiki_from_raw(...)` — compile sources
  into pages.
- `graph_seed_from_tree(...)` — bridge the two indices by deriving graph
  `DOCUMENT`/`SECTION` nodes from the page tree.
- `build_graphindex_toolkit(...)` — the ergonomic helper for a **write-enabled**
  `GraphIndexToolkit` (assembles the graph, embeds seed nodes, and hands the
  toolkit a consistent `graph` / `faiss_index` / `node_map` / `node_id_list` /
  `assembler` / `embedder` / `nodes` set).
- `WikiAgent(OntologyRAGMixin, BasicAgent)` via `build_wiki_agent(...)` — one
  agent with both tool surfaces plus the entity layer.
- `wiki_lint(...)` — surfaces orphan concepts and community structure.

## The loop

1. **Ingest** raw sources into PageIndex pages.
2. **Bridge** the page tree into graph nodes/edges.
3. **Build** a `WikiAgent` with both toolkits (+ Ontology).
4. **Query** — grounded, cited answers.
5. **Contribute** — the LLM files a new concept, cross-links it, attaches a
   summary, and adds a wiki page.
6. **Re-query** — the new knowledge is searchable.
7. **Lint** — report repo health.

## Running

```bash
# Offline (no API key): real PageIndex + GraphIndex toolkits, deterministic.
python examples/knowledge_wiki/llm_wiki_agent.py --no-llm

# Full agentic demo (needs GOOGLE_API_KEY for ingest + agent).
export GOOGLE_API_KEY=...
python examples/knowledge_wiki/llm_wiki_agent.py

# Tests (offline, no API key / DB).
pytest examples/knowledge_wiki/ -v
```

## Notes

- The example's default `HashingGraphEmbedder` is offline and deterministic;
  swap in `parrot.knowledge.graphindex.embed.GraphIndexEmbedder` for production
  semantic similarity.
- PageIndex auto-persists to `examples/knowledge_wiki/store/` (git-ignored); the
  GraphIndex graph is in-memory in the demo.

## Read next

- [WikiToolkit as Claude Code infrastructure](./wiki-claude-code.md) —
  `wikitoolkit build` + `parrot claude install`: the wiki as a
  codebase knowledge graph for coding assistants.
- [PageIndex](./pageindex.md)
- [Memory & Knowledge](./chapters/memory-knowledge.md)
- [Parent-Child Retrieval](./parent-child-retrieval.md)
