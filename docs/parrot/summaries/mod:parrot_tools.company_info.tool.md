---
type: Wiki Summary
title: parrot_tools.company_info.tool
id: mod:parrot_tools.company_info.tool
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: CompanyInfoToolkit - Unified toolkit for scraping company information from
  multiple sources.
relates_to:
- concept: class:parrot_tools.company_info.tool.CompanyInfo
  rel: defines
- concept: class:parrot_tools.company_info.tool.CompanyInfoToolkit
  rel: defines
- concept: class:parrot_tools.company_info.tool.CompanyInput
  rel: defines
- concept: class:parrot_tools.company_info.tool.GoogleSearchResult
  rel: defines
- concept: class:parrot_tools.company_info.tool.ResearchCompanyInput
  rel: defines
- concept: class:parrot_tools.company_info.tool.SourceConfig
  rel: defines
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.scraping.driver_context
  rel: references
- concept: mod:parrot_tools.scraping.toolkit_models
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.company_info.tool`

CompanyInfoToolkit - Unified toolkit for scraping company information from multiple sources.

This toolkit extends AbstractToolkit and provides methods to scrape company data from:
- explorium.ai
- leadiq.com
- rocketreach.co
- siccode.com
- zoominfo.com

Each public async method becomes a tool that:
1. Searches for the company (DDG-first, Google CSE fallback; see
   `_search_company_url`)
2. Fetches the first validated result via the Playwright driver stack
   (`driver_context` + `DriverConfig(driver_type="playwright")`)
3. Parses the page with BeautifulSoup
4. Extracts company information
5. Returns structured data (CompanyInfo model or JSON)

Dependencies:
    - playwright (fetch layer; scraping extra)
    - rapidfuzz (fuzzy company-name validation; scraping extra)
    - ddgs (DDG-first search)
    - beautifulsoup4
    - pydantic
    - google-api-python-client
    - aiohttp

Example usage:
    toolkit = CompanyInfoToolkit(
        google_api_key="your-api-key",
        google_cse_id="your-cse-id",
        use_proxy=False,
        headless=True
    )

    # Get all tools
    tools = toolkit.get_tools()

    # Or use methods directly
    result = await toolkit.scrape_zoominfo("PetSmart")
    print(result.company_name)

## Classes

- **`CompanyInput(BaseModel)`** — Input model for company scraping tools.
- **`ResearchCompanyInput(BaseModel)`** — Input model for the `research_company` aggregate tool.
- **`CompanyInfo(BaseModel)`** — Structured output model for company information.
- **`GoogleSearchResult(BaseModel)`** — Result from Google site search.
- **`SourceConfig(BaseModel)`** — Internal per-source search configuration.
- **`CompanyInfoToolkit(AbstractToolkit)`** — Toolkit for scraping company information from multiple platforms.
