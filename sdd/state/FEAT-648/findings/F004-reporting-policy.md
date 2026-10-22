---
id: F004
query_id: Q009
type: read
intent: Read ReportingPolicy, the meta override and effective_reporting
executed_at: 2026-10-09T20:49:59Z
duration_ms: 0
parent_id: null
depth: 0
---

# F004 — ReportingPolicy defaults: slot_presence=False, product_label=display_name; per-row meta override

## Summary

`ReportingPolicy` (extra="forbid") has three fields: `product_label` (default `"display_name"`), `slot_presence` (default `False`), `misplaced_min_confidence` (0.9). `effective_reporting` starts from `ReportingPolicy()`, replaces it with the layout profile's `reporting` when present, then applies a partial override from `SlotsDefinition.meta["reporting"]` (validated at construction). So a per-row `slots_definition.meta.reporting` can already turn presence on or off for any type. `FacingDefinition` guarantees every occupied facing has a non-blank `product`, which is what `SlotPresence.model` reports.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py`
  lines: 49-57
  symbol: `ReportingPolicy`
  excerpt: |
    class ReportingPolicy(BaseModel):
        model_config = ConfigDict(extra="forbid")
        product_label: Literal["display_name", "product"] = "display_name"
        slot_presence: bool = False
        misplaced_min_confidence: float = Field(default=0.9, ge=0.0, le=1.0)

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py`
  lines: 172-190
  symbol: `SlotsDefinition._check_reporting_meta`
  excerpt: |
    if REPORTING_META_KEY in self.meta:
        ReportingPolicy.model_validate(self.meta[REPORTING_META_KEY])

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py`
  lines: 196-225
  symbol: `effective_reporting`
  excerpt: |
    policy = ReportingPolicy()
    layout_policy = getattr(layout, "reporting", None) if layout is not None else None
    if layout_policy is not None:
        policy = ReportingPolicy.model_validate(layout_policy)
    if definition is not None and REPORTING_META_KEY in definition.meta:
        resolved = policy.model_dump(); resolved.update(definition.meta[REPORTING_META_KEY])
        policy = ReportingPolicy.model_validate(resolved)

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py`
  lines: 119-138
  symbol: `FacingDefinition._occupied_needs_product`
  excerpt: |
    product: Optional[str] = None
    brand: Optional[str] = None
    descriptors: Descriptors = Field(default_factory=Descriptors)
    expected_occupancy: Literal["occupied", "empty"] = "occupied"
    ...
    if self.expected_occupancy == "occupied" and not (self.product and self.product.strip()):
        raise ValueError(f"{self.facing_id}: occupied facing requires a nonblank product")
