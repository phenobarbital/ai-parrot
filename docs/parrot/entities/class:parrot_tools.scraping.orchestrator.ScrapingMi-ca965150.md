---
type: Wiki Entity
title: ScrapingMissionBuilder
id: class:parrot_tools.scraping.orchestrator.ScrapingMissionBuilder
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Builder pattern for creating complex scraping missions
---

# ScrapingMissionBuilder

Defined in [`parrot_tools.scraping.orchestrator`](../summaries/mod:parrot_tools.scraping.orchestrator.md).

```python
class ScrapingMissionBuilder
```

Builder pattern for creating complex scraping missions

## Methods

- `def add_target(self, url: str, objective: str='Extract all relevant content', authentication: Optional[Dict[str, Any]]=None, custom_steps: Optional[List[Dict[str, Any]]]=None, custom_selectors: Optional[List[Dict[str, Any]]]=None) -> 'ScrapingMissionBuilder'` — Add a target to the scraping mission
- `def set_rate_limiting(self, requests_per_minute: int=30, delay_between_requests: float=2.0) -> 'ScrapingMissionBuilder'` — Set rate limiting constraints
- `def set_authentication(self, username: str, password: str, login_url: str, username_selector: str='#username', password_selector: str='#password', submit_selector: str='input[type=submit]') -> 'ScrapingMissionBuilder'` — Set global authentication for all targets
- `def enable_content_analysis(self, summarize_content: bool=True, extract_entities: bool=True, sentiment_analysis: bool=False) -> 'ScrapingMissionBuilder'` — Enable advanced content analysis features
- `def build(self) -> Dict[str, Any]` — Build the final mission configuration
