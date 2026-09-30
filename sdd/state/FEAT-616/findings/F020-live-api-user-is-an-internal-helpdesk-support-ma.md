---
id: F020
query_id: L008
type: rpc
intent: live: ACL of the API user
executed_at: 2026-09-30T23:58:00Z
duration_ms: 0
parent_id: None
depth: 0
---

# F020 — Live: API user is an internal Helpdesk Support Manager with full ticket CRUD

## Summary

`check_access_rights` on `sh.helpdesk.ticket`: read/write/create/unlink all True. `res.users` uid 2241: `share=False` (internal), groups include `Helpdesk / Support Manager`, `Helpdesk SLA Policy`, `Helpdesk Ticket Alarm`.

## Citations

- path: `sdd/state/FEAT-616/findings/live/12_distribution_acl.json`
  symbol: api_user_groups
- path: `sdd/state/FEAT-616/findings/live/00_version.json`

## Notes

—
