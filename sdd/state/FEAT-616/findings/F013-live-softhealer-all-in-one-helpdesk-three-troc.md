---
id: F013
query_id: L002
type: rpc
intent: live: installed helpdesk/softhealer/troc modules
executed_at: 2026-09-30T23:58:00Z
duration_ms: 0
parent_id: None
depth: 0
---

# F013 — Live: Softhealer All-in-One Helpdesk + three TROC bridge modules

## Summary

Installed: `sh_all_in_one_helpdesk` 19.0.0.0.1 (Softhealer Technologies, OPL-1; depends mail, portal, product, resource, sale_management, purchase, account, hr_timesheet, crm, project); `troc_helpdesk` 19.0.1.32.0 (TROC Global, LGPL-3, "TROC extensions for sh_all_in_one_helpdesk", depends `data_injector_api`); `dynamic_form_helpdesk` 19.0.1.1.0 (T-ROC — bridge between WebbyCrown dynamic forms and `sh.helpdesk.ticket`, partner resolution hooks); `troc_helpdesk_dynamic_forms` 19.0.1.2.1 (Navigator QuerySource/NavAPI form engine; unmapped answers → `sh.helpdesk.ticket.extra_fields`, webhook write-path). Plus hr_timesheet/sale_timesheet/spreadsheet dashboards.

## Citations

- path: `sdd/state/FEAT-616/findings/live/01_modules.json`
  symbol: sh_all_in_one_helpdesk, troc_helpdesk, dynamic_form_helpdesk, troc_helpdesk_dynamic_forms
- path: `sdd/state/FEAT-616/findings/live/11_troc_modules.json`
  symbol: modules_detail (summary/description/depends)

## Notes

The vendor is confirmed: Softhealer Technologies (India). TROC owns three custom layers on top, at version 1.32 — the instance is heavily customised, not vanilla Softhealer.
