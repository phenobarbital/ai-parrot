---
kind: inline
jira_key: null
fetched_at: 2026-06-02T00:00:00Z
summary_oneline: OdooFieldServiceToolkit — domain @tools over OdooToolkit for OCA fieldservice + fieldservice_stock route management
---

# OdooFieldServiceToolkit (5.a)

Custom `@tool`s over the native Odoo toolkit, operating on the OCA
`fieldservice` + `fieldservice_stock` stack. Odoo is the system of record.

| Tool | Signature | Does | HITL | Source |
|------|-----------|------|------|--------|
| `get_today_fsos` | `(rep_id) -> list` | The rep's `fsm.order`s for today, ordered by Navigator sequence | none | Odoo |
| `get_loading_summary` | `(rep_id, date) -> list` | Consolidated pick: product → total qty across today's outbound pickings | none | Odoo |
| `get_kiosk` | `(location_id) -> dict` | `fsm.location` details: name, partner address, coords, planogram ref | none | Odoo |
| `create_return_draft` | `(order_id, lines, reason, photo?) -> picking` | Draft return picking for product coming back | rep confirm | Odoo |
| `validate_loading_pick` | `(rep_id, pin) -> result` | Validate the day's loading pick (start of route) | manager PIN | Odoo |
| `validate_returns` | `(rep_id, pin) -> result` | Validate all draft return pickings (end of day) | manager PIN | Odoo |
| `get_return_summary` | `(rep_id, date) -> list` | EOD: product → qty to return to warehouse (from draft return pickings) | none | Odoo |
| `complete_fso` | `(order_id) -> stage` | Advance `fsm.order` stage when a kiosk is finished | rep confirm | Odoo |
