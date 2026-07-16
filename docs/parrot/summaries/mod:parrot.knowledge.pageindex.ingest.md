---
type: Wiki Summary
title: parrot.knowledge.pageindex.ingest
id: mod:parrot.knowledge.pageindex.ingest
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Two-Step Chain-of-Thought ingestion: raw content -> clean markdown.'
relates_to:
- concept: class:parrot.knowledge.pageindex.ingest.IngestedMarkdown
  rel: defines
- concept: class:parrot.knowledge.pageindex.ingest.TwoStepIngester
  rel: defines
- concept: mod:parrot.knowledge.pageindex.llm_adapter
  rel: references
- concept: mod:parrot.knowledge.pageindex.prompts
  rel: references
---

# `parrot.knowledge.pageindex.ingest`

Two-Step Chain-of-Thought ingestion: raw content -> clean markdown.

Step 1 (lightweight model): an open-ended Chain-of-Thought analysis of
the content, returned as prose.
Step 2 (heavy model): structured markdown generation grounded on the
Step-1 analysis and the original content.

The resulting :class:`IngestedMarkdown` can then be fed to
:func:`parrot.knowledge.pageindex.md_builder.md_to_tree` to produce a subtree
ready for :func:`parrot.knowledge.pageindex.tree_ops.splice_subtree`.

## Classes

- **`IngestedMarkdown(BaseModel)`** — Structured output of the Step-2 markdown generator.
- **`TwoStepIngester`** — Drive the two-step ingest pipeline against an LLM adapter.
