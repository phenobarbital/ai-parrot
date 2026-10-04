---
id: F003
query_id: Q003
type: read
intent: existing tool patterns
executed_at: 2026-09-30T23:58:00Z
duration_ms: 0
parent_id: None
depth: 0
---

# F003 — Existing tool patterns: discovery, CRUD, action-then-read-back

## Summary

Three reusable patterns: (1) discovery tools return typed envelopes — `server_info` → `ServerInfoResult` (:348), `list_models` iterates `_DEFAULT_KNOWN_MODELS` with `check_access_rights` (:373), `fields_get` (:392), `get_odoo_profile` (:1151), `schema_catalog` (:1206), `inspect_model_relationships` (:1265). (2) generic CRUD `search_records` (:406-455) uses `select_smart_fields` when `fields` is omitted and returns `SearchResult` with `FieldSelectionMetadata`. (3) business actions follow *call server method with `[[id]]` then `_read_one` → entity*: `confirm_sale_order` (:792-800) calls `self._execute("sale.order", "action_confirm", [[sale_order_id]])` then `SaleOrder.model_validate(record)`, gated by `@requires_permission("odoo.write")` + `@tool_schema(ConfirmSaleOrderInput)`. Per-model default field lists are class constants (e.g. `_ACCOUNT_MOVE_DEFAULT_FIELDS` :804).

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py`
  lines: 348-371
  symbol: `OdooToolkit.server_info`
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py`
  lines: 373-390
  symbol: `OdooToolkit.list_models`
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py`
  lines: 406-455
  symbol: `OdooToolkit.search_records`
  excerpt: |
    if fields is None:
        fields_meta = await self._get_fields_metadata(model)
        fields = select_smart_fields(fields_meta)
    records = await self._execute(model, "search_read", [domain or []], kwargs)
    total = await self._execute(model, "search_count", [domain or []])
    return SearchResult(records=records or [], total=int(total or 0), ...)
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py`
  lines: 792-800
  symbol: `OdooToolkit.confirm_sale_order`
  excerpt: |
    @requires_permission("odoo.write")
    @tool_schema(ConfirmSaleOrderInput)
    async def confirm_sale_order(self, sale_order_id: int) -> SaleOrder:
        await self._execute("sale.order", "action_confirm", [[sale_order_id]])
        record = await self._read_one("sale.order", sale_order_id, self._SALE_ORDER_DEFAULT_FIELDS)
        return SaleOrder.model_validate(record)
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py`
  lines: 804-810
  symbol: `OdooToolkit._ACCOUNT_MOVE_DEFAULT_FIELDS`
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py`
  lines: 1151-1204
  symbol: `OdooToolkit.get_odoo_profile`
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py`
  lines: 1206-1262
  symbol: `OdooToolkit.schema_catalog`
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py`
  lines: 1265-1330
  symbol: `OdooToolkit.inspect_model_relationships`

## Notes

The action-then-read-back pattern maps 1:1 onto Softhealer's `action_done/action_closed/action_cancel/action_open` buttons (F017).
