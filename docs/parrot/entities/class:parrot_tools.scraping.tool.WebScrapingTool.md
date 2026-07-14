---
type: Wiki Entity
title: WebScrapingTool
id: class:parrot_tools.scraping.tool.WebScrapingTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Advanced web scraping tool with LLM integration support.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# WebScrapingTool

Defined in [`parrot_tools.scraping.tool`](../summaries/mod:parrot_tools.scraping.tool.md).

```python
class WebScrapingTool(AbstractTool)
```

Advanced web scraping tool with LLM integration support.

Features:
- Support for both Selenium and Playwright
- Step-by-step navigation instructions
- Flexible content extraction
- Intermediate result storage
- Error handling and retry logic

Supported Actions:
    * Navigation: navigate, back, refresh
    * Interaction: click, fill, press_key, scroll
    * Data Extraction: get_text, get_html, get_cookies
    * Authentication: authenticate
    * File Operations: upload_file, wait_for_download, screenshot
    * State Management: set_cookies
    * Waiting: wait, await_human, await_keypress, await_browser_event
    * Evaluation: evaluate
    * Control Flow: loop

## Methods

- `async def initialize_driver(self, config_overrides: Optional[Dict[str, Any]]=None)` — Initialize the web driver based on configuration.
- `async def execute_scraping_workflow(self, steps: List[ScrapingStep], selectors: Optional[List[ScrapingSelector]]=None, base_url: str='') -> List[ScrapingResult]` — Execute a complete scraping workflow
- `def js_click(self, driver, element)`
- `async def crawl(self, start_url: str, plan: Optional[ScrapingPlan]=None, depth: int=1, max_pages: Optional[int]=None, strategy: Optional[CrawlStrategy]=None, concurrency: int=1, browser_config: Optional[Dict[str, Any]]=None) -> CrawlResult` — Multi-page crawl starting from *start_url*.
- `async def cleanup(self)` — Clean up resources.
- `def get_schema(self) -> Dict[str, Any]` — Define the tool schema for LLM interaction.
