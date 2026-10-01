---
id: F006
query_id: Q006
type: read
intent: in-flight FEAT-614 JSON-2 fix touching the same files
executed_at: 2026-09-30T23:58:00Z
duration_ms: 0
parent_id: None
depth: 0
---

# F006 — FEAT-614 (in flight) fixes JSON-2 read_group mapping on the same files

## Summary

FEAT-614 (`odoo-json2-domain-first-methods.spec.md`, approved 2026-09-30, TASK-3883 active) adds `_DOMAIN_FIRST_METHODS` to `json2.py` and drops `lazy` for Odoo 19 `formatted_read_group` in `aggregate_records` (`toolkit.py:994`), adding `having`. It was discovered by `agent:odoo_hd` against `pokemon.helpdesk.staging` on `sh.helpdesk.ticket` (ledger `issue:c32c408ded92`). It explicitly leaves `_looks_like_ids`, XML-RPC/JSON-RPC and `odoointerface.py` untouched.

## Citations

- path: `sdd/specs/odoo-json2-domain-first-methods.spec.md`
  lines: 1-60
  symbol: FEAT-614 §1 Motivation
  excerpt: |
    Observed live on `pokemon.helpdesk.staging` (Odoo 19.0, `json2` transport) when
    the helpdesk agent called the tool on `sh.helpdesk.ticket`; recorded in the work
    ledger as `issue:c32c408ded92`
- path: `sdd/specs/odoo-json2-domain-first-methods.spec.md`
  lines: 100-140
  symbol: `_DOMAIN_FIRST_METHODS` (planned)
- path: `sdd/tasks/active/TASK-3883-json2-domain-first-mapping.md`
- path: `sdd/ledger/issues.jsonl`
  symbol: `issue:c32c408ded92`
- path: `packages/ai-parrot/tests/test_odoo_json2_transport.py`
- path: `packages/ai-parrot/tests/test_odoo_toolkit.py`

## Notes

A helpdesk feature must sequence after (or coordinate with) FEAT-614 because both edit `toolkit.py`, `inputs.py`, `test_odoo_toolkit.py`. An existing helpdesk agent (`odoo_hd`) already runs against this instance but is not in this repo (F008).
