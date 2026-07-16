---
type: Wiki Summary
title: parrot_loaders.webscraping
id: mod:parrot_loaders.webscraping
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: WebScrapingLoader — Loader interface for WebScrapingToolkit + CrawlEngine.
relates_to:
- concept: class:parrot_loaders.webscraping.WebScrapingLoader
  rel: defines
- concept: mod:parrot.loaders.abstract
  rel: references
- concept: mod:parrot.stores.models
  rel: references
- concept: mod:parrot.utils.jsonld_extractors
  rel: references
- concept: mod:parrot_tools.scraping.toolkit
  rel: references
---

# `parrot_loaders.webscraping`

WebScrapingLoader — Loader interface for WebScrapingToolkit + CrawlEngine.

Bridges parrot's Loader abstraction with the scraping/crawling infrastructure
in ``parrot_tools.scraping``, converting ``ScrapingResult`` / ``CrawlResult``
into chunked ``Document`` objects suitable for vector stores and PageIndex.

Single-page usage::

    loader = WebScrapingLoader(
        source="https://example.com/docs",
        selectors=[
            {"name": "content", "selector": "article.main", "extract_type": "text"},
            {"name": "title", "selector": "h1", "extract_type": "text"},
        ],
        tags=["p", "h1", "h2", "h3", "article", "section"],
    )
    docs = await loader.load()

Crawl usage::

    loader = WebScrapingLoader(
        source="https://example.com/docs",
        crawl=True,
        depth=2,
        max_pages=50,
        follow_pattern=r"/docs/.*",
    )
    docs = await loader.load()

With a ScrapingPlan::

    from parrot_tools.scraping.plan import ScrapingPlan
    plan = ScrapingPlan(url="https://example.com", objective="Extract docs", steps=[...])
    loader = WebScrapingLoader(source="https://example.com", plan=plan)
    docs = await loader.load()

## Classes

- **`WebScrapingLoader(AbstractLoader)`** — Load web pages via WebScrapingToolkit and convert to Documents.
