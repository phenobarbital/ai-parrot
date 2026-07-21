---
type: Wiki Entity
title: TwoStepIngester
id: class:parrot.knowledge.pageindex.ingest.TwoStepIngester
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Drive the two-step ingest pipeline against an LLM adapter.
---

# TwoStepIngester

Defined in [`parrot.knowledge.pageindex.ingest`](../summaries/mod:parrot.knowledge.pageindex.ingest.md).

```python
class TwoStepIngester
```

Drive the two-step ingest pipeline against an LLM adapter.

Args:
    adapter: The "heavy" adapter used for Step 2 (markdown generation).
    lightweight_adapter: Optional dedicated adapter for Step 1. When
        provided, Step 1 runs against this adapter (typically wrapping
        the same client but pinned to a smaller model). When omitted,
        ``adapter`` is used for both steps.

## Methods

- `async def ingest(self, content: str, hint: Optional[str]=None) -> IngestedMarkdown` — Run both steps and return the structured markdown.
