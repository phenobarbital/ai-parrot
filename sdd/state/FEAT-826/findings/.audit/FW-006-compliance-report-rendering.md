---
id: FW-006
query_id: Q007
type: wiki_query
intent: "Find where the compliance report (markdown, per-shelf status) is rendered."
executed_at: 2026-11-06T16:11:08Z
duration_ms: 0
parent_id: null
depth: 0
---

# FW-006 — The markdown report is rendered by FlowTask `_create_markdown_report`, per shelf only; it never itemises rule outcomes

## Summary

The report shown in the Epson360 UI is built in the FlowTask component, not in ai-parrot:
`PlanogramCompliance._create_markdown_report` prints overall status/score (plus strict score, assessment status
and coverage when present), then one block per `ComplianceResult` — product score, expected/found products,
issues (`missing_products`) and text requirements — then a "Slot Presence" summary and pipeline errors. The
per-shelf tick is now `compliance_score >= 1.0`. The component contains no reference to `rule_results`,
`illumination`, `appearance` or zones, so the ticket's four checks (top present, top correct image, middle
present, bottom present) and the backlit state are not itemised unless the pipeline folds them into the
per-shelf `expected_products` / `found_products` / `missing_products` / `text_compliance_results` fields.

## Citations

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/PlanogramCompliance.py`
  lines: 538-622
  symbol: `PlanogramCompliance._create_markdown_report`
  wiki: `flowtask::sym:flowtask/components/PlanogramCompliance.py#PlanogramCompliance._create_markdown_report` (Q007 score 0.98)
  excerpt: |
    for shelf_result in shelf_results:
        level = shelf_result.shelf_level.upper()
        status = "✅" if shelf_result.compliance_score >= 1.0 else "❌"
        missing_prods = getattr(shelf_result, 'missing_products', []) or []
        md.append(f"### {level} Shelf: {status}")
        md.append(f"- **Product Score:** {shelf_result.compliance_score:.1%}")
        md.append(f"- **Expected Products:** {', '.join(shelf_result.expected_products)}")
        md.append(f"- **Found Products:** {', '.join(shelf_result.found_products) or 'None'}")
        if missing_prods:
            md.append(f"- **Issues:** {', '.join(missing_prods)}")

- path: `/home/jesuslara/proyectos/flowtask/flowtask/components/PlanogramCompliance.py`
  lines: 545-555
  symbol: `PlanogramCompliance._create_markdown_report`
  excerpt: |
    strict_score = result.get('strict_compliance_score')
    ...
    if result.get('assessment_status'):
        md.append(f"**Assessment:** {result['assessment_status']}")
    coverage = result.get('coverage')

## Notes

- In the 2026-03-17 backlit log (`source.md`) the report printed `HEADER Shelf: ✅` beside a 36 % product score and
  `Text Score: 100.0%` beside failed text requirements. The current renderer derives the tick from
  `compliance_score >= 1.0` and no longer prints a "Text Score" line, so that particular inconsistency belongs to
  the pre-rewrite component.
- An anchored grep of the on-disk component for `appearance|illumination|rule_results|zone` returned no line.
- Other Q007 hits: `flowtask::sym:tests/components/test_planogram_compliance.py#TestPipelineResult.test_additive_fields_reach_the_reports`
  (1.00), `flowtask::file:sdd/specs/planogram-ink-wall-changes.spec.md` (0.82),
  `file:sdd/tasks/completed/TASK-4008-fact-tag-docs-and-harness.md` (1.00).
- ai-parrot also has a REST consumer: `PlanogramComplianceHandler`
  (`packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py` L37-424, symbols lookup);
  not read in this lane.
- [cross-lane: type=read, intent=in stages/compare.py / comparison/projection.py, how zone rule outcomes (zone_present, illumination, appearance, visual_features) are projected into ComplianceResult.expected_products / found_products / missing_products / text_compliance_results that FlowTask renders]
