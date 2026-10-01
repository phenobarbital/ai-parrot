---
id: F016
query_id: L005
type: rpc
intent: live: stages semantics, stage history, server actions, crons
executed_at: 2026-09-30T23:58:00Z
duration_ms: 0
parent_id: None
depth: 0
---

# F016 — Live: 5 linear stages, stage flags, history lines, auto-close cron

## Summary

`helpdesk.stages` fields: `name` R, `sequence`, `is_done_button_visible`, `is_cancel_button_visible`, `sh_next_stage` (m2o self), `sh_group_ids`, `mail_template_ids`, `company_id` — no `fold`/`is_close`. Configured stages: New(4, seq 0) → Open(22) → Pending close(23) → Pending reminder(24) → Closed(21, TROC xml id `helpdesk_stage_apple_closed`), chained via `sh_next_stage`; both button flags are False on every stage, so the form's *Resolved/Cancel* buttons are hidden here. Distribution (42 tickets): New 22, Open 4, Pending close 10, Pending reminder 0, Closed 6. `sh.helpdesk.ticket.stage.info` rows record `stage_name`, `date_in/date_out`, `date_in_by`, `day_diff/time_diff` per stage visit (56 rows). Server actions on the ticket: "Mass Update Ticket", "Merge Ticket" (bindings) and cron "Auto Close Helpdesk Ticket" (daily). `base.automation` is not installed.

## Citations

- path: `sdd/state/FEAT-616/findings/live/10_stages_fields.json`
  symbol: stages, stage_xmlids
- path: `sdd/state/FEAT-616/findings/live/12_distribution_acl.json`
  symbol: by_stage
- path: `sdd/state/FEAT-616/findings/live/03_fields.json`
  symbol: `helpdesk.stages`, `sh.helpdesk.ticket.stage.info`

## Notes

Stage ids are instance-specific (4/22/23/24/21) — tools must resolve stages by name/`sh_next_stage`, never hard-code ids. "Done" semantics on this tenant are expressed by stage `Closed`, not by the Softhealer done flag.
