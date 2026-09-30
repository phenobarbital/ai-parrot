---
id: F005
query_id: Q005
type: read
intent: transport detection + JSON-2 auth/body mapping limits
executed_at: 2026-09-30T23:58:00Z
duration_ms: 0
parent_id: None
depth: 0
---

# F005 — Transport detection and JSON-2 mapping limits

## Summary

`auto_detect_transport` (`detect.py:107`) probes `/web/version`; serie ≥ 19 → `Json2Transport`. JSON-2 (`json2.py:38`) sends `Authorization: bearer <password>` and `X-Odoo-Database: <database>` (:60-65), authenticates via `res.users.context_get` (:164-169), and `execute_kw` (:171-179) translates positional `execute_kw` args with `_build_body` (:90-162): explicit branches for `search/search_read/search_count`, `read/write/unlink/create/fields_get/check_access_rights/load`, then an `_looks_like_ids` tail; anything else raises `OdooRPCError("JSON-2 transport cannot map positional args for method …")` (:160-162). `[[id]]`-style action calls (e.g. `action_confirm`) map to `ids` and work.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/detect.py`
  lines: 30-38
  symbol: `_serie_is_json2`
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/detect.py`
  lines: 107-120
  symbol: `auto_detect_transport`
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py`
  lines: 60-65
  symbol: `Json2Transport._headers`
  excerpt: |
    return {
        "Authorization": f"bearer {self.config.password}",
        "X-Odoo-Database": self.config.database,
        "Content-Type": "application/json",
    }
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py`
  lines: 90-162
  symbol: `Json2Transport._build_body`
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py`
  lines: 164-169
  symbol: `Json2Transport.authenticate`
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py`
  lines: 171-179
  symbol: `Json2Transport.execute_kw`
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/base.py`
  lines: 11-55
  symbol: `AbstractOdooTransport`

## Notes

Live confirmation in F012/F021: an empty `X-Odoo-Database` header is accepted by the staging server; `get_views` (views-first positional) is unmappable; `formatted_read_group` fails until FEAT-614 lands.
