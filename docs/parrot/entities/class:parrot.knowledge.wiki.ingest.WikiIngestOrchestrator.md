---
type: Wiki Entity
title: WikiIngestOrchestrator
id: class:parrot.knowledge.wiki.ingest.WikiIngestOrchestrator
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Orchestrates the full source-to-wiki-page ingest pipeline.
---

# WikiIngestOrchestrator

Defined in [`parrot.knowledge.wiki.ingest`](../summaries/mod:parrot.knowledge.wiki.ingest.md).

```python
class WikiIngestOrchestrator
```

Orchestrates the full source-to-wiki-page ingest pipeline.

Dependencies are injected at construction time so every component
can be mocked in tests without a real LLM or database.

Attributes:
    _pi: ``PageIndexToolkit`` instance for tree mutations.
    _gi: ``GraphIndexToolkit`` instance for graph sync.
    _sources: :class:`SourceCollectionManager` for manifest tracking.
    _bookkeeper: :class:`WikiBookkeeper` for index/log updates.
    logger: Standard Python logger.

Example::

    orch = WikiIngestOrchestrator(pi, gi, source_mgr, bookkeeper)
    report = await orch.ingest("/docs/article.md", config)
    print(report.pages_created)

## Methods

- `async def ingest(self, source_path: str, wiki_config: WikiConfig) -> IngestReport` — Run the full ingest pipeline for a single source file.
