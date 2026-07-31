---
type: Wiki Summary
title: parrot_tools.rss.toolkit
id: mod:parrot_tools.rss.toolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: RSS Feed Reader Toolkit.
relates_to:
- concept: class:parrot_tools.rss.toolkit.RSSFeedReaderToolkit
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.tools.decorators
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
- concept: mod:parrot_tools.rss.fetcher
  rel: references
- concept: mod:parrot_tools.rss.models
  rel: references
- concept: mod:parrot_tools.rss.storage
  rel: references
---

# `parrot_tools.rss.toolkit`

RSS Feed Reader Toolkit.

Reads a configurable list of RSS/Atom feeds, fetches the COMPLETE page
content of every linked article (aiohttp first, Selenium fallback for
JS-heavy pages — the fallback needs the ``scraping`` extra), and archives
raw HTML + extracted text on disk. The LLM only receives per-item metadata
dictionaries carrying the paths of the archived files, never the page
content itself; ``rss_get_content`` reads archived content on demand.

Feed parsing requires the ``rss`` extra: ``pip install ai-parrot-tools[rss]``.

## Classes

- **`RSSFeedReaderToolkit(AbstractToolkit)`** — Toolkit that archives RSS feed articles to disk for later retrieval.
