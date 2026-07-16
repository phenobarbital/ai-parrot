---
type: Wiki Overview
title: 'TASK-1016: Aggregate Records (read_group / formatted_read_group)'
id: doc:sdd-tasks-completed-task-1016-aggregate-records-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Agents currently must fetch raw records and aggregate client-side, wasting
  bandwidth
relates_to:
- concept: mod:parrot.interfaces.odoointerface
  rel: mentions
---

# TASK-1016: Aggregate Records (read_group / formatted_read_group)

**Feature**: FEAT-147 — Evaluate Odoo MCP Toolkit
**Spec**: `sdd/specs/evaluate-odoo-mcp-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1013, TASK-1015
**Assigned-to**: unassigned

---

## Context

Agents currently must fetch raw records and aggregate client-side, wasting bandwidth
and LLM context. This task adds `aggregate_records` which uses Odoo's server-side
`read_group` (v16-18) or `formatted_read_group` (v19+).

Implements spec §3 Module 3: Aggregate Records.

---

## Scope

- Add `aggregate_records` async method to `OdooToolkit`
- Implement Odoo version detection: parse `server_serie` from `server_info()` to
  determine major version
- Add `ALLOWED_AGGREGATORS` constant: `{"sum", "avg", "min", "max", "count", "count_distinct", "array_agg", "bool_and", "bool_or"}`
- Parse `"field:agg"` measure specs via a `_parse_measure_spec` helper
- Decorate with `@tool_schema(AggregateRecordsInput)`
- Return `AggregateResult` envelope

**NOT in scope**: Smart fields, domain builder, other toolkit methods.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | MODIFY | Add `aggregate_records`, `_parse_measure_spec`, `_get_odoo_major_version`, `ALLOWED_AGGREGATORS` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported in toolkit.py:
from .models.envelopes import SearchResult, ServerInfoResult  # envelopes.py

# New imports to add:
from .models.inputs import AggregateRecordsInput         # TASK-1013
from .models.envelopes import AggregateResult            # TASK-1013
```

### Existing Signatures to Use
```python
# toolkit.py:228
async def _execute(self, model, method, args=None, kwargs=None) -> Any:

# toolkit.py:282
async def server_info(self) -> ServerInfoResult:
# ServerInfoResult.server_serie: str  (e.g., "17.0", "19.0")
```

### Does NOT Exist
- ~~`OdooToolkit.aggregate_records()`~~ — must be created
- ~~`OdooToolkit._get_odoo_major_version()`~~ — must be created
- ~~`OdooToolkit._odoo_version`~~ — no cached version attribute exists
- ~~`parrot.interfaces.odoointerface.formatted_read_group`~~ — no such wrapper; use `_execute` directly

---

## Implementation Notes

### Version Detection
```python
async def _get_odoo_major_version(self) -> int | None:
    """Return the Odoo major version (e.g. 17, 19) or None if unknown."""
    try:
        info = await self.server_info()
        serie = info.server_serie  # e.g. "17.0"
        return int(serie.split(".")[0]) if serie else None
    except (OdooError, ValueError):
        return None
```

### Measure Spec Parsing
```python
def _parse_measure_spec(spec: str) -> tuple[str, str]:
    """Split 'field:agg' into (field, aggregator). Default agg is 'sum'."""
    if ":" in spec:
        field, agg = spec.rsplit(":", 1)
        return field, agg
    return spec, "sum"
```

### Aggregation Call
- Odoo 19+: `self._execute(model, "formatted_read_group", ...)`
- Odoo 16-18: `self._execute(model, "read_group", [domain], {groupby, fields, lazy, limit, offset, orderby})`
- The `fields` kwarg for `read_group` expects `["field:agg"]` format

### Key Constraints
- Validate aggregator names against `ALLOWED_AGGREGATORS` before calling Odoo
- Raise `ValueError` for unknown aggregators
- `lazy=False` means fully expanded groups (all groupby levels at once)

---

## Acceptance Criteria

- [ ] `aggregate_records(model="sale.order", group_by=["state"])` calls `read_group`
- [ ] On Odoo 19+, uses `formatted_read_group` instead
- [ ] `measures=["amount_total:sum"]` passes correctly to Odoo
- [ ] `measures=["amount_total:invalid"]` raises `ValueError`
- [ ] Returns `AggregateResult` with groups, count, measures list

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_aggregate_records_read_group(odoo_toolkit):
    """Uses read_group for Odoo < 19."""
    tk = odoo_toolkit
    # Mock server_info to return version 17
    # Mock _execute to return groupby results
    result = await tk.aggregate_records(
        model="sale.order", group_by=["state"], measures=["amount_total:sum"]
    )
    assert isinstance(result, AggregateResult)
    assert result.group_by == ["state"]

@pytest.mark.asyncio
async def test_aggregate_invalid_aggregator(odoo_toolkit):
    with pytest.raises(ValueError, match="aggregator"):
        await tk.aggregate_records(
            model="sale.order", group_by=["state"], measures=["amount:evil"]
        )
```

---

## Completion Note

*(Agent fills this in when done)*
