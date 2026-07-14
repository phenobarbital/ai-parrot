---
id: F005
query_id: Q006+Q011
type: read
intent: Existing scraping/search infrastructure in parrot
executed_at: 2026-07-13T22:42:00Z
parent_id: null
depth: 0
---

# F005 — parrot already has HTTPService with proxy + DDG + Google search

## Summary

`parrot/interfaces/http.py` (1600+ lines) contains an `HTTPService` mixin that
is the same lineage as flowtask's: proxy rotation via `proxylists`
(Oxylabs/Decodo/Geonode/FreeProxy, `use_proxy`/`proxy_type`/`_free_proxy`
attrs), `_get`/`_post`/`api_get`/`api_post`, **`_search_duckduckgo`** (DDGS)
and **`_search_google`** (Google CSE via `googleapiclient`, keys from
`GOOGLE_SEARCH_API_KEY`/`GOOGLE_SEARCH_ENGINE_ID` in parrot.conf), backoff,
BeautifulSoup + lxml imports, `primp`, aiohttp AND httpx AND requests.
This means the search-and-fetch layer the CompanyScraper depends on already
exists in ai-parrot — the port does not need to bring flowtask interfaces.
**No `SeleniumService` exists in parrot** (grep: no matches under
src/parrot/), so ZoomInfo's undetected-chromedriver path and the Selenium
Google-CSE fallback have no direct equivalent.

## Citations

- path: `packages/ai-parrot/src/parrot/interfaces/http.py`
  lines: 126-149
  symbol: `HTTPService`
  excerpt: |
    class HTTPService(CredentialsInterface, PandasDataframe):
        self.use_proxy: bool = kwargs.pop("use_proxy", False)
        self.proxy_type: str = kwargs.pop('proxy_type', 'oxylabs')
        self._free_proxy: bool = kwargs.pop('use_free_proxy', True)
        self.google_api_key = kwargs.pop('google_api_key', GOOGLE_SEARCH_API_KEY)
        self.google_cse = kwargs.pop('google_cse', GOOGLE_SEARCH_ENGINE_ID)

- path: `packages/ai-parrot/src/parrot/interfaces/http.py`
  lines: 1327, 1412
  symbol: `_search_duckduckgo, _search_google`
  excerpt: |
    async def _search_duckduckgo(...)
    async def _search_google(...)

- path: `packages/ai-parrot/src/parrot/interfaces/http.py`
  lines: 956, 1059
  symbol: `_get, _post`
  excerpt: |
    async def _get(...)   # proxy-aware fetch
    async def _post(...)

- path: `packages/ai-parrot/src/parrot/interfaces/http.py`
  lines: 20-40
  symbol: imports
  excerpt: |
    from duckduckgo_search import DDGS
    from proxylists.proxies import FreeProxy, Oxylabs, Decodo, Geonode
    from bs4 import BeautifulSoup as bs

## Notes

grep for `SeleniumService|get_driver` in src/parrot/ returned only unrelated
db-driver hits — confirms absence of a Selenium interface in parrot.
