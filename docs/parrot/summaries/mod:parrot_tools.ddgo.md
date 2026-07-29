---
type: Wiki Summary
title: parrot_tools.ddgo
id: mod:parrot_tools.ddgo
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: DuckDuckGo Search Toolkit for AI-Parrot.
relates_to:
- concept: class:parrot_tools.ddgo.DuckDuckGoToolkit
  rel: defines
- concept: class:parrot_tools.ddgo.ImageSearchArgs
  rel: defines
- concept: class:parrot_tools.ddgo.NewsSearchArgs
  rel: defines
- concept: class:parrot_tools.ddgo.VideoSearchArgs
  rel: defines
- concept: class:parrot_tools.ddgo.WebSearchArgs
  rel: defines
- concept: mod:parrot_tools.abstract
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.ddgo`

DuckDuckGo Search Toolkit for AI-Parrot.

This toolkit provides web search capabilities using the ddgs library directly,
removing all Langchain dependencies and implementing proper backoff retry for rate limiting.

## Classes

- **`WebSearchArgs(BaseModel)`** — Arguments for web search.
- **`NewsSearchArgs(BaseModel)`** — Arguments for news search.
- **`ImageSearchArgs(BaseModel)`** — Arguments for image search.
- **`VideoSearchArgs(BaseModel)`** — Arguments for video search.
- **`DuckDuckGoToolkit(AbstractToolkit)`** — DuckDuckGo Search Toolkit providing comprehensive search capabilities.
