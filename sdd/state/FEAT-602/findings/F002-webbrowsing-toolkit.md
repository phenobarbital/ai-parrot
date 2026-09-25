---
id: F002
query_id: Q002
type: wiki_query
intent: Orient: locate WebBrowsingToolkit (catalogued Playwright/Selenium site actions).
executed_at: 2026-09-25T11:30:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F002 — WebBrowsingToolkit gives catalogued, deterministic per-site actions over a persistent Playwright/Selenium session

## Summary

`parrot_tools/browsing/toolkit.py` extends `WebScrapingToolkit` with a per-site action catalog (one folder per site, one JSON per action, `_site.json` metadata), `run_site_action`/`run_site_sequence`/`execute_web_task`, `requires` auto-injection (login before pages), `credential_resolver`, `human_channel`, `confirm_runs`. Driver fixed at construction (Playwright or Selenium); `PlaywrightDriver` lives in `scraping/drivers/playwright_driver.py`. README already uses Hooba as the worked example (site `hooba-es`, `authenticate` with `credential_provider: "hooba"`, an `invoice-draft` composite). Stable: three commits 2026-08-26, none since.

## Citations


- path: `packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py`
  lines: 1-30
  symbol: `WebBrowsingToolkit`
  excerpt: |
    Extends WebScrapingToolkit with a per-site **action catalog** ... "inicia sesión en Hooba" ... composing several actions (login -> dashboard -> CRM -> ...) into one sequence over a single persistent browser session.

- path: `packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py`
  lines: __init__ signature
  symbol: `WebBrowsingToolkit.__init__`
  excerpt: |
    def __init__(self, catalog_dir="browsing_catalog", user_data_dir=None, profile_directory=None, browser_channel=None, max_loop_iterations=..., credential_resolver=None, human_channel=None, session_based=True, headless=False, confirm_runs=True, **kwargs)

- path: `packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py`
  lines: API outline
  symbol: `register_site, list_sites, list_site_actions, get_site_action, save_site_action, delete_site_action, run_site_action, run_site_sequence, execute_web_task, close_browser`

- path: `packages/ai-parrot-tools/src/parrot_tools/browsing/readme.md`
  lines: 48-104
  symbol: `worked example`
  excerpt: |
    base_url="https://hooba.es", title="Hooba", aliases=["hooba"] ... {"action": "authenticate", "credential_provider": "hooba", ... site="hooba", name="invoice-draft", kind="composite"

- path: `packages/ai-parrot-tools/src/parrot_tools/browsing/catalog.py`
  lines: 7, 147
  symbol: `catalog layout / resolve`
  excerpt: |
    hooba-es/ ... Resolve a natural reference ("hooba", "hooba.es") to a site.

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py`
  lines: 15
  symbol: `PlaywrightDriver`
  excerpt: |
    class PlaywrightDriver(AbstractDriver):

## Notes

git log (Q036): 1d4f4abfd8 2026-08-26 execute_web_task; 74262cab5c harden per adversarial review; f09e2e5729 WebBrowsingToolkit initial.

