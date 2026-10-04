---
id: F008
query_id: Q008
type: grep
intent: where ODOO_HELPDESK_* / helpdesk / odoo_hd are referenced
executed_at: 2026-09-30T23:58:00Z
duration_ms: 0
parent_id: None
depth: 0
---

# F008 — ODOO_HELPDESK_* keys, helpdesk precedents and the missing odoo_hd agent

## Summary

`ODOO_HELPDESK_APIKEY/PASSWORD/URL/USER` exist only in `env/.env` (no `ODOO_HELPDESK_DATABASE`); nothing in `packages/` reads them. `odoo_hd` / `sh.helpdesk` appear only in SDD/ledger files — the helpdesk agent is not in this repo. The only helpdesk-shaped toolkit is `ZammadToolkit` (`parrot_tools/zammad.py:141`, `tool_prefix="zammad"`) with `create_ticket`, `get_ticket`, `list_tickets`, `update_ticket`, `close_ticket`, `search_tickets`, `delete_ticket`, `get_articles`, `get_attachment`, user tools — a naming precedent. `examples/orchestrator/` is an IT-helpdesk demo unrelated to Odoo.

## Citations

- path: `env/.env`
  symbol: `ODOO_HELPDESK_URL`, `ODOO_HELPDESK_USER`, `ODOO_HELPDESK_PASSWORD`, `ODOO_HELPDESK_APIKEY` (names only)
- path: `packages/ai-parrot-tools/src/parrot_tools/zammad.py`
  lines: 33-141
  symbol: `CreateTicketInput`, `UpdateTicketInput`, `CloseTicketInput`, `ZammadToolkit`
- path: `packages/ai-parrot-tools/src/parrot_tools/zammad.py`
  lines: 241-330
  symbol: `ZammadToolkit.create_ticket`, `get_ticket`, `list_tickets`, `update_ticket`, `close_ticket`, `search_tickets`
- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 819
  symbol: Zammad conf block (no ODOO_HELPDESK block)
- path: `sdd/ledger/issues.jsonl`
  symbol: `discovered_from: agent:odoo_hd`

## Notes

—
