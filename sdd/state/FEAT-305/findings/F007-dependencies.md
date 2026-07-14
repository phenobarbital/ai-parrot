---
id: F007
query_id: Q009
type: grep
intent: Dependency and credential coupling
executed_at: 2026-07-13T22:44:00Z
parent_id: null
depth: 0
---

# F007 — Dependency availability in ai-parrot

## Summary

ai-parrot's pyproject already carries almost every dependency CompanyScraper
uses: `beautifulsoup4>=4.12` (core, line 42), `backoff==2.2.1` (core, line
45), `duckduckgo-search==8.1.1` (lines 211/267/300 — extras), `selenium==
4.35.0` + `undetected-chromedriver==3.5.5` + `playwright==1.52.0` (inside the
`agents` extra). **`fuzzywuzzy` (used for name matching in flowtask) is NOT a
parrot dependency** — a fuzzy-matching dep (rapidfuzz/thefuzz) or a stdlib
`difflib.SequenceMatcher` substitute is needed. No navconfig credential keys
are required by the scrapers themselves (public pages + cookies); proxy
credentials and Google CSE keys already resolve via parrot.conf
(GOOGLE_SEARCH_API_KEY / GOOGLE_SEARCH_ENGINE_ID, F005).

## Citations

- path: `packages/ai-parrot/pyproject.toml`
  lines: 42-45
  excerpt: |
    "beautifulsoup4>=4.12",
    "backoff==2.2.1",
- path: `packages/ai-parrot/pyproject.toml`
  lines: 211, 224
  excerpt: |
    "duckduckgo-search==8.1.1",
    "selenium==4.35.0",   # in [agents] extra with undetected-chromedriver

## Notes

fuzzywuzzy/rapidfuzz: no grep hits in pyproject.
