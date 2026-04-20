# TASK-753: Migrate `create_widget` to CRUD primitives

**Feature**: FEAT-107 — NavigatorToolkit Method Migration to PostgresToolkit CRUD
**Spec**: `sdd/specs/navigator-toolkit-method-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-748
**Assigned-to**: unassigned

---

## Context

Implements **Module 6** of the spec. `create_widget` combines a
19-column INSERT (six `::text::jsonb` + one `::varchar` cast) with a
follow-up UPDATE on the parent dashboard's `attributes` to merge in the
new widget's `widget_location`. Today the two writes are unscoped; a
mis-merge leaves an orphan widget. Migration wraps both in a single
transaction.

---

## Scope

Rewrite `create_widget` (toolkit.py:1332):

- Wrap body in `async with self.transaction() as tx:`.
- Widget INSERT (line 1389) → `self.insert_row("navigator.widgets",
  data={…}, returning=["widget_id","widget_type"], conn=tx)`. Drop all
  `::text::jsonb` / `::varchar` cast strings — pass plain Python values.
- Parent-dashboard UPDATE (line 1429) →
  `self.update_row("navigator.dashboards",
  data={"attributes": merged_attributes},
  where={"dashboard_id": did}, conn=tx)`.
- `confirm_execution=False` branch unchanged (lines 1381-1386).

**NOT in scope**: `update_widget`, `get_widget`, widget-template logic,
`navigator.widgets_templates` writes (this tool does not touch them).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py` | MODIFY | Rewrite `create_widget` body |
| `packages/ai-parrot-tools/tests/unit/test_navigator_create_widget.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.database.toolkits.postgres import PostgresToolkit
# verified: packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py:28
```

### Existing Signatures to Use
```python
async def insert_row(self, table, data, returning=None, conn=None): ...   # postgres.py:361
async def update_row(self, table, data, where,
    returning=None, conn=None): ...                                        # postgres.py:490
async def transaction(self): ...                                           # postgres.py:697
async def create_widget(...) -> Dict[str, Any]: ...                        # toolkit.py:1332
async def _check_write_access(self, program_id: int) -> None: ...          # toolkit.py:593
async def _check_dashboard_access(self, dashboard_id: str) -> None: ...    # toolkit.py:540
```

### Does NOT Exist
- ~~`update_row` without `where`~~ — required kwarg. `QueryValidator`
  enforces PK-in-WHERE.
- ~~Hand-concatenated `::text::jsonb` cast~~ — removed at end of task.

---

## Implementation Notes

### Pattern
```python
if not confirm_execution:
    return {"status": "confirm_execution", "plan": {...}}

async with self.transaction() as tx:
    widget = await self.insert_row(
        "navigator.widgets",
        data={...19 fields, plain values...},
        returning=["widget_id", "widget_type"],
        conn=tx,
    )
    merged = {**parent_attributes, "widget_location":
              {**parent_attributes.get("widget_location", {}),
               widget["widget_id"]: widget_location_for_new_widget}}
    await self.update_row(
        "navigator.dashboards",
        data={"attributes": merged},
        where={"dashboard_id": did},
        conn=tx,
    )
```

### Key Constraints
- JSON columns (`options`, `query_information`, etc.) are plain dicts.
- The `::varchar` cast for `widget_type` is dropped — the dynamic
  Pydantic model derives the type from `TableMetadata`.
- Both writes share `conn=tx`. A failure in `update_row` rolls back the
  widget insert.

---

## Acceptance Criteria

- [ ] `create_widget(confirm_execution=False)` returns plan dict identical to baseline.
- [ ] `insert_row("navigator.widgets", …)` called once with 19-field data dict, `returning=["widget_id","widget_type"]`.
- [ ] `update_row("navigator.dashboards", …)` called once with merged `attributes` + `where={"dashboard_id": …}`.
- [ ] Both CRUD calls receive `conn=tx`.
- [ ] `transaction()` entered exactly once.
- [ ] No `::text::jsonb` or `::varchar` fragments remain in the method body.
- [ ] `get_tools()` snapshot still green.
- [ ] `pytest packages/ai-parrot-tools/tests/unit/test_navigator_create_widget.py -v` passes.

---

## Test Specification

Required (spec §4):
- `test_create_widget_updates_parent_dashboard_attributes` — verifies
  `update_row("navigator.dashboards", …)` is called with merged
  `widget_location` inside the same transaction as the widget insert.

---

## Agent Instructions

Standard. Preserve the exact `widget_location` merge semantics from the
old method — it is a deep-merge that downstream clients depend on.
