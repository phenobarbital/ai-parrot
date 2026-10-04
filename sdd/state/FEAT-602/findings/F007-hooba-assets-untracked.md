---
id: F007
query_id: Q011
type: grep
intent: Prove/disprove that public code holds zero Hooba identifiers; locate private Hooba assets.
executed_at: 2026-09-25T11:30:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F007 — Hooba appears in public code only as docstring examples; the real, working Playwright operativa is an UNTRACKED local example with six navigation-only actions

## Summary

Tracked packages mention "hooba" only in docstrings/README examples (`scraping/models.py:499`, `browsing/readme.md`, `browsing/catalog.py:7,147`, `browsing/toolkit.py:8,203-206`) and in tests as a placeholder provider name. The live assets are `examples/agents/web/services/{hooba_agent.py, seed_catalog.py, README.md, catalog/hooba/*.json}` — **not tracked by git** (`git ls-files` returns only `docs/business-automation-runbook.md`; `examples/**/*.py` is gitignored). `hooba_agent.py` builds `WebBrowsingToolkit(catalog_dir, driver_type="playwright", browser="chrome", headless, credential_resolver=resolve_hooba_credentials, confirm_runs=False)` with credentials from navconfig `HOOBA_USERNAME`/`HOOBA_PASSWORD`; `HoobaNavigatorAgent(Agent)` + `--smoke` mode. Catalog `_site.json`: base_url `https://app.hooba.com`. Actions: `hooba-login` (navigate `/es/login?returnUrl=%2Fdashboard` → conditional `authenticate` form with `credential_provider: "hooba"` → wait url `/dashboard`), plus `hooba-dashboard`, `hooba-settings`, `hooba-budgets`, `hooba-invoices` (navigate `/es/sales/invoices`, requires hooba-login), `hooba-products`. **No data-entry action exists** (no invoice creation, no expense registration, no upload).

## Citations


- path: `examples/agents/web/services/hooba_agent.py`
  lines: 1-25, 62-91
  symbol: `resolve_hooba_credentials, build_toolkit, HoobaNavigatorAgent`
  excerpt: |
    return WebBrowsingToolkit(catalog_dir=catalog_dir, driver_type=driver_type, browser="chrome", headless=headless, credential_resolver=resolve_hooba_credentials, confirm_runs=False)

- path: `examples/agents/web/services/seed_catalog.py`
  lines: 23-39
  symbol: `CATALOG_DIR, SITE_NAME, CREDENTIAL_PROVIDER, SECTIONS`
  excerpt: |
    CATALOG_DIR = Path(__file__).parent / "catalog"; SITE_NAME = "hooba"; CREDENTIAL_PROVIDER = "hooba"; SECTIONS: dict[str, tuple[str, str, str]]

- path: `examples/agents/web/services/catalog/hooba/_site.json`
  lines: 1-13
  symbol: `site metadata`
  excerpt: |
    "site": "hooba", "base_url": "https://app.hooba.com", "aliases": ["hooba", "hooba.com", "app.hooba.com", "crm"]

- path: `examples/agents/web/services/catalog/hooba/hooba-login.json`
  lines: 1-45
  symbol: `hooba-login`
  excerpt: |
    {"action": "navigate", "url": "https://app.hooba.com/es/login?returnUrl=%2Fdashboard"} → conditional exists input[type="email"] → {"action": "authenticate", "method": "form", "credential_provider": "hooba", "username_selector": "input[type=\"email\"]", ...} → wait url_contains /dashboard

- path: `examples/agents/web/services/catalog/hooba/hooba-invoices.json`
  lines: 1-30
  symbol: `hooba-invoices`
  excerpt: |
    "kind": "navigation", steps: navigate https://app.hooba.com/es/sales/invoices; "requires": ["hooba-login"]

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/models.py`
  lines: 499
  symbol: `docstring`
  excerpt: |
    (e.g. 'hooba') instead of reading the literal username/password

- path: `docs/business-automation-runbook.md`
  lines: 1-36
  symbol: `runbook`
  excerpt: |
    ## 1. Plans-directory contract ... ## 2. Submit-gate policy (Decision D2)

## Notes

Resolves the auto-finance brainstorm open item "Locate and share the path of the private hooba_agent assets" (F013): they live at examples/agents/web/services/ on this machine, untracked.

