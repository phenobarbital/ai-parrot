---
id: F006
query_id: Q006
type: grep
intent: Check for existing LeadIQ code in ai-parrot-tools (dedupe risk)
executed_at: 2026-07-13T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F006 — Existing `scrape_leadiq` is scraping, NOT the API

## Summary

The only pre-existing LeadIQ code in ai-parrot-tools is
`CompanyInfoToolkit.scrape_leadiq`, which does a Google `site:leadiq.com`
search + Selenium/BeautifulSoup HTML scrape of the public leadiq.com page.
It does **not** use the official GraphQL API or `LEADIQ_API_KEY`. The new
tool is therefore a distinct, complementary capability (authenticated,
structured, rate-limited API) rather than a duplicate — it should live in a
separate `leadiq/` module to avoid conflation and Selenium coupling.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py`
  lines: 675-693
  symbol: `scrape_leadiq`
  excerpt: |
    @tool_schema(CompanyInput)
    async def scrape_leadiq(self, company_name: str, ...):
        site = "leadiq.com"
        search_term = f"site:leadiq.com {standardized_name}"
        # Google CSE + Selenium fetch + bs4 parse — no LEADIQ_API_KEY, no GraphQL

## Notes

`grep -rn "LEADIQ_API_KEY|leadiq"` over `src/` returned only company_info
references — confirming no existing API client to extend or collide with.
