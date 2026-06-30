---
id: F008
query_id: Q008
type: read
intent: Deep dive into PageIndex ingest pipeline and TwoStepIngester
executed_at: 2026-06-26T00:00:00Z
duration_ms: 4500
parent_id: F001
depth: 1
---

# F008 — PageIndex Ingest Pipeline: Two-Step Chain-of-Thought

## Summary

The TwoStepIngester (ingest.py:43-106) processes raw content via a two-model pipeline: Step 1 uses a lightweight model for CoT analysis (truncated to 8K chars), Step 2 uses a heavy model for structured markdown generation (IngestedMarkdown with title, summary, markdown). The PageIndexToolkit wires this into insert_content() which calls md_to_tree() to parse markdown into a hierarchical tree, then splice_subtree() to merge into an existing tree with reindexed node IDs. Per-node markdown bodies are extracted from the tree and stored as sidecars in NodeContentStore (one .md file per node). The lean JSON tree retains only titles, summaries, metadata, and structure.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/ingest.py`
  lines: 43-106
  symbol: `TwoStepIngester`
  excerpt: |
    class TwoStepIngester:
        def __init__(self, adapter, lightweight_adapter=None)
        async def ingest(content, hint=None) -> IngestedMarkdown
        async def _step1_analyze(content, hint) -> str  # CoT analysis
        async def _step2_generate(content, analysis, hint) -> IngestedMarkdown

- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py`
  lines: 730-752
  symbol: `insert_content`
  excerpt: |
    async def insert_content(self, tree_name, content, parent_node_id=None, hint=None):
        ingested = await self._ingester().ingest(content, hint)
        return await self.insert_markdown(tree_name, ingested.markdown, ...)

- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py`
  lines: 194-256
  symbol: `md_to_tree`

## Notes

The two-model strategy is critical for wiki ingest: cheap model understands the document, expensive model generates structured output. For wiki multi-page updates, the same pattern can be extended: Step 1 analyzes what existing wiki pages need updating, Step 2 generates the actual updates. The splice_subtree + reindex pattern handles tree mutations safely.
