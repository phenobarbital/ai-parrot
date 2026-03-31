#!/usr/bin/env python3
"""
Gorilla Sheds Catalog Loader — Verification & Utility Script.

The ``gorillashed.products`` PgVector table is already populated with
vectorised products. This script:

1. Verifies the catalog is accessible and products exist.
2. Provides ``get_catalog()`` — a helper used by the advisor agent.

Usage:
    python examples/shoply/load_catalog.py
"""
from __future__ import annotations

import asyncio
import logging

from parrot.advisors import ProductCatalog

from examples.shoply.config import CATALOG_ID, SCHEMA, TABLE

logger = logging.getLogger(__name__)


async def get_catalog() -> ProductCatalog:
    """Get a configured ProductCatalog for Gorilla Sheds.

    The ``gorillashed.products`` table must already exist and be populated.
    No table creation or data insertion is performed.

    Returns:
        Initialised ProductCatalog instance.
    """
    catalog = ProductCatalog(
        catalog_id=CATALOG_ID,
        table=TABLE,
        schema=SCHEMA,
    )
    await catalog.initialize(create_table=False)
    return catalog


async def verify_catalog() -> None:
    """Verify catalog connectivity and print a product summary."""
    catalog = await get_catalog()
    products = await catalog.get_all_products()
    print(f"Catalog: {CATALOG_ID}")
    print(f"Schema:  {SCHEMA}.{TABLE}")
    print(f"Products found: {len(products)}")
    for p in products[:5]:
        print(f"  - {p.name} ({p.product_id})")
    if len(products) > 5:
        print(f"  ... and {len(products) - 5} more")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    asyncio.run(verify_catalog())
