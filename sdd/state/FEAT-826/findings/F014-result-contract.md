---
id: F014
query_id: Q024
type: grep
intent: "Result contract consumed downstream (FlowTask writes it to epson.compliance_photo_reports)."
executed_at: 2026-11-06T16:05:00Z
duration_ms: 700
parent_id: null
depth: 0
lanes: [codebase]
merged_from: [FC-016]
---
# F014 — The pipeline returns 8 legacy keys + additive keys and no markdown; the report text is built outside this repo

## Summary

`PlanogramCompliance._assemble` returns the eight legacy keys the March logs show (`step3_compliance_results`, `compliance_results`, `overall_compliance_score`, `overall_compliant`, `identified_products`, `shelf_regions`, `rendered_image`, `overlay_path`) plus additive keys such as `assessment_status`, `strict_compliance_score`, `coverage`, `detection_source`, `products_found`, `errors`. `overall_compliant` is forced to `False` when there are no compliance results. A search of `packages/ai-parrot-pipelines/src` and `packages/ai-parrot/src/parrot/models` for `compliance_analysis`, `SHELF-BY-SHELF`, `Overall Compliance`, `Text Score`, `Product Score` finds nothing relevant: the markdown stored in `compliance_analysis*` is produced by the FlowTask component (F018).

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py`
  lines: 493-532
  symbol: `PlanogramCompliance._assemble`
  excerpt: |
    return {
        "step3_compliance_results": results,
        "compliance_results": results,
        "overall_compliance_score": comparison.overall_compliance_score,
        "overall_compliant": bool(comparison.overall_compliant and results),
        "identified_products": products,
        "shelf_regions": shelves,
        "rendered_image": first.rendered_image if first else None,
        "overlay_path": first.overlay_path if first else None,
        # additive
- path: `packages/ai-parrot/src/parrot/models/detections.py`
  lines: 793-793
  symbol: `planogram_diagram_to_markdown`
  excerpt: |
    def planogram_diagram_to_markdown(diagram: Mapping[str, Any]) -> str:

## Notes

- `planogram_diagram_to_markdown` was the only `_markdown` hit and is unrelated to the compliance report.
- The "Text Score" / "Product Score: 36%" with a ✅ header seen in the ticket's backlit log came from the March version of the consumer; the current consumer no longer prints "Text Score" (F018).
