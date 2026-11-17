---
id: F006
query_id: Q015, Q028, Q022, Q001, Q009
type: read
intent: "Planogram type used for graphics-only endcaps."
executed_at: 2026-11-06T16:05:20Z
duration_ms: 1100
parent_id: null
depth: 0
lanes: [codebase, wiki]
merged_from: [FC-006, FC-013, FC-014, FW-001, FW-007]
---
# F006 — EndcapNoShelvesPromotional is a thin type over the shared stages; default perception is CV

## Summary

**[F006 · codebase]** `EndcapNoShelvesPromotional` ("Shelf-less promotional endcap: configured zones, text, and illumination") only supplies two provisional zone shape profiles (`promo_backlit_zone`, `promo_poster_zone`) and delegates perceive/identify/compare to the shared stages. Its default layout is `perception_mode="cv"`, `anchor_rule=SHAPE_IS_SLOT`, `identify_strategy=FULL_IMAGE`, `min_usable_shapes=1`, so a row must override `perception_mode` to get the ROI/LLM path. When the configuration lacks legacy keys, `_description()` falls back to a minimal `PlanogramDescription` with `shelves=[]`.

**[F006 · codebase]** `validate_zone_selectors` is defined in `planogram/layout.py` and called in production code only from `PlanogramCompliance._load_definition`. The other hits are its unit test. `migration.py`, `migration_runner.py` and the e2e harness never call it directly.

**[F006 · codebase]** All six types set `perception_mode="cv"` in their default layout. `LayoutProfile.perception_mode` is `Literal["cv", "llm_detector"]`; a row overrides it via `planogram_config.layout_profile.perception_mode` or a top-level `perception_mode` (a contradiction between the two is a validation error). In `llm_detector` mode `stages/perceive.py` takes a dedicated branch and the generic detector fallback in `plan.py` is disabled. `convert_config` only carries a top-level `perception_mode` over; it never sets `llm_detector` on its own.

**[F006 · wiki]** The wiki's top hits are the FEAT-090 spec (`sdd/specs/endcap-no-shelves-promotional-fix.spec.md`) and the type
module itself. `EndcapNoShelvesPromotional` ("Shelf-less promotional endcap: configured zones, text, and
illumination") only supplies two provisional zone shape profiles (`promo_backlit_zone`, polarity `bright`;
`promo_poster_zone`, polarity `edge`) and delegates perceive/identify/compare to the shared cycle stages. Its
default layout profile is `perception_mode="cv"`, `anchor_rule=SHAPE_IS_SLOT`, `identify_strategy=FULL_IMAGE`,
`min_usable_shapes=1`, and it declares `requires_slots_definition = True`.

**[F006 · wiki]** `LayoutProfile` (strict, `extra="forbid"`) is stored inside `planogram_config.layout_profile` and merged over the
type default. It exposes `perception_mode: Literal["cv", "llm_detector"] = "cv"`, `roi_detection: bool = True`
("Locate the fixture with the configuration's ROI prompt before any LLM detection") and `roi_zone_labels`
("Labels of the ROI prompt whose detections are observed zones (e.g. `top_zone`), with their text"). FEAT-612
(`refactor-planogram-compliance`, approved, target ai-parrot-pipelines 1.1.0) decided: `cv` by default for every
type with `llm_detector` as an explicit override; required zones must carry a mandatory `zone_present` binding;
every zone-only scoring unit needs at least one mandatory rule; a missing definition raises `ValueError` before
any LLM call; the eight legacy result keys are preserved.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py`
  lines: 33-63
  symbol: `_zone_profiles`
  excerpt: |
    backlit = ShapeProfile(name="promo_backlit_zone", kind=ShapeKind.ZONE.value,
        min_width=0.40, max_width=1.0, min_height=0.06, max_height=0.35,
        min_aspect=1.5, max_aspect=12.0, polarity="bright", ...)
    poster = backlit.model_copy(update={"name": "promo_poster_zone", "polarity": "edge", ...})
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py`
  lines: 66-84
  symbol: `EndcapNoShelvesPromotional.default_layout_profile`
  excerpt: |
    requires_slots_definition: ClassVar[bool] = True
    min_usable_shapes: ClassVar[int] = 1
    ...
    return LayoutProfile(
        shape_profiles=_zone_profiles(),
        anchor_rule=AnchorRule.SHAPE_IS_SLOT,
        identify_strategy=IdentifyStrategy.FULL_IMAGE,
        perception_mode="cv",
        min_usable_shapes=1,
    )
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py`
  lines: 105-117
  symbol: `EndcapNoShelvesPromotional._description`
  excerpt: |
    try:
        return self.config.get_planogram_description()
    except Exception as exc:  # noqa: BLE001 - promotional configs may omit legacy keys
        ...
        return PlanogramDescription(
            brand=str(config.get("brand", "")),
            category=str(config.get("category", "promotional")),
            aisle=AisleConfig(name=str(config.get("aisle", "promotional"))),
            shelves=[],
        )
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py`
  lines: 209-242
  symbol: `validate_zone_selectors`
  wiki: `sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py#validate_zone_selectors` (symbols lookup)
  excerpt: |
    Validate selector ids and ambiguous repeated zone kinds against a definition.
- path: `packages/ai-parrot-pipelines/tests/planogram_cycle/test_layout_profile.py`
  lines: 166-204
  symbol: `test_validate_zone_selectors_against_definition`
  excerpt: |
    def test_validate_zone_selectors_against_definition(defaults: LayoutProfile) -> None:
    ...
        validate_zone_selectors(defaults, definition, config_name="cfg")
    ...
    assert validate_zone_selectors(configured, definition, config_name="cfg") is None
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
  lines: 174-180
  symbol: `resolve_layout_profile`
  excerpt: |
    top_perception_mode = (config or {}).get("perception_mode")
    if top_perception_mode is not None:
        if "perception_mode" in overrides and overrides["perception_mode"] != top_perception_mode:
            ... invalid layout_profile.perception_mode: contradicts top-level perception_mode
        overrides["perception_mode"] = top_perception_mode
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/perceive.py`
  lines: 308-312
  symbol: `(perceive stage)`
  excerpt: |
    if profile.perception_mode == "llm_detector":
    ...
            return result.model_copy(update={"errors": [f"{image_id}: llm_detector produced
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py`
  lines: 618-620
  symbol: `convert_config`
  excerpt: |
    if "perception_mode" in config:
        layout["perception_mode"] = config["perception_mode"]
        report.warnings.append("perception_mode accepted and moved to layout_profile")
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py`
  lines: 66-117
  symbol: `EndcapNoShelvesPromotional`
  wiki: `file:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py` (page read in full; reached from Q001 result `file:sdd/specs/endcap-no-shelves-promotional-fix.spec.md`, score 1.00)
  excerpt: |
    class EndcapNoShelvesPromotional(AbstractPlanogramType):
        """Shelf-less promotional endcap: configured zones, text, and illumination."""
        requires_slots_definition: ClassVar[bool] = True
        uses_enhanced_image: ClassVar[bool] = False
        min_usable_shapes: ClassVar[int] = 1
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

*From F006:*
- In the fallback, `aisle=AisleConfig(name=str(config.get("aisle", "promotional")))` stringifies the whole `aisle` dict when the row stores `{"name": ...}` (as both rewritten rows do, F002/F003). Cosmetic only if `get_planogram_description()` succeeds first; not verified which branch the rewritten rows take.
- A second zone-oriented type, `graphic_panel_display`, exists in the registry (F005); it was not read in this lane.

*From F006:*
`layout.py` lines 221-240 show what it enforces: selector `zone_id`s must exist in the definition and selectors are "required for repeated zone kinds". The not-backlit row has two `graphic` zones and the backlit row two `graphic` zones (F002/F003), so both depend on this check passing.

*From F006:*
- The mechanically converted candidates for the two rows (F019) therefore run in `cv` mode; only the hand-written apply scripts (F002/F003) set `llm_detector`, with a comment that a lit lightbox alone satisfies the CV poster profile and would skip the ROI.
- `stages/perceive.py` was not read beyond the two matched lines.

*From F006:*
- Other Q001 hits: `flowtask::file:sdd/proposals/endcap-no-shelves-promotional-fix.proposal.md` (1.00),
  `file:sdd/tasks/completed/TASK-625-fix-detect-objects-n-zones.md` (0.88),
  `file:packages/ai-parrot-pipelines/examples/planogram_configs/endcap_no_shelves_config.py` (0.58).
- Both provisional zone profiles cap `max_height` at 0.35 of the image and require `min_aspect` 1.5: a tall
  comparison panel or the floor base graphic need not match either CV profile. See F006 for the
  `perception_mode` / `roi_detection` switches.
- [cross-lane: type=read, intent=confirm in stages/perceive.py when the LLM-detector fallback runs for a zone-only type whose CV pass finds >= min_usable_shapes (1) shape]

*From F006:*
- Documentation drift: the runbook (line 47-48) says `roi_detection_prompt` is "accepted but ignored", while
  `LayoutProfile.roi_detection` (default True) documents that the configuration's ROI prompt locates the fixture
  before LLM detection, and `roi_zone_labels` turns ROI detections into observed zones. The code is the newer
  statement; the runbook was not updated.
- Decision memory `flowtask::mem-6a7fff7f2208` (Q009 hit): reference images map `key -> [paths]` "because the
  pipeline matches the catalogue key against layout_profile.references.brand_by_reference".
- Other Q009 hits: `flowtask::file:flowtask/components/PlanogramCompliance.py` (1.00),
  `querysource::file:sdd/proposals/planogram-compliance-handler.brainstorm.md` (1.00).
- [cross-lane: type=grep, intent=where roi_detection / roi_zone_labels are consumed (stages/perceive.py, identification/detector.py) and whether ROI 'content' text feeds text evidence]
- [citation moved, §4c dedup] `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py` :: `PlanogramCompliance._load_definition` lines 207 — cited in F005.
- [citation moved, §4c dedup] `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py` :: `PlanogramCompliance._fallback_if_needed` lines 365 — cited in F005.
- [citation-check: condensed excerpt] `types/endcap_no_shelves_promotional.py` `_zone_profiles` (def at line 33): the excerpt reflows the multi-line `ShapeProfile(...)` call onto fewer lines; names and values confirmed by direct read.
