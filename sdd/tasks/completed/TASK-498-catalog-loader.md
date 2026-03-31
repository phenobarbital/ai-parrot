# TASK-498: Gorilla Sheds Catalog Loader (Verification & Utility Script)

**Feature**: advisor-ontologic-rag-agent (FEAT-071)
**Spec**: `sdd/specs/advisor-ontologic-rag-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-497
**Assigned-to**: unassigned

---

## Context

> The `gorillashed.products` PgVector table is **already populated** with vectorised
> products. This task creates a lightweight utility script that:
> 1. Verifies the catalog is accessible and products exist
> 2. Optionally enriches existing products with scraped PageIndex data
> 3. Provides a `get_catalog()` helper used by the advisor agent (TASK-499)
>
> This is NOT a bulk loader — the data is already there. This is a verification
> and convenience module.
>
> Implements **Module 2** from the spec (adapted per user feedback).

---

## Scope

- Implement `examples/shoply/load_catalog.py` with:
  - `get_catalog()` → returns configured `ProductCatalog` instance pointing to
    `gorillashed.products` (schema=`gorillashed`, table=`products`)
  - `verify_catalog()` → connects, counts products, prints summary
  - CLI mode: `python examples/shoply/load_catalog.py` runs verification
- Implement `examples/shoply/config.py` with shared constants:
  - `CATALOG_ID = "gorillashed"`
  - `SCHEMA = "gorillashed"`
  - `TABLE = "products"`
  - `DATA_DIR = Path(__file__).parent / "data"`

**NOT in scope**:
- Bulk product insertion (already done)
- Scraping (TASK-497)
- Building the advisor agent (TASK-499)

---

## Files to Create / Modify

| File | Action | Description |
|------|--------|-------------|
| `examples/shoply/config.py` | CREATE | Shared constants |
| `examples/shoply/load_catalog.py` | CREATE | Catalog verification and helper |

---

## Implementation Notes

### Pattern to Follow

```python
# examples/shoply/load_catalog.py
import asyncio
import logging

from parrot.advisors import ProductCatalog
from examples.shoply.config import CATALOG_ID, SCHEMA, TABLE

logger = logging.getLogger(__name__)


async def get_catalog() -> ProductCatalog:
    """Get configured ProductCatalog for Gorilla Sheds.

    The gorillashed.products table must already exist and be populated.
    """
    catalog = ProductCatalog(
        catalog_id=CATALOG_ID,
        table=TABLE,
        schema=SCHEMA,
    )
    await catalog.initialize(create_table=False)
    return catalog


async def verify_catalog() -> None:
    """Verify catalog connectivity and print product summary."""
    catalog = await get_catalog()
    products = await catalog.get_all_products()
    print(f"Catalog: {CATALOG_ID}")
    print(f"Products found: {len(products)}")
    for p in products[:5]:
        print(f"  - {p.name} ({p.product_id})")
    if len(products) > 5:
        print(f"  ... and {len(products) - 5} more")


if __name__ == "__main__":
    asyncio.run(verify_catalog())
```

### Key Constraints

- `create_table=False` — table already exists
- All async
- Must work standalone: `python examples/shoply/load_catalog.py`

### References in Codebase

- `parrot/advisors/catalog/catalog.py` — `ProductCatalog` class
- `examples/advisors/product_advisor_basebot.py` — existing catalog usage

---

## Acceptance Criteria

- [ ] `python examples/shoply/load_catalog.py` connects and prints product count
- [ ] `get_catalog()` returns working `ProductCatalog` instance
- [ ] `config.py` defines shared constants used by other modules
- [ ] No attempt to create tables or insert data

---

## Test Specification

```python
# tests/examples/test_catalog_loader.py
import pytest
from examples.shoply.config import CATALOG_ID, SCHEMA, TABLE


class TestConfig:
    def test_catalog_id(self):
        assert CATALOG_ID == "gorillashed"

    def test_schema(self):
        assert SCHEMA == "gorillashed"

    def test_table(self):
        assert TABLE == "products"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-498-catalog-loader.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
