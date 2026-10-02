---
id: F021
query_id: L009
type: rpc
intent: live: reproduce JSON-2 mapping gaps
executed_at: 2026-09-30T23:58:00Z
duration_ms: 0
parent_id: None
depth: 0
---

# F021 — Live: JSON-2 gaps reproduced (formatted_read_group, get_views)

## Summary

`formatted_read_group([[]], groupby=[stage_id], aggregates=[__count])` over JSON-2 → HTTP 422 `missing a required argument: 'domain'` (exact FEAT-614 symptom). `get_views` → client-side `OdooRPCError: JSON-2 transport cannot map positional args for method 'get_views'`. `ir.model.modules` is non-stored so cannot be searched. `name_search`, `search_read`, `search_count`, `fields_get`, `read`, `check_access_rights` all work.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py`
  lines: 90-162
  symbol: `Json2Transport._build_body`
- path: `sdd/specs/odoo-json2-domain-first-methods.spec.md`
  symbol: FEAT-614

## Notes

Any helpdesk "stats" tool (tickets per stage/team, SLA pass rate) depends on FEAT-614 landing; a stage-count fallback via N × `search_count` works today.
