---
id: F013
query_id: Q011
type: read
intent: How non-ink-wall definitions name products; shelf-level label policy
executed_at: 2026-10-09T20:49:59Z
duration_ms: 0
parent_id: null
depth: 0
---

# F013 — Legacy configs produce facing.product = product name; found_products labels stay display_name unless product_label=product

## Summary

`migration.py` converts legacy `planograms_configurations` rows into facings with `"product": name` (the legacy product name), `brand` and seeded descriptors, so endcap / shelf definitions name a product per occupied facing (the printer model for printer endcaps). `project_compliance` (projection.py:95-125) switches the per-shelf `expected_products` / `found_products` labels to the facing product only when `policy.product_label == "product"`; with the default `display_name` those lists keep display names. `products_found` is independent of that switch (it always uses `model=first.product`).

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py`
  lines: 262-292
  symbol: (legacy shelf → facings conversion)
  excerpt: |
    facings.append({"facing_id": facing_id, "shelf_id": shelf_id, "slot": slot,
                    "product": name, "brand": product.get("brand") or brand,
                    "descriptors": copy.deepcopy(descriptors)})

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py`
  lines: 95-125
  symbol: `project_compliance`
  excerpt: |
    product_labels = policy is not None and policy.product_label == "product"
    if product_labels:
