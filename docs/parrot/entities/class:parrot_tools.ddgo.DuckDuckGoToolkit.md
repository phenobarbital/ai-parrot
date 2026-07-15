---
type: Wiki Entity
title: DuckDuckGoToolkit
id: class:parrot_tools.ddgo.DuckDuckGoToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: DuckDuckGo Search Toolkit providing comprehensive search capabilities.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# DuckDuckGoToolkit

Defined in [`parrot_tools.ddgo`](../summaries/mod:parrot_tools.ddgo.md).

```python
class DuckDuckGoToolkit(AbstractToolkit)
```

DuckDuckGo Search Toolkit providing comprehensive search capabilities.

This toolkit uses the ddgs library directly for improved performance and reliability,
with built-in backoff retry mechanisms for handling rate limits.

## Methods

- `async def web_search(self, query: str, region: str='us-en', safesearch: str='moderate', timelimit: Optional[str]=None, max_results: int=10, page: int=1) -> ToolResult` — Search the web using DuckDuckGo.
- `async def news_search(self, query: str, region: str='us-en', safesearch: str='moderate', timelimit: Optional[str]=None, max_results: int=10) -> ToolResult` — Search for news using DuckDuckGo.
- `async def image_search(self, query: str, region: str='us-en', safesearch: str='moderate', size: Optional[str]=None, color: Optional[str]=None, type_image: Optional[str]=None, layout: Optional[str]=None, license_image: Optional[str]=None, max_results: int=10) -> ToolResult` — Search for images using DuckDuckGo.
- `async def video_search(self, query: str, region: str='us-en', safesearch: str='moderate', timelimit: Optional[str]=None, resolution: Optional[str]=None, duration: Optional[str]=None, license_videos: Optional[str]=None, max_results: int=10) -> ToolResult` — Search for videos using DuckDuckGo.
