---
id: F002
query_id: Q001
type: wiki_query
intent: Orient: products_found / ink_wall and endcap reference-image detection
executed_at: 2026-10-09T20:49:59Z
duration_ms: 0
parent_id: null
depth: 0
---

# F002 — Wiki orientation

## Summary

Q001 ("planogram compliance products_found slot presence ink_wall") top hits: memory `mem-14a8c23ccf44` (FEAT-645 reporting-meta validation boundary, score 1.00), `file:packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py` (0.45), `sdd/proposals/refactor-planogram-compliance.brainstorm.md` (every type on the three-step cycle). Q002 ("endcap planogram type reference images printer detection") top hits: `sym:…/models.py#PlanogramConfig` (0.56), `sym:…/handlers/planogram_compliance.py#PlanogramComplianceHandler._build_planogram_config` (0.20), `examples/planogram_configs/endcap_no_shelves_config.py` (0.18). The wiki confirms every type runs the shared perceive → identify → compare cycle; the detail was taken from code reads (F003–F008).

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/models.py`
  lines: 78-85
  symbol: `PlanogramConfig.reference_images`
  excerpt: |
    reference_images: Dict[str, Union[str, Path, List[str], List[Path], Image.Image]] = Field(
        default_factory=dict,
        description=("Local reference images per catalogue key: ... Loaded once per run "
                     "into the identification reference bank (opaque labels; never used as expected placement)."),
    )

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py`
  lines: 312-346
  symbol: `PlanogramComplianceHandler._build_planogram_config`
  excerpt: |
    reference_images_raw = self._decode_json_column(row.get("reference_images")) or {}
    ...
    reference_images=reference_images,

## Notes

Wiki page ids for follow-up: `mem-14a8c23ccf44`, `file:packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py`, `sym:packages/ai-parrot-pipelines/src/parrot_pipelines/models.py#PlanogramConfig`.
