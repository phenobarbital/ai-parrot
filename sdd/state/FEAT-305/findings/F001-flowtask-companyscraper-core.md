---
id: F001
query_id: Q001
type: read
intent: Understand the base component's orchestration, HTTP strategy, output shape
executed_at: 2026-07-13T22:40:00Z
parent_id: null
depth: 0
---

# F001 — flowtask CompanyScraper core component

## Summary

`CompanyScraper(FlowComponent, SeleniumService, HTTPService)` is a
DataFrame-in/DataFrame-out batch component. Pipeline per row: (1) build a
site-scoped search term via each configured scrapper
(`scrapper.define_search_term(company_name)`), (2) search DuckDuckGo first
(`search_in_ddg` → `self._search_duckduckgo`), falling back to Google CSE
(`search_in_google` → `self._search_google`, then Selenium-driven
`search_google_cse`), (3) validate the hit title against the company name
with exact/prefix/fuzzy matching (`_check_company_name`, `fuzz.ratio > 85`),
(4) fetch the company page (`scrapper.get`, proxy-enabled; Selenium fallback
on HTTP errors), (5) delegate parsing to `scrapper.scrapping(soup, idx, row)`.
Output columns (~28) include company_name, address/city/state/zip/country,
phone_number, website, stock_symbol, naics_code, sic_code, employee_count,
revenue_range, industry, company_description, similar_companies (JSON string),
search_status/scrape_status.

## Citations

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/CompanyScraper/scrapper.py`
  lines: 28-101
  symbol: `CompanyScraper.__init__`
  excerpt: |
    class CompanyScraper(FlowComponent, SeleniumService, HTTPService):
        self.info_column: str = kwargs.get('column_name', 'company_name')
        self.scrappers: list = kwargs.get('scrappers', ['leadiq'])
        self.use_proxy: bool = True
        self.paid_proxy: bool = True
        self.headers: dict = {..., "User-Agent": random.choice(ua)}

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/CompanyScraper/scrapper.py`
  lines: 741-770
  symbol: `_check_company_name`
  excerpt: |
    # keyword split + exact/first-token match, then:
    score = fuzz.ratio(company.lower(), result.lower())
    if score > 85:
        return True

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/CompanyScraper/scrapper.py`
  lines: 778-864
  symbol: `search_in_ddg / search_in_google / _company_exists`
  excerpt: |
    results = await self._search_duckduckgo(search_term, use_proxy=True, ...)
    # fallback:
    response = await self._search_google(search_term, use_proxy=True, ...)
    # last resort: await self.search_google_cse(search_term)  (Selenium)

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/CompanyScraper/scrapper.py`
  lines: 866-968
  symbol: `_search_company`
  excerpt: |
    for scrapper in self.scrappers:
        search_term = scrapper.define_search_term(company_name)
        company = await self.search_in_ddg(...)   # → google fallbacks
        url = company.get('link') ...
        company_page = await scrapper.get(url, headers=self.headers)
        scraped_idx, scraped_data = await scrapper.scrapping(soup, idx, row)
        if scraped_data['scrape_status'] == 'success': return idx, row

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/CompanyScraper/scrapper.py`
  lines: 970-1056
  symbol: `run`
  excerpt: |
    # instantiates LeadiqScrapper/ExploriumScrapper/ZoomInfoScrapper/
    # SicCodeScrapper/RocketReachScrapper/VisualVisitorScrapper with
    # per-domain httpx cookies; gathers per-row tasks in chunks.

## Notes

Also contains dead/duplicated logic: `scrape_url`, `_scrape_leadiq`,
`_scrape_explorium`, `extract_company_info` duplicate the parser classes
(legacy path, URL-based). DataFrame/tqdm/pandas concerns are flowtask-specific
and must NOT be ported to a per-company agent tool.
