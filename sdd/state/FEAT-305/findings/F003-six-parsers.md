---
id: F003
query_id: Q003
type: read
intent: Per-source extraction logic and coupling to strip
executed_at: 2026-07-13T22:40:00Z
parent_id: null
depth: 0
---

# F003 — The six source parsers

## Summary

All six parsers are BeautifulSoup selector walkers over public company-profile
pages (NOT authenticated APIs). Each defines its `site:` search template +
title keywords and fills the same row dict. Notable specifics: **LeadIQ**
(richest: overview dl/dt/dd, hero section, similar_companies JSON);
**RocketReach** (info table; extracts funding, founded, industry list,
NAICS/SIC as lists); **ZoomInfo** overrides `get()` to use undetected-Chrome
Selenium (`self.use_undetected = True`) because of anti-bot walls;
**SICCode** (main-title + description/overview blocks; city/state/zip/country/
metro_area); **VisualVisitor** is a copy-paste of RocketReach's selectors
(even mislabels `source_platform: 'rocketreach'` — porting bug to fix);
**Explorium** (data-id driven selectors, NAICS/SIC with aria-label industry
descriptions). Copy-paste error messages ("Error parsing LeadIQ data") appear
in rocket/visualvisitor too.

## Citations

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/CompanyScraper/parsers/leadiq.py`
  lines: 6-38
  symbol: `LeadiqScrapper`
  excerpt: |
    domain = 'leadiq.com'; search_term = "site:leadiq.com {}"
    keywords = ['Email Formats & Email Address', 'Company Overview', ...]

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/CompanyScraper/parsers/rocket.py`
  lines: 6-33
  symbol: `RocketReachScrapper`
  excerpt: |
    domain = 'https://rocketreach.co/'
    search_term = "site:rocketreach.co '{}'"
    def _extract_codes(self, value): ...  # NAICS/SIC numbers from <a> tags

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/CompanyScraper/parsers/zoominfo.py`
  lines: 29-42
  symbol: `ZoomInfoScrapper.get`
  excerpt: |
    async def get(self, url, headers):
        self.use_proxy = True; self._free_proxy = False
        self.use_undetected = True
        driver = await self.get_driver()
        driver.get(url); return driver.page_source

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/CompanyScraper/parsers/siccode.py`
  lines: 45-104
  symbol: `SicCodeScrapper.scrapping`
  excerpt: |
    result["sic_code"], result["industry"] = sic.split(' - ')
    result["naics_code"], result["category"] = naics.split(' - ')
    result["city"|"state"|"zip_code"|"country"|"metro_area"] = ...

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/CompanyScraper/parsers/visualvisitor.py`
  lines: 40-45
  symbol: `VisualVisitorScrapper.scrapping`
  excerpt: |
    result.update({
        'source_platform': 'rocketreach',   # <-- copy-paste bug
        ...})

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/CompanyScraper/parsers/explorium.py`
  lines: 105-154
  symbol: `ExploriumScrapper._extract_naics_sic`
  excerpt: |
    naics_section = document.find('div', {'data-id': 'company-stat-naics'})
    industry_desc = entry.get('aria-label', '').strip()
