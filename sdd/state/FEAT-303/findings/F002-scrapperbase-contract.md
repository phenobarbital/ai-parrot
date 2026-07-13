---
id: F002
query_id: Q002
type: read
intent: Extractor base class contract
executed_at: 2026-07-13T22:40:00Z
parent_id: null
depth: 0
---

# F002 — ScrapperBase: the per-source extractor contract

## Summary

Each source is a `ScrapperBase(SeleniumService, HTTPService)` subclass with 4
class attributes — `domain`, `search_term` (a `site:{domain} {}` template),
`cookies`, `keywords` (title markers used to validate search hits) — and two
abstract methods: `define_search_term(term)` and
`async scrapping(document: BeautifulSoup, idx, row) -> (idx, dict)`. Shared
helpers: `get(url, headers)` (proxy-enabled `_get`), `_parse_address` (two
regexes → address/state/zipcode/country), `_standardize_name`.

## Citations

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/CompanyScraper/parsers/base.py`
  lines: 8-36
  symbol: `ScrapperBase`
  excerpt: |
    class ScrapperBase(SeleniumService, HTTPService):
        domain: str
        search_term: str
        cookies: Any
        keywords: List[str]
        @abstractmethod
        async def scrapping(self, document: bs, idx: int, row: dict): ...
        @abstractmethod
        def define_search_term(self, term: str): ...
        async def get(self, url, headers):
            return await self._get(url, headers=headers, use_proxy=True)

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/CompanyScraper/parsers/base.py`
  lines: 38-96
  symbol: `_parse_address`
  excerpt: |
    pattern1 = r'^.*,\s+([^,]+?)\s+([\w\s-]+)\s+([A-Z]{2})$'
    pattern2 = r'^.*,\s*([^,]+?),\s+([\w\s-]+?)\s*([A-Z]{2})'
