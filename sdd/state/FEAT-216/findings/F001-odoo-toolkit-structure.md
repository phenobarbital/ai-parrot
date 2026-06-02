# F001 — OdooToolkit structure & tool patterns

**Confidence:** high

`OdooToolkit(AbstractToolkit)` lives at
`packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py:159` (~82 KB, ~30 tools).

Key facts:
- `tool_prefix = "odoo"` (toolkit.py:177) — every tool is exposed as `odoo_<method>`.
- `__init__` (toolkit.py:180-221): builds `OdooConfig` from args or `ODOO_*` env
  vars; defers all I/O. Stores `self.config`, `self.protocol`, `self._transport`,
  `self._auth_lock`, `self._fields_cache`, `self.logger`.
- Lazy auth: `_ensure_transport()` (toolkit.py:223) + `_pre_execute()` (toolkit.py:246)
  authenticate on first tool call; `auto_detect_transport` picks json2/jsonrpc/xmlrpc.
- Central RPC helper: `async _execute(model, method, args, kwargs)` (toolkit.py:261) —
  the single private chokepoint every tool uses to call Odoo (e.g.
  `confirm_sale_order` → `self._execute("sale.order", "action_confirm", [[id]])`,
  toolkit.py:774). This is exactly how button methods like `button_validate`
  (picking validation) and stage advances would be invoked.
- Tool decoration pattern (per method):
  ```python
  @requires_permission("odoo.write")        # optional, permission gating
  @tool_schema(CreateRecordInput)            # binds Pydantic input schema
  async def create_record(self, ...) -> CreateResult: ...
  ```
- Private helpers (`_read_one`, `_get_fields_metadata`, `_resolve_binary_source`,
  `attach_document` at toolkit.py:906 for photos/binaries) are reusable.

**Citations:** `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` (159,177,180,223,246,261,469-471,772-774,906)
