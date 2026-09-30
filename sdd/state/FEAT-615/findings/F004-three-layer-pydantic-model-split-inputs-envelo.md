---
id: F004
query_id: Q004
type: read
intent: three-layer Pydantic model split and exports
executed_at: 2026-09-30T23:58:00Z
duration_ms: 0
parent_id: None
depth: 0
---

# F004 — Three-layer Pydantic model split (inputs / envelopes / entities)

## Summary

Models live in `parrot_tools/odoo/models/`: `inputs.py` (`_OdooBaseInput`, `extra="ignore"`, `OdooDomain = list[Any]`; 36 input classes, one per tool, each `Field(..., description=...)`), `envelopes.py` (`SearchResult`, `RecordResult`, `CreateResult`, `UpdateResult`, `BulkCreateResult`, `ServerInfoResult`, `AggregateResult`, ... 30 envelopes; `SearchResult.records` is `list[dict]`), `entities.py` (`_OdooEntity` with `extra="allow"`, `Many2one = Union[tuple[int,str], list[Any], bool, None]`, 13 entities incl. `ResPartner`, `SaleOrder`, `AccountMove`, `CrmLead`, `HrEmployee`). `models/__init__.py` re-exports; package `__init__.py` exports `OdooToolkit` and the 4 error classes only.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py`
  lines: 14-24
  symbol: `OdooDomain`, `_OdooBaseInput`
  excerpt: |
    OdooDomain = list[Any]
    class _OdooBaseInput(BaseModel):
        model_config = ConfigDict(extra="ignore", protected_namespaces=())
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py`
  lines: 39-50
  symbol: `SearchRecordsInput`
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py`
  lines: 183-188
  symbol: `ConfirmSaleOrderInput`
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/models/envelopes.py`
  lines: 52-84
  symbol: `SearchResult`, `RecordResult`, `CreateResult`
  excerpt: |
    class CreateResult(BaseModel):
        success: bool = True
        record: dict[str, Any] = Field(default_factory=dict)
        record_id: int
        model: str
        message: str = ""
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/models/envelopes.py`
  lines: 157-186
  symbol: `ServerInfoResult`, `AggregateResult`
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/models/entities.py`
  lines: 19-31
  symbol: `Many2one`, `_OdooEntity`
  excerpt: |
    Many2one = Union[tuple[int, str], list[Any], bool, None]
    class _OdooEntity(BaseModel):
        model_config = ConfigDict(extra="allow", populate_by_name=True)
        id: Optional[int] = None
        display_name: Optional[str] = None
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/models/entities.py`
  lines: 129-155
  symbol: `SaleOrder`
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/models/__init__.py`
  symbol: `__all__`
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/__init__.py`
  symbol: `__all__`

## Notes

No helpdesk entity/input/envelope exists. Helpdesk models would be added to these three modules (or new `models/helpdesk_*.py` siblings re-exported from `models/__init__.py`).
