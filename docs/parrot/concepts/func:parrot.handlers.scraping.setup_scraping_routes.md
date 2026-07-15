---
type: Concept
title: setup_scraping_routes()
id: func:parrot.handlers.scraping.setup_scraping_routes
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Register all scraping handler routes on the aiohttp application.
---

# setup_scraping_routes

```python
def setup_scraping_routes(app: web.Application) -> None
```

Register all scraping handler routes on the aiohttp application.

This is the single entry point for integrating scraping endpoints
into an aiohttp app. It registers:
- ScrapingHandler class-based view routes (plan CRUD, scrape, crawl, jobs)
- ScrapingInfoHandler method-based routes (actions, drivers, config, strategies)
- Startup/cleanup signals for toolkit and job manager lifecycle

Args:
    app: The aiohttp web application.
