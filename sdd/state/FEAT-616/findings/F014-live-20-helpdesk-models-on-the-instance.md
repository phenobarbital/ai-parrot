---
id: F014
query_id: L003
type: rpc
intent: live: helpdesk models
executed_at: 2026-09-30T23:58:00Z
duration_ms: 0
parent_id: None
depth: 0
---

# F014 — Live: 20 helpdesk models on the instance

## Summary

`ir.model` matching helpdesk/sh.: core `sh.helpdesk.ticket`, `sh.helpdesk.team`, `helpdesk.stages`, `helpdesk.category`, `helpdesk.subcategory`, `helpdesk.priority`, `helpdesk.sub.type`, `helpdesk.tags`, `sh.helpdesk.ticket.type`; SLA `sh.helpdesk.sla`, `sh.helpdesk.sla.status`, `sh.helpdesk.sla.analysis`; history `sh.helpdesk.ticket.stage.info`; alarms `sh.ticket.alarm`; wizards `sh.helpdesk.reassign.wizard` (TROC), `sh.helpdesk.ticket.mass.update.wizard`, `sh.helpdesk.ticket.merge.ticket.wizard`; TROC `sh.helpdesk.ticket.extra_fields`, `sh.helpdesk.webhook.error_dedupe`; dynamic forms `dynamic.form`, `dynamic.form.submission`. Note the mixed naming: Softhealer uses both `helpdesk.*` and `sh.helpdesk.*`.

## Citations

- path: `sdd/state/FEAT-616/findings/live/02_models.json`
  symbol: model list
- path: `sdd/state/FEAT-616/findings/live/03_fields.json`
  symbol: fields_get per model

## Notes

—
