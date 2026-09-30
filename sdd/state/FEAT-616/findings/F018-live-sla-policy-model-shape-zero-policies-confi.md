---
id: F018
query_id: L006
type: rpc
intent: live: SLA models, alarms
executed_at: 2026-09-30T23:58:00Z
duration_ms: 0
parent_id: None
depth: 0
---

# F018 — Live: SLA policy model shape; zero policies configured

## Summary

`sh.helpdesk.sla`: `name` R, `sh_team_id` R, `sh_days/sh_hours/sh_minutes` R, `sh_sla_target_type` (`reaching_stage|assign_to`), `sh_stage_id`, `sh_ticket_type_id`, `company_id`, `sla_ticket_count`. `sh.helpdesk.sla.status` (per ticket × policy): `sh_sla_id` R, `sh_ticket_id`, `sh_sla_stage_id` ro, `sh_deadline` ro, `sh_done_sla_date`, `sh_exceeded_hours`, `sh_status`. `sh.helpdesk.sla.analysis` is a report model. `sh.ticket.alarm`: `name`, `type` R (`email|popup`), `sh_remind_before`, `sh_reminder_unit` R. Counts on staging: 0 SLA policies, 0 sla.status rows, 0 alarms; every sampled ticket has `sh_sla_deadline=False`, `sh_status=False`. The API user holds the `Helpdesk SLA Policy` and `Helpdesk Ticket Alarm` groups.

## Citations

- path: `sdd/state/FEAT-616/findings/live/03_fields.json`
  symbol: `sh.helpdesk.sla`, `sh.helpdesk.sla.status`, `sh.helpdesk.sla.analysis`
- path: `sdd/state/FEAT-616/findings/live/10_stages_fields.json`
  symbol: `fields:sh.ticket.alarm`
- path: `sdd/state/FEAT-616/findings/live/12_distribution_acl.json`
  symbol: api_user_groups

## Notes

SLA policy CRUD is model-level (`create`/`write` on `sh.helpdesk.sla`); how policies attach to tickets (`sh_sla_policy_ids`) and when `sla.status` rows are computed is Softhealer logic not observable without a live policy.
