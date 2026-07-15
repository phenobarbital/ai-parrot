---
type: Wiki Entity
title: ScrapingOrchestrator
id: class:parrot_tools.scraping.orchestrator.ScrapingOrchestrator
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: High-level orchestrator that manages the complete LLM-directed scraping workflow.
---

# ScrapingOrchestrator

Defined in [`parrot_tools.scraping.orchestrator`](../summaries/mod:parrot_tools.scraping.orchestrator.md).

```python
class ScrapingOrchestrator
```

High-level orchestrator that manages the complete LLM-directed scraping workflow.

This class integrates with AI-parrot's existing infrastructure:
- Uses the knowledge base system for storing scraped content
- Integrates with the loader system for content processing
- Supports agent orchestration patterns
- Provides hooks for custom post-processing

## Methods

- `async def execute_scraping_mission(self, mission_config: Dict[str, Any]) -> Dict[str, Any]` — Execute a complete scraping mission with multiple targets and objectives.
- `def add_result_filter(self, filter_func: Callable[[ScrapingResult, Dict[str, Any]], bool])` — Add a filter function to exclude certain results
- `def add_post_processor(self, processor_func: Callable)` — Add a post-processor function for result enhancement
