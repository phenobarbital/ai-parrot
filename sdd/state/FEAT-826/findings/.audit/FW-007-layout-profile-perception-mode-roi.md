---
id: FW-007
query_id: Q009
type: wiki_query
intent: "Prior SDD decisions on planogram config rows (appearance rule, refactor, new pipeline)."
executed_at: 2026-11-06T16:11:08Z
duration_ms: 0
parent_id: null
depth: 0
---

# FW-007 — `LayoutProfile` carries `perception_mode` (cv | llm_detector), `roi_detection` (default True) and `roi_zone_labels`; FEAT-612 fixes cv as the default and mandates `zone_present`

## Summary

`LayoutProfile` (strict, `extra="forbid"`) is stored inside `planogram_config.layout_profile` and merged over the
type default. It exposes `perception_mode: Literal["cv", "llm_detector"] = "cv"`, `roi_detection: bool = True`
("Locate the fixture with the configuration's ROI prompt before any LLM detection") and `roi_zone_labels`
("Labels of the ROI prompt whose detections are observed zones (e.g. `top_zone`), with their text"). FEAT-612
(`refactor-planogram-compliance`, approved, target ai-parrot-pipelines 1.1.0) decided: `cv` by default for every
type with `llm_detector` as an explicit override; required zones must carry a mandatory `zone_present` binding;
every zone-only scoring unit needs at least one mandatory rule; a missing definition raises `ValueError` before
any LLM call; the eight legacy result keys are preserved.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py`
  lines: 66-129
  symbol: `LayoutProfile`
  wiki: `sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py#LayoutProfile` (symbols lookup; Q009 top hit `file:packages/ai-parrot-pipelines/tests/planogram_cycle/test_layout_profile.py`, score 1.00)
  excerpt: |
    model_config = ConfigDict(extra="forbid")
    ...
    perception_mode: Literal["cv", "llm_detector"] = "cv"
    #: Locate the fixture with the configuration's ROI prompt before any LLM detection.
    roi_detection: bool = True
    #: Labels of the ROI prompt whose detections are observed zones (e.g. ``top_zone``), with their text.
    roi_zone_labels: List[str] = Field(default_factory=list)
    roi_product_labels: Optional[str] = None
    min_usable_shapes: int = Field(default=1, ge=0)

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py`
  lines: 209-242
  symbol: `validate_zone_selectors`
  wiki: `sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py#validate_zone_selectors` (symbols lookup)
  excerpt: |
    Validate selector ids and ambiguous repeated zone kinds against a definition.

- path: `sdd/specs/refactor-planogram-compliance.spec.md`
  lines: 10-13, 44, 66-68, 112, 229-231, 238-239
  symbol: `FEAT-612`
  wiki: `file:sdd/specs/refactor-planogram-compliance.spec.md`
  excerpt: |
    - Preserve the handler invocation, HTTP contract, and eight legacy result keys.
    A missing definition raises `ValueError` naming `config_name` and `docs/pipelines/planogram-cycle-migration.md` before any LLM call.
    | `perception_mode` | `cv` by default for every type; explicit `llm_detector` remains a diagnostic override |
    Required zones must have a mandatory `zone_present` binding (converter emits it; runtime validation
    rejects omissions). Every zone-only scoring unit needs at least one mandatory rule. A missing zone
    is failed only with positive evidence that its expected region was inspected; unknown visibility
    is unassessed. Completely empty perceptions always produce inconclusive/false.
    For zone-only units use existing product-presence/text/visual weighting with required-zone presence
    as the product term and apply illumination penalties once.

- path: `wiki/flows/pipelines/planogram-cycle-migration.md`
  lines: 36-49
  symbol: `Layout and reference policy`
  excerpt: |
    A zone selector matches observed zones to one configured zone in one of three ways: `ordinal` ...,
    `region` (a box in whole-photo coordinates), or `band` — `[y_start, y_end]` as fractions of the
    observed fixture height.
    For one release, `roi_detection_prompt`, `object_identification_prompt`, `detection_model`,
    `confidence_threshold`, and `detection_grid` are accepted but ignored.

## Notes

- Documentation drift: the runbook (line 47-48) says `roi_detection_prompt` is "accepted but ignored", while
  `LayoutProfile.roi_detection` (default True) documents that the configuration's ROI prompt locates the fixture
  before LLM detection, and `roi_zone_labels` turns ROI detections into observed zones. The code is the newer
  statement; the runbook was not updated.
- Decision memory `flowtask::mem-6a7fff7f2208` (Q009 hit): reference images map `key -> [paths]` "because the
  pipeline matches the catalogue key against layout_profile.references.brand_by_reference".
- Other Q009 hits: `flowtask::file:flowtask/components/PlanogramCompliance.py` (1.00),
  `querysource::file:sdd/proposals/planogram-compliance-handler.brainstorm.md` (1.00).
- [cross-lane: type=grep, intent=where roi_detection / roi_zone_labels are consumed (stages/perceive.py, identification/detector.py) and whether ROI 'content' text feeds text evidence]
