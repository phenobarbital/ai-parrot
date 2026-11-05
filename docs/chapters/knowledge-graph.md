# Knowledge Graph & LLM Wiki

Classic RAG re-synthesises an answer from raw text on every query and throws
the work away. This approach treats each query as if it were the first time
the information was ever needed. AI-Parrot provides three layered systems
that do the opposite: compile knowledge once, keep it structured, and let
agents contribute back to it. This transforms your data from a static
repository into a living knowledge base that grows smarter over time.

## Key Concepts

- **PageIndex**: Tree-based, vectorless retrieval that builds a hierarchical
  semantic tree from PDFs or Markdown documents using LLM reasoning. It
  answers the question "where inside this document is the answer?" without
  requiring a vector database, making it accessible and cost-effective.
- **GraphIndex**: Structured knowledge graph indexing that spans code,
  documentation, and skills. The six-stage pipeline (extract, embed, assemble,
  resolve, persist, analyze) produces typed `UniversalNode` and `UniversalEdge`
  objects across domains, infers cross-domain relationships by similarity,
  and generates interactive `graph.html` visualizations plus `GRAPH_REPORT.md`
  reports identifying god nodes, communities, and knowledge gaps.
- **LLM Wiki**: An agent-maintained knowledge repository where agents compile,
  query, and file their own knowledge back into the system. The principle is
  simple: "the agent forgets, the graph does not." The `wikitoolkit` CLI
  provides commands to build, query, and remember, while namespaces enable
  federating multiple corpora—a codebase, an Obsidian vault, a Jira backlog—
  behind one unified query interface.

## What You Can Build

- **Document Q&A without vector databases** using PageIndex for hierarchical
  semantic navigation of long PDFs and Markdown files, perfect for
  organizations that want semantic search without additional infrastructure.
- **Codebase understanding tools** that map how components relate using
  GraphIndex, producing interactive visualizations and automated reports
  that identify knowledge gaps and community structures in your codebase.
- **Persistent agent memory** that survives restarts via the LLM Wiki,
  allowing agents to consult established knowledge before acting, reducing
  redundant work and enabling more sophisticated reasoning.
- **Federated knowledge bases** that query across a codebase, Obsidian vault,
  and Jira backlog through unified namespaces, giving agents a complete
  picture of all your organizational knowledge.

## Deep Dive

For API reference, implementation details, and configuration options, see
the [Knowledge section](https://github.com/phenobarbital/ai-parrot/wiki/Knowledge)
and [LLM Wiki](https://github.com/phenobarbital/ai-parrot/wiki/Wiki) in the Wiki.