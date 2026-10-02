---
id: F015
query_id: L003
type: rpc
intent: live: sh.helpdesk.ticket fields
executed_at: 2026-09-30T23:58:00Z
duration_ms: 0
parent_id: None
depth: 0
---

# F015 — Live: sh.helpdesk.ticket has 127 fields; key groups

## Summary

Required non-readonly: `state` (selection `customer_replied|staff_replied`, labelled "Replied Status" — NOT a workflow state) and `partner_id`. Workflow: `stage_id → helpdesk.stages`, computed stage booleans `open_boolean/done_stage_boolean/closed_stage_boolean/cancel_stage_boolean/reopen_stage_boolean`, `done_button_boolean/cancel_button_boolean`, `close_date/close_by`, `cancel_date/cancel_by/cancel_reason`, `replied_date`, `helpdesk_stage_history_line`. Classification: `team_id`, `team_head`, `user_id`, `sh_user_ids` (multi-assign), `category_id`, `sub_category_id`, `ticket_type`, `subject_id → helpdesk.sub.type`, `priority → helpdesk.priority` (m2o) plus legacy `priority_new` selection 1-6, `tag_ids`. Content: `name` (auto `TICKET#…`), `description` html, `comment`, `customer_comment`, `email`, `email_cc`, `email_subject`, `mobile_no`, `person_name`, `attachment_ids`, `product_ids`. SLA: `sh_sla_policy_ids`, `sh_sla_status_ids`, `sh_sla_deadline` (ro), `sh_due_date`, `sh_status` (sla_failed|sla_passed|sh_partially_passed), `sh_days_to_reach/late`, `sh_ticket_alarm_ids`. Timesheet: `timehseet_ids` (sic), `ticket_running/ticket_run`, `start_time/end_time/total_time`. Links: `sh_sale_order_ids`, `sh_purchase_order_ids`, `sh_invoice_ids`, `sh_lead_ids`, `task_ids`, `sh_merge_ticket_ids`. Origin: `ticket_from_portal`, `ticket_from_website`. mail.thread + activities present (`message_ids`, `activity_ids`). TROC adds `extra_field_ids`, `extra_field_count`, `assignee_on_leave`, `category_id_domain`; dynamic forms add `dynamic_form_submission_id`, `dynamic_form_unmapped_*`.

## Citations

- path: `sdd/state/FEAT-616/findings/live/03_fields.json`
  symbol: `sh.helpdesk.ticket`
- path: `sdd/state/FEAT-616/findings/live/10_stages_fields.json`
  symbol: `fields:sh.ticket.alarm`, `fields:helpdesk.priority`, `fields:sh.helpdesk.ticket.extra_fields`, `fields:dynamic.form.submission`

## Notes

`state` is a trap for an LLM-facing schema: it means reply-direction, not lifecycle. Lifecycle is `stage_id` + the computed booleans. `priority` (m2o) and `priority_new` (selection) coexist.
