---
id: F014
query_id: Q037
type: grep
intent: Example wiring of the browsing/business toolkits to copy for the Hooba agent.
executed_at: 2026-09-25T11:30:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F014 — Two reference wirings exist: the untracked hooba_agent (WebBrowsingToolkit + navconfig resolver) and the tracked webbrowsing examples

## Summary

`examples/agents/web/services/hooba_agent.py` + `seed_catalog.py` (untracked, F007), `examples/agents/webbrowser/webbrowsing_agent.py`, `examples/webbrowsing/{browsing_agent.py, seed_catalog.py, local_demo.py, README.md}` and `examples/clients/jev_bestbuy_live.py` all instantiate `WebBrowsingToolkit(`. No example wires `BusinessAutomationToolkit` (its wiring lives only in tests `tests/business_automation/conftest.py`, `test_toolkit.py`, `test_submit_gate.py`, `test_fixture_site_e2e.py`).

## Citations


- path: `examples/agents/webbrowser/webbrowsing_agent.py`
  lines: 1-1
  symbol: `example`
  excerpt: |
    Web-navigation agent example — WebBrowsingToolkit + Chrome profile

- path: `examples/webbrowsing/browsing_agent.py`
  lines: 1-1
  symbol: `example`
  excerpt: |
    Example Agent wired with the WebBrowsingToolkit and a pre-built catalog

- path: `packages/ai-parrot-tools/tests/business_automation/conftest.py`
  lines: 1-1
  symbol: `fixtures`
  excerpt: |
    (wiki_related: references BusinessAutomationToolkit)

- path: `packages/ai-parrot-tools/tests/business_automation/test_submit_gate.py`
  lines: 1-1
  symbol: `submit-gate tests`
