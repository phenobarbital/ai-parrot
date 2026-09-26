---
id: F011
query_id: Q027
type: grep
intent: Toolkit registration, optional extras and existing tests.
executed_at: 2026-09-25T11:30:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F011 — Registration and packaging conventions for a new parrot_tools subpackage are explicit: TOOL_REGISTRY entry + an optional-dependency extra + tests/<pkg>/

## Summary

`parrot_tools/__init__.py::TOOL_REGISTRY` (line 13) maps names to dotted paths, e.g. `"web_browsing": "parrot_tools.browsing.toolkit.WebBrowsingToolkit"` (35), `"business_automation": "...BusinessAutomationToolkit"` (36). `packages/ai-parrot-tools/pyproject.toml` extras: `excel = ["openpyxl>=3.1", "odfpy>=1.4"]` (66), `scraping = [selenium, undetected-chromedriver, webdriver-manager, "playwright>=1.52", rapidfuzz]` (73), `business_automation = ["pandas>=2.0", "ai-parrot-loaders"]` (107), all aggregated in `all` (108). `prance` is not in this package's extras (OpenAPIToolkit lives in core). Tests: `packages/ai-parrot-tools/tests/business_automation/{conftest.py, fixtures/, test_fixture_site_e2e.py, test_ingest.py, test_memory.py, test_smoke.py, test_store.py, test_submit_gate.py, test_toolkit.py}`; browsing tests under `tests/tools/browsing/`.

## Citations


- path: `packages/ai-parrot-tools/src/parrot_tools/__init__.py`
  lines: 13, 35-36
  symbol: `TOOL_REGISTRY`
  excerpt: |
    "web_browsing": "parrot_tools.browsing.toolkit.WebBrowsingToolkit",
    "business_automation": "parrot_tools.business_automation.toolkit.BusinessAutomationToolkit",

- path: `packages/ai-parrot-tools/pyproject.toml`
  lines: 37, 66, 73, 107-108
  symbol: `optional-dependencies`
  excerpt: |
    excel = ["openpyxl>=3.1", "odfpy>=1.4"]
    scraping = [..., "playwright>=1.52", ...]
    business_automation = ["pandas>=2.0", "ai-parrot-loaders"]

- path: `packages/ai-parrot-tools/tests/business_automation/`
  lines: listing
  symbol: `tests`
  excerpt: |
    conftest.py fixtures/ test_fixture_site_e2e.py test_ingest.py test_memory.py test_smoke.py test_store.py test_submit_gate.py test_toolkit.py

- path: `packages/ai-parrot-tools/tests/business_automation/fixtures/broker.py`
  lines: 1-1
  symbol: `fake_broker`
  excerpt: |
    a real CredentialBroker for FEAT-455 real-browser tests (wiki)
