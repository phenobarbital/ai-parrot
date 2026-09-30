---
id: F002
query_id: Q002
type: read
intent: OdooToolkit class shape: config, init, transport, _execute chokepoint
executed_at: 2026-09-30T23:58:00Z
duration_ms: 0
parent_id: None
depth: 0
---

# F002 — OdooToolkit class shape and RPC chokepoint

## Summary

`OdooToolkit(AbstractToolkit)` (`toolkit.py:172`) sets `tool_prefix = "odoo"` (:191) and `confirming_tools` for shell tools (:194). `__init__` (:202-243) takes `url/database/username/password/timeout/verify_ssl/protocol/transport` and falls back to `parrot.conf` `ODOO_URL/ODOO_DATABASE/ODOO_USERNAME/ODOO_PASSWORD/ODOO_TIMEOUT/ODOO_VERIFY_SSL` (:31-38, :230-235). `_ensure_transport` (:245) auto-detects or builds the transport and authenticates once under `_auth_lock`; `_pre_execute` (:268) only authenticates when url+database+username are truthy. Every RPC goes through `_execute(model, method, args, kwargs)` (:283-292) → `transport.execute_kw`. Helpers: `_record_url` (:294), `_read_one` (:299), `_get_fields_metadata` (:312, cached), `_get_odoo_major_version` (:982). `_DEFAULT_KNOWN_MODELS` (:149-160) is a static tuple of 10 core models (no helpdesk model).

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py`
  lines: 149-160
  symbol: `_DEFAULT_KNOWN_MODELS`
  excerpt: |
    _DEFAULT_KNOWN_MODELS: tuple[tuple[str, str], ...] = (
        ("res.partner", "Contact / Partner"),
        ...
        ("stock.picking", "Stock Transfer"),
    )
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py`
  lines: 172-243
  symbol: `OdooToolkit.__init__`
  excerpt: |
    class OdooToolkit(AbstractToolkit):
        tool_prefix = "odoo"
        def __init__(self, url=None, database=None, username=None, password=None,
                     timeout=None, verify_ssl=None, protocol: Protocol = "auto",
                     transport: AbstractOdooTransport | None = None, **kwargs) -> None:
            self.config = OdooConfig(url=url or ODOO_URL or "", database=database or ODOO_DATABASE or "", ...)
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py`
  lines: 245-266
  symbol: `OdooToolkit._ensure_transport`
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py`
  lines: 268-271
  symbol: `OdooToolkit._pre_execute`
  excerpt: |
    if self.config.url and self.config.database and self.config.username:
        await self._ensure_transport()
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py`
  lines: 283-292
  symbol: `OdooToolkit._execute`
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py`
  lines: 299-322
  symbol: `OdooToolkit._read_one`, `OdooToolkit._get_fields_metadata`
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py`
  lines: 982-991
  symbol: `OdooToolkit._get_odoo_major_version`
- path: `packages/ai-parrot/src/parrot/conf.py`
  symbol: `ODOO_URL`, `ODOO_DATABASE`, `ODOO_USERNAME`, `ODOO_PASSWORD`

## Notes

`_pre_execute` skips eager auth when `database` is empty, but `_execute` still authenticates lazily via `_ensure_transport` — that is why an empty database works on JSON-2 (F012). No `ODOO_HELPDESK_*` keys exist in `parrot.conf` (F008).
