---
kind: inline
jira_key: null
fetched_at: "2026-06-16T12:00:00Z"
summary_oneline: "Evaluate llm_wiki repo and OKF spec; extract ideas for GraphIndex/PageIndex platform enhancement"
---

## Source

Based on these external references:

1. **nashsu/llm_wiki** — https://github.com/nashsu/llm_wiki/tree/main
   Desktop app implementing Karpathy's LLM Wiki pattern with 4-signal relevance model,
   Louvain community detection, graph insights (surprising connections, knowledge gaps),
   and multi-phase retrieval pipeline.

2. **Karpathy's LLM Wiki gist** — https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
   Abstract design pattern: raw sources → LLM-maintained wiki → schema.
   Three core operations: ingest, query, lint.

3. **Google Open Knowledge Format (OKF)** — https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing
   Open spec (v0.1) for portable, vendor-neutral knowledge representation.
   Markdown + YAML frontmatter + directory hierarchy. Only `type` is required.

## User Request

Evaluate whether current GraphIndex/PageIndex implementation can supersede OKF
as a knowledge platform, and extract ideas from nashsu/llm_wiki to enhance the
current platform. Specific areas of interest:

- FEAT-191 Louvain community detection enhancements
- Graph Insights: surprising connections & knowledge gaps
- Signal Relevance Model optimization
- OKF bundle interchange compliance
