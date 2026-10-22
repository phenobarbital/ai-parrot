---
id: F008
query_id: Q007
type: grep
intent: Reference-image detection path and the identity it yields
executed_at: 2026-10-09T20:49:59Z
duration_ms: 0
parent_id: null
depth: 0
---

# F008 — Reference match resolves to a definition product via the catalogue key

## Summary

Reference images are loaded per run into `ctx.reference_bank` with opaque labels `ref-NNNN` and their `catalog_key` (the `reference_images` dict key, F002). The identify call offers the labels and the model returns `reference_id`; `_reference_product` (compare.py:34-57) maps the label back to its `catalog_key` and runs `resolve_identity(Identification(product=key, ...), definition)` so the identity becomes a **definition product name** — exactly what `SlotPresence.model` / `observed` carry. Commit 42a93f350 skips reference loading for types whose `ReferencePolicy.enabled` is false (InkWall).

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/references.py`
  lines: 20-80
  symbol: `reference_label`, `flatten_references`, `load_reference_bank`
  excerpt: |
    LABEL_FORMAT: str = "ref-{:04d}"
    bank.append(ReferenceImage(label=reference_label(index), image=png, catalog_key=catalog_key,
                               brand=policy.brand_by_reference.get(catalog_key)))

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/compare.py`
  lines: 34-57
  symbol: `_reference_product`
  excerpt: |
    key = next((ref.catalog_key for ref in ctx.reference_bank if ref.label == identification.reference_id), None)
    product, _ = resolve_identity(Identification(shape_id=identification.shape_id, product=key, brand=identification.brand),
                                  definition, required_fields=())
    if product is None or (candidates and product not in candidates): return None, None
    return product, key

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py`
  lines: 442-511
  symbol: (identify call with selected references; `_clean_reference_id` at 56)
  excerpt: |
    if policy is not None and policy.enabled and ctx.reference_bank:
        references, diagnostics = select_references(ctx.reference_bank, call_readings, policy)
    labels = [reference.label for reference in references]
