---
type: Wiki Entity
title: ScrapingAgent
id: class:parrot.bots.scraper.scraper.ScrapingAgent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Intelligent web scraping agent that uses LLM to:'
relates_to:
- concept: class:parrot.bots.base.BaseBot
  rel: extends
---

# ScrapingAgent

Defined in [`parrot.bots.scraper.scraper`](../summaries/mod:parrot.bots.scraper.scraper.md).

```python
class ScrapingAgent(BaseBot)
```

Intelligent web scraping agent that uses LLM to:
- Analyze web pages and determine optimal scraping strategies
- Generate navigation steps based on page structure
- Adapt selectors based on content analysis
- Handle dynamic content and authentication flows
- Recommend optimal browser configurations

## Methods

- `async def analyze_scraping_request(self, request: Dict[str, Any]) -> Dict[str, Any]` — Analyze a scraping request and generate an execution plan with browser recommendations
- `def add_scraping_template(self, domain: str, template: Dict[str, Any])` — Add or update a scraping template for a specific domain
- `async def execute_intelligent_scraping(self, request: Dict[str, Any], adaptive_config: bool=True) -> List[ScrapingResult]` — Execute intelligent scraping with LLM-driven adaptations and browser optimization
- `async def recommend_browser_for_site(self, url: str) -> Dict[str, Any]` — Analyze a site and recommend optimal browser configuration
- `async def get_site_recommendations(self, url: str) -> Dict[str, Any]` — Get comprehensive recommendations for scraping a specific site
- `async def cleanup(self)` — Clean up resources
- `def get_available_templates(self) -> Dict[str, str]` — Get list of available scraping templates
- `def get_template_for_url(self, url: str) -> Optional[Dict[str, Any]]` — Get the best matching template for a given URL
- `async def extract_documents(self, url: str, objective: str, extraction_plan: Optional[Any]=None, scraping_plan: Optional[Any]=None, save_plan: bool=True, crawl: bool=False, depth: int=0, max_pages: int=10, follow_pattern: Optional[str]=None) -> List[Any]` — High-level entry point: scrape + extract + recall + return Documents.
