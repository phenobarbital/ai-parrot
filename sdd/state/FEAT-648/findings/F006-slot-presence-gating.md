---
id: F006
query_id: Q006
type: grep
intent: Which types enable slot_presence; LayoutProfile.reporting
executed_at: 2026-10-09T20:49:59Z
duration_ms: 0
parent_id: null
depth: 0
---

# F006 — Only InkWall enables slot_presence; every other type inherits the False default

## Summary

`slot_presence` appears in exactly four source locations: the policy field (definition.py:55), the gate (compare.py:226), the presence module import, and `types/ink_wall.py:80`, where InkWall's `default_layout_profile` sets `ReportingPolicy(product_label="product", slot_presence=True)`. `LayoutProfile.reporting` (layout.py:99) defaults to `ReportingPolicy()`. None of `product_on_shelves.py`, `endcap_backlit_multitier.py`, `endcap_no_shelves_promotional.py`, `graphic_panel_display.py`, `product_counter.py` mention `ReportingPolicy` or `slot_presence`.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py`
  lines: 65-84
  symbol: `InkWall.default_layout_profile`
  excerpt: |
    # Ink cartridges are identified from the price-tag text; no reference images are used.
    references=ReferencePolicy(enabled=False),
    reporting=ReportingPolicy(product_label="product", slot_presence=True),

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py`
  lines: 98-100
  symbol: `LayoutProfile.reporting`
  excerpt: |
    references: ReferencePolicy = Field(default_factory=ReferencePolicy)
    reporting: ReportingPolicy = Field(default_factory=ReportingPolicy)
    completeness: CompletenessPolicy = Field(default_factory=CompletenessPolicy)

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py`
  lines: 105-118
  symbol: `ProductOnShelves.default_layout_profile`
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py`
  lines: 160-174
  symbol: `EndcapBacklitMultitier.default_layout_profile`
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py`
  lines: 74-85
  symbol: `EndcapNoShelvesPromotional.default_layout_profile`
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py`
  lines: 94-101
  symbol: `GraphicPanelDisplay.compare`
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py`
  lines: 115-122
  symbol: `ProductCounter.compare`
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/__init__.py`
  lines: 1-19
  symbol: `__all__` (ProductOnShelves, GraphicPanelDisplay, ProductCounter, EndcapNoShelvesPromotional, EndcapBacklitMultitier, InkWall)
