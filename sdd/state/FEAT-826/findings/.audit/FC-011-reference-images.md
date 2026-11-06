---
id: FC-011
query_id: Q020
type: read
intent: "Reference images — maps to 'top graphic is correct image'."
executed_at: 2026-11-06T16:08:40Z
duration_ms: 500
parent_id: null
depth: 0
---

# FC-011 — Reference images feed product identification only; zones never use them

## Summary

`identification/references.py` loads a reference bank and selects a capped subset per vision call (`select_references`, optionally `by_brand` from OCR readings). The module has no zone handling at all. `LayoutProfile.references` defaults to an enabled `ReferencePolicy`, and the pipeline loads the bank only when the layout enables references **and** the row has `reference_images`. Both rewritten EcoTank rows carry no reference images (exported `reference_images` is `{}`, FC-021) and their image folders have no `references/` (FC-004), so "top graphic is the correct image" is not backed by any reference artwork today.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/references.py`
  lines: 80-87
  symbol: `select_references`
  excerpt: |
    def select_references(
        bank: Sequence[ReferenceImage], readings: Mapping[str, OcrReading], policy: ReferencePolicy
    ) -> Tuple[List[ReferenceImage], List[str]]:
        """Select a stable capped subset using only current-call OCR readings."""
        if not policy.enabled:
            return [], ["references: disabled"]
        if not bank:
            return [], ["references: none configured"]
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/references.py`
  lines: 48-48
  symbol: `load_reference_bank`
  excerpt: |
    async def load_reference_bank(reference_images: Mapping[str, Any], ctx: CycleContext) -> List[ReferenceImage]:
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py`
  lines: 22-27
  symbol: `ReferencePolicy`
  excerpt: |
    class ReferencePolicy(BaseModel):
        """Bound and select references without using expected shelf identity."""
        enabled: bool = True
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py`
  lines: 260-261
  symbol: `PlanogramCompliance.run`
  excerpt: |
    if self._layout.references.enabled and self.reference_images:
        ctx.reference_bank = await load_reference_bank(self.reference_images, ctx)

## Notes

- The ticket attaches two rendering PDFs ("70843 OD Q1 ET-4950 Rendering_Backlit_4ft_P3.pdf", "..._4ft_3ft_P3.pdf") as the reference for the display structure. Nothing in the pipeline consumes a rendering for a zone; they can only inform the hand-written texts / visual keywords.
- [cross-lane: type=wiki_query, intent=whether any spec plans a reference-image or image-similarity rule for zones (graphic correctness)]
