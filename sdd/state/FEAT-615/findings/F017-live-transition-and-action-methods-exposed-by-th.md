---
id: F017
query_id: L004
type: rpc
intent: live: ticket form/kanban/list views -> transition buttons
executed_at: 2026-09-30T23:58:00Z
duration_ms: 0
parent_id: None
depth: 0
---

# F017 — Live: transition and action methods exposed by the ticket form

## Summary

Base form `sh_all_in_one_helpdesk.sh_helpdesk_ticket_form_view` buttons (type=object): `action_approve` (hidden when cancel/done/closed stage), `action_reply`, `action_send_whatsapp`, `action_done` "Resolved Ticket" (visible iff `done_button_boolean`), `action_closed` "Close Ticket" (iff `done_stage_boolean`), `action_cancel` "Cancel Ticket" (iff `cancel_button_boolean`), `action_open` "Re-Open Ticket" (iff `open_boolean`), `preview_ticket`. Inherited views add `action_ticket_start/action_ticket_end` (timesheet timer), `action_sale_create_order`, `action_create_purchase_order`, `action_create_invoice`, `action_create_lead/action_create_opportunity`, `create_task`. TROC view `sh_helpdesk_ticket_form_view_as_buttons` adds `action_take_ticket` (hidden when `user_id == uid`) and `action_open_reassign` (opens `sh.helpdesk.reassign.wizard`, fields `ticket_id`, `new_user_id`, `team_member_ids`). Wizards: mass update (`helpdesk_stages`, `assign_to`, `team_id`, followers add/remove) and merge (`sh_select_type new|existing`, `sh_select_merge_type close|cancel|done|remove|do_nothing`).

## Citations

- path: `sdd/state/FEAT-615/findings/live/08_view_buttons.json`
  symbol: form_buttons per view
- path: `sdd/state/FEAT-615/findings/live/03_fields.json`
  symbol: `sh.helpdesk.reassign.wizard`, `sh.helpdesk.ticket.mass.update.wizard`, `sh.helpdesk.ticket.merge.ticket.wizard`

## Notes

Method *names* and visibility guards are verified; their server-side effects (which fields they set, whether `action_cancel`/`action_done` open a wizard or require a reason) are NOT — no write was performed on staging. `get_views` itself is unreachable over JSON-2 (F021); the arch was read from `ir.ui.view.arch_db` instead.
