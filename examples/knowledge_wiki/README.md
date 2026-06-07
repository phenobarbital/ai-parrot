# LLM Wiki — an agent-maintained knowledge repository

This example builds a **knowledge repository that an agent compiles, queries,
and contributes to** — inspired by Andrej Karpathy's "LLM wiki" idea. Instead
of re-synthesising an answer from raw text on every query (classic RAG), the
agent compiles sources into durable, cross-linked pages and *files its own
knowledge back* into the repository. The LLM does the bookkeeping a human wiki
editor would otherwise do by hand: cross-referencing, summarising, filing.

It composes **three** AI-Parrot knowledge subsystems — no framework changes, all
wiring is inline in [`wiki.py`](./wiki.py):

| LLM-Wiki concept   | AI-Parrot subsystem                                                        |
| ------------------ | ------------------------------------------------------------------------- |
| `raw/` sources     | the markdown files in [`raw/`](./raw)                                      |
| `wiki/` pages      | **PageIndex** — a JSON table-of-contents + per-node markdown sidecars      |
| the knowledge graph| **GraphIndex** — a graph + FAISS index the agent grows via *write* tools   |
| entity layer       | **Ontology** — structured, tenant-scoped entities (optional, degrades)     |
| `lint`             | [`wiki_lint`](./wiki.py) — orphan-node / community health report           |

## Why these are the right pieces

- **PageIndex** (`parrot.knowledge.pageindex`) is the *wiki pages* half. It is
  already writable: `add_node`, `insert_content`, `tag_node`,
  `update_node_content` let an agent author durable pages, and hybrid
  BM25 + LLM-walk search retrieves them with citations.
- **GraphIndex** (`parrot_tools.graphindex.GraphIndexToolkit`) is the
  *knowledge graph* half. Its 19 tools include 7 **write** tools
  (`create_concept`, `link_nodes`, `attach_summary`, `merge_nodes`, …) that
  mutate the same in-memory graph + FAISS index the read tools use — so a
  concept the agent files mid-conversation is immediately searchable. **This is
  what lets the LLM contribute its own knowledge.**
- **Ontology** (`parrot.knowledge.ontology.OntologyRAGMixin`) adds a structured
  entity layer. It degrades gracefully: with no `tenant_manager` it reports
  `not_configured`; with ArangoDB unreachable it falls back to `vector_only` —
  never raising. So the example runs without it and lights it up when configured.

## The loop the demo walks

1. **Ingest** — compile `raw/*.md` into PageIndex pages.
2. **Bridge** — derive graph `DOCUMENT`/`SECTION` nodes from the page tree.
3. **Agent** — wire a `WikiAgent` (`OntologyRAGMixin` + `BasicAgent`) with both
   toolkits.
4. **Query** — answer a question, grounded and cited.
5. **Contribute** — the LLM files a new concept, cross-links it, attaches a
   summary, and adds a synthesised wiki page.
6. **Re-query** — confirm the freshly filed concept is now searchable.
7. **Lint** — report orphan nodes and community structure.

## Running

### Offline (no API key) — recommended first run

Exercises the **real** PageIndex and GraphIndex toolkits deterministically,
skipping only the LLM/agent phases:

```bash
python examples/knowledge_wiki/llm_wiki_agent.py --no-llm
```

### Full agentic demo

Requires `GOOGLE_API_KEY` (PageIndex ingest and the agent both call an LLM):

```bash
export GOOGLE_API_KEY=...
python examples/knowledge_wiki/llm_wiki_agent.py            # add --reset to rebuild
```

Dependencies: `pip install -e "packages/ai-parrot[graphindex]" -e packages/ai-parrot-tools bm25s`
(plus an LLM provider such as `ai-parrot[google]` for the full demo).

## Tests

Deterministic, offline, no API key or database:

```bash
pytest examples/knowledge_wiki/ -v
```

They cover the write-enabled toolkit construction, the contribution loop
(create → search → link → relevance → communities), `merge_nodes` FAISS
bookkeeping, PageIndex authoring + BM25 retrieval, the lint report, and the
Ontology graceful-degradation path.

## Notes & extension points

- **Graph embeddings.** The default `HashingGraphEmbedder` in `wiki.py` is an
  offline, deterministic bag-of-tokens embedder so the demo runs without a model
  download. For production semantic similarity, pass a
  `parrot.knowledge.graphindex.embed.GraphIndexEmbedder` to
  `build_graphindex_toolkit(..., embedder=...)` — the rest of the wiring is
  unchanged.
- **Persistence.** PageIndex auto-persists pages + sidecars to
  `examples/knowledge_wiki/store/` (git-ignored). The GraphIndex graph is
  in-memory here; persist it to ArangoDB via
  `parrot.knowledge.graphindex` persistence when you need durability.
- **Ontology, fully on.** Provide an ArangoDB-backed `TenantOntologyManager` +
  `OntologyGraphStore` to `build_wiki_agent(...)` and call
  `agent.ontology_process(...)` to enrich queries with structural entity data.
  See `sdd/specs/advisor-ontologic-rag-agent.spec.md` for the canonical pattern.
- **Reusing the glue.** `build_graphindex_toolkit` is the ergonomic helper the
  framework does not yet ship for *write-enabled* graph toolkits. If it proves
  useful beyond this example, promoting it to a `GraphIndexBuilder.to_toolkit()`
  is the natural follow-up.
```
