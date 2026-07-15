---
type: Wiki Summary
title: parrot_tools.sitesearch.tool
id: mod:parrot_tools.sitesearch.tool
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: SiteSearch tool for site-specific crawling with markdown output.
relates_to:
- concept: class:parrot_tools.sitesearch.tool.SiteSearch
  rel: defines
- concept: class:parrot_tools.sitesearch.tool.SiteSearchArgs
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot_tools.google.tools
  rel: references
- concept: mod:parrot_tools.scraping.driver
  rel: references
- concept: mod:parrot_tools.sitesearch.presets
  rel: references
---

# `parrot_tools.sitesearch.tool`

SiteSearch tool for site-specific crawling with markdown output.

## Classes

- **`SiteSearchArgs(BaseModel)`** — Arguments schema for :class:`SiteSearch`.
- **`SiteSearch(GoogleSiteSearchTool)`** — Perform Google-powered site searches and return rendered content as markdown.
