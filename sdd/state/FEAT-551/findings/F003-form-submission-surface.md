---
id: F003
query_id: Q003
type: wiki_query
intent: Locate form submission endpoint
executed_at: 2026-09-10T22:27:13Z
duration_ms: 0
parent_id: null
depth: 0
---

# F003 — Form submission surface (wiki)

## Summary
The submit path is `FormAPIHandler.submit_data` (POST `.../forms/{form_uid}/data`), heavily documented by FEAT-457/458/188 artifacts. FEAT-544 TASK-3075 (active, not done) plans to make that same endpoint dual-wire (legacy JSON + A2UI action envelope).

## Citations
- path: `sdd/tasks/active/TASK-3075-submit-data-dual-wire.md`
  symbol: TASK-3075 (score 26.91) — pending
- path: `sdd/state/FEAT-544/findings/F009-submit-data-contract.md`
  symbol: prior digest of submit_data contract (score 26.77)
