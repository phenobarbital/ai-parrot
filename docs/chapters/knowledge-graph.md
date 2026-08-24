# Knowledge Graph & LLM Wiki

Classic RAG re-synthesises an answer from raw text on every query and throws
the work away. This chapter covers the three subsystems AI-Parrot ships to do
the opposite — **compile** knowledge once, keep it structured, and let agents
*contribute back to it*.

## The three layers

| Layer | Unit of work | The question it answers |
|---|---|---|
| **[PageIndex](../pageindex.md)** | One document | *Where inside this document is the answer?* |
| **[GraphIndex](../graphindex.md)** | A whole corpus | *How do these things relate to each other?* |
| **[LLM Wiki](../llm-wiki.md)** | A durable page set | *What have we already established?* |

They compose. The LLM Wiki is built on GraphIndex pages and edges; GraphIndex
can hand hierarchical documents to PageIndex so a `SECTION` node resolves to
real prose instead of a chunk.

### PageIndex — tree-based, vectorless retrieval

Builds a **hierarchical semantic tree** from a PDF or Markdown document using
LLM reasoning, then navigates that structure to find relevant sections. No
vector database required, and it works with any provider AI-Parrot supports.

→ [PageIndex reference](../pageindex.md)

### GraphIndex — typed graph over code, docs and skills

A 6-stage pipeline (extract → embed → assemble → resolve → persist → analyze)
that emits `UniversalNode` / `UniversalEdge` across domains, infers
cross-domain edges by similarity, and produces an interactive `graph.html`
map plus a `GRAPH_REPORT.md` naming god nodes, communities and knowledge gaps.
The code pass is deterministic and LLM-free.

→ [GraphIndex reference](../graphindex.md)

### LLM Wiki — an agent-maintained knowledge repository

A machine-first knowledge graph of pages and typed edges the agent compiles,
queries, and **files its own knowledge back into** — "the agent forgets, the
graph does not". `wikitoolkit build` creates it, `wikitoolkit query` reads it,
`wikitoolkit remember` writes to it, and namespaces let several corpora
(a codebase, an Obsidian vault, a Jira backlog) federate behind one query.

→ [LLM Wiki overview](../llm-wiki.md) · [Complete guide](../guides/llm-wiki-guide.md)

## Decision matrix

| Use case | Reach for |
|---|---|
| Retrieve from one long PDF without a vector DB | [PageIndex](../pageindex.md) |
| Map how a codebase hangs together | [GraphIndex](../graphindex.md) CLI (`parrot-graphindex`) |
| Give an agent memory that survives restarts | `GraphMemoryMixin` — [Persistent graph memory](../graphindex.md#persistent-graph-memory) |
| Let a coding assistant consult the repo before grepping | [WikiToolkit as Claude Code infrastructure](../wiki-claude-code.md) |
| Query Jira tickets as a knowledge base | [Jira issues namespace](../runbooks/jira-issues-namespace.md) |

## Read next

- [LLM Wiki — Complete Guide](../guides/llm-wiki-guide.md) — build, query,
  federate, and wire it into Claude Code, Codex and Gemini.
- [WikiToolkit as Claude Code infrastructure](../wiki-claude-code.md)
- [Jira Ticket Extractor](../guides/jira-ticket-extractor.md) and
  [Integrating the Jira namespace with an agent](../guides/jira-wiki-agent-integration.md)
- [Architecture — Ontologic RAG](../architecture/09-ontologic-rag.md)
- [Memory & Knowledge chapter](memory-knowledge.md) — conversation memory and
  the vector stores underneath all of this.
