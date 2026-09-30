---
id: F019
query_id: L006
type: rpc
intent: live: reference data and TROC extra fields
executed_at: 2026-09-30T23:58:00Z
duration_ms: 0
parent_id: None
depth: 0
---

# F019 — Live: reference data is kiosk-support specific; extra fields carry the form payload

## Summary

Reference data on the tenant (company "Pokémon"): 11 categories (Black Screen, Card Reader Issue, Door Will Not Open, …, Other Please Describe), 4 priorities (Low/Medium/High/Critical), 1 ticket type (Kiosks Issues), 1 sub type (Kiosk Failure), 1 subcategory (Kiosks Failure), 1 team (Compliance), 0 tags. `helpdesk.category` has `team_id` and `is_helpdesk_manager` (TROC). 643 `sh.helpdesk.ticket.extra_fields` rows (`ticket_id`, `field_name`, `name` label, `value` text) — e.g. ticket 68 carries 16 keys (`organization_id`, `poke_locationid`, `poke_location_address/city/state/zipcode`, `poke_kiosk_merchandised`, `attachments`, `field_26` "Kiosk Number"…). Tickets originate from website dynamic forms (`ticket_from_website=True`, `dynamic_form_submission_id`). `mail.message` rows on a ticket are readable (notes + comments); `name_search` works over JSON-2.

## Citations

- path: `sdd/state/FEAT-615/findings/live/03_fields.json`
  symbol: `helpdesk.category`, `helpdesk.priority`, `sh.helpdesk.ticket.type`, `sh.helpdesk.team`
- path: `sdd/state/FEAT-615/findings/live/12_distribution_acl.json`
  symbol: extra_field_names_ticket_68
- path: `sdd/state/FEAT-615/findings/live/11_troc_modules.json`
  symbol: troc_xmlids (`field_res_users__sh_helpdesk_team_ids`, `field_helpdesk_category__team_id`, cron `cron_webhook_error_dedupe_cleanup`)

## Notes

Extra fields are a `field_name → value` bag; a typed `dict[str, str]` projection is the natural structured output.
