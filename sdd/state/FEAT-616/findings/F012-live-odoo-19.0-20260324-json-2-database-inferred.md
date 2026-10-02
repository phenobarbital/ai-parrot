---
id: F012
query_id: L001
type: rpc
intent: live: server version, transport, database resolution
executed_at: 2026-09-30T23:58:00Z
duration_ms: 0
parent_id: None
depth: 0
---

# F012 — Live: Odoo 19.0-20260324, JSON-2, database inferred by server

## Summary

`GET /web/version` → `19.0-20260324`, `version_info [19,0,0,'final',0,'']`. `/web/database/list` is disabled ("Odoo Server Error"). JSON-2 `res.users.context_get` with the API key as bearer and **no / empty `X-Odoo-Database` header** returns `{lang: en_US, tz: Europe/Madrid, uid: 2241}` → the server hosts a single filtered database, so `OdooToolkit(database="")` authenticates fine (`server_info`: connected, transport `json2`, uid 2241). `/web/session/authenticate` requires a `db` argument, so the password login path cannot be used without the db name.

## Citations

- path: `sdd/state/FEAT-616/findings/live/00_version.json`
  symbol: version_info, databases (empty)
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py`
  lines: 60-65
  symbol: `Json2Transport._headers` (empty database header accepted)

## Notes

The database name remains unknown; not needed for JSON-2. `ODOO_HELPDESK_*` provides both PASSWORD and APIKEY; the API key was used as bearer.
