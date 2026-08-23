---
id: F001
query_id: Q001,Q002,Q003,Q004,Q019
type: wiki_query
intent: Overlap check — KnowledgeRouter (FEAT-200), FEAT-449 legal wiki namespaces, MultiStoreSearchToolkit (FEAT-379)
executed_at: 2026-08-23T02:20:00Z
depth: 0
---
# F001 — No competing "namespace router" exists; two adjacent designs to stay consistent with

## Summary
`grep "class KnowledgeRouter|KnowledgeRouter("` over `packages/` returns **nothing** — the
`KnowledgeRouter` that `sdd/state/FEAT-449/source.md` cites (line 23, marked ⚠️VERIFY) does not
exist in source. FEAT-449 (Legal LLM Wiki, in-flight, plan not yet approved) decided on
**GraphIndex namespaces** `legal:core`, `legal:civil` over shared Arango collections
(source.md:143-144) — a different plane (GraphIndex, not the wiki store) but a naming convention to
keep compatible. `MultiStoreSearchToolkit` (FEAT-379) is the agent-level prior art: an
origin-adapter registry with a `ParrotWikiOrigin`, per-origin sections + BM25 rerank + dedup.
It federates *kinds* of stores for an agent; it does not give `wikitoolkit` (CLI/MCP) multiple
wiki planes, nor namespaced ids.

## Citations
- path: `sdd/state/FEAT-449/source.md`
  lines: 23, 143-144, 274
  excerpt: |
    | KB routing | `KnowledgeRouter` (FEAT-200; ... namespaced `concept_id`) | ...
    Each L2 graph is a separate GraphIndex namespace (`legal:civil`, `legal:laboral`, …)
    **Decided (OQ1):** a single ArangoDB database; L0/L1 and every L2 are GraphIndex namespaces
- path: `sdd/proposals/multistoresearchtool-parrotwiki.brainstorm.md`
  lines: 18-30, 58-66
  excerpt: |
    ParrotWiki / LLM-Wiki (`parrot/knowledge/wiki/`) — `WikiStore` SQLite retrieval plane
    ### Option A: Origin-Adapter Toolkit (`SearchOrigin` protocol + `MultiStoreSearchToolkit`)
- path: `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py`
  lines: 39, 85, 246-252, 359, 390
  symbol: `MultiStoreSearchToolkit`, `_build_response`, `_rerank_with_bm25`, `_deduplicate_hits`
- path: `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/wiki.py`
  lines: 21
  symbol: `ParrotWikiOrigin`
- path: `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py`
  lines: 18
  symbol: `SearchOrigin`

## Notes
Wiki hits: [file:sdd/proposals/multistoresearchtool-parrotwiki.brainstorm.md] score=1.00,
[file:packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py] score=0.11.
Q001 returned no page for "KnowledgeRouter" (top hit was scripts/build_llm_wiki.py, unrelated).
