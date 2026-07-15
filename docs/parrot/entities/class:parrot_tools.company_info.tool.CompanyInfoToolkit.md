---
type: Wiki Entity
title: CompanyInfoToolkit
id: class:parrot_tools.company_info.tool.CompanyInfoToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit for scraping company information from multiple platforms.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# CompanyInfoToolkit

Defined in [`parrot_tools.company_info.tool`](../summaries/mod:parrot_tools.company_info.tool.md).

```python
class CompanyInfoToolkit(AbstractToolkit)
```

Toolkit for scraping company information from multiple platforms.

Each public async method is automatically converted to a tool by AbstractToolkit.
Methods perform:
1. Google site search for company
2. Selenium page fetch
3. BeautifulSoup parsing
4. Structured data extraction

## Methods

- `async def scrape_zoominfo(self, company_name: str, return_json: bool=False) -> Union[CompanyInfo, str]` — Scrape company information from ZoomInfo.
- `async def scrape_explorium(self, company_name: str, return_json: bool=False) -> Union[CompanyInfo, str]` — Scrape company information from Explorium.ai.
- `async def scrape_leadiq(self, company_name: str, return_json: bool=False) -> Union[CompanyInfo, str]` — Scrape company information from LeadIQ.
- `async def scrape_rocketreach(self, company_name: str, return_json: bool=False) -> Union[CompanyInfo, str]` — Scrape company information from RocketReach.
- `async def scrape_siccode(self, company_name: str, return_json: bool=False) -> Union[CompanyInfo, str]` — Scrape company information from SICCode.com.
- `async def scrape_visualvisitor(self, company_name: str, return_json: bool=False) -> Union[CompanyInfo, str]` — Scrape company information from VisualVisitor.
- `async def scrape_all_sources(self, company_name: str, return_json: bool=False) -> Union[List[CompanyInfo], str]` — Scrape company information from ALL available sources.
- `async def research_company(self, company_name: str, sources: Optional[List[str]]=None, return_json: bool=False) -> Union[CompanyInfo, str]` — Research a company across sources, returning the first successful profile.
