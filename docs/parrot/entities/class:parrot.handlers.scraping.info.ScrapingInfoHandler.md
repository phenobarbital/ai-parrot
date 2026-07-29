---
type: Wiki Entity
title: ScrapingInfoHandler
id: class:parrot.handlers.scraping.info.ScrapingInfoHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Method-based handler serving reference data for the Scraping UI.
---

# ScrapingInfoHandler

Defined in [`parrot.handlers.scraping.info`](../summaries/mod:parrot.handlers.scraping.info.md).

```python
class ScrapingInfoHandler(BaseHandler)
```

Method-based handler serving reference data for the Scraping UI.

All endpoints are GET-only and return static/introspected metadata
about browser actions, driver types, driver configuration, and
crawl strategies.

## Methods

- `async def get_actions(self, request: web.Request) -> web.Response` — GET /api/v1/scraping/info/actions — list all BrowserAction types.
- `async def get_drivers(self, request: web.Request) -> web.Response` — GET /api/v1/scraping/info/drivers — list driver types and browsers.
- `async def get_config_schema(self, request: web.Request) -> web.Response` — GET /api/v1/scraping/info/config — DriverConfig JSON schema.
- `async def get_strategies(self, request: web.Request) -> web.Response` — GET /api/v1/scraping/info/strategies — crawl strategy definitions.
- `def setup(self, app: web.Application) -> None` — Register all info GET routes on the aiohttp application.
