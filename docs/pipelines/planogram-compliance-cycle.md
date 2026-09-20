# Planogram compliance cycle (perceive → identify → compare)

## Overview

`PlanogramCompliance.run()` used to be a pure-LLM, ROI-first sequence: an LLM located the
endcap, another call detected and named products inside that ROI, and a per-type
`check_planogram_compliance` scored the result. Every stage depended on a Google-only
auxiliary client, the image was always contrast-enhanced, and a wrong ROI silently removed
products from the assessment. FEAT-574 replaces that orchestration with a three-stage
template and makes the provider a configuration choice (`llm_backend`).

The cycle is **perceive → identify → compare**. *Perceive* finds shapes, rows and slots on the
untouched full-resolution photo with classical CV (and optional local OCR), and labels every
shape `on_fixture` / `off_fixture` / `uncertain` from spatial evidence. *Identify* asks the
vision LLM — through one provider-neutral adapter — what each listed area shows, never what it
*should* show. *Compare* registers the observed rows against a versioned slots definition,
decides every expected facing, and scores shelves with an explicit strict/lenient credit table.

Perception, membership, registration, the per-facing decision and scoring are deterministic
pure functions: the same inputs always give the same result. Only stage 2 (and the optional
LLM-detector fallback) calls a model. Legacy types keep working unchanged through the default
hooks, which run the old sequence as a *legacy adapter*.

## Stage contracts

| Stage | Hook | Input | Output | Runs where |
|---|---|---|---|---|
| 1 — perceive | `perceive(image, image_id, ctx)` | untouched `PIL.Image` (enhanced only for `uses_enhanced_image=True`) | `PerceptionResult` (shapes, slots, zones, rows, `detection_source`, `ocr_available`, optional `legacy` payload) | event loop; CV and OCR through `ctx.executor` (`CpuExecutor`, spawn process pool) |
| fallback | — (template) | perception with fewer than `min_usable_shapes` on-fixture shapes | shapes from `llm_detect_shapes`, membership re-applied, `slots=[]`, `detection_source="llm"` | `VisionAdapter` (LLM) |
| 2 — identify | `identify(image, perception, ctx)` | stage-1 output | `IdentificationResult` (identifications, validated additions, errors) | `VisionAdapter` (`identify_full_image` / `identify_strips`, optional `verify_unresolved`) |
| 3 — compare | `compare(perceptions, identifications, ctx)` | every image's stage-1/2 output | `ComparisonResult` (compliance results, positions, shelf scores, coverage, evidence quality, assessment status) | event loop (pure functions) |

`ctx` is a `CycleContext` created per `run()`: `vision` (`VisionAdapter`, one bounded LLM
semaphore per run), `executor` (`CpuExecutor`, closed in `finally`), `ocr` (`OcrReader`),
`definition` / `bindings` (loaded once when the type requires them), `credit_policy`,
`evidence_weights`, `output_dir` and an `errors` sink. One failed photo is isolated; the run
continues with the others.

## Type hook contract

Every type subclasses `AbstractPlanogramType` and declares four class attributes:

| ClassVar | Default | Meaning |
|---|---|---|
| `identify_strategy` | `IdentifyStrategy.FULL_IMAGE` | `FULL_IMAGE` (one call) or `STRIPS` (one call per row, Set-of-Marks) |
| `requires_slots_definition` | `False` | construction fails without `PlanogramConfig.slots_definition` |
| `min_usable_shapes` | `0` | fallback threshold on **on-fixture** shapes; `0` disables the fallback |
| `uses_enhanced_image` | `True` | legacy default; migrated types set `False` and get the untouched image |

The default hooks form the **legacy adapter**: `perceive` runs `compute_roi` →
`detect_objects` → promotional OCR → virtual shelves → fact-tag refinement / assignment /
corroboration → header injections (`types/legacy_adapter.py`) and returns
`detection_source="legacy_llm"`; `identify` is a pass-through; `compare` calls
`check_planogram_compliance` on the legacy payload, reports `assessment_status="legacy_unmeasured"`
and never treats an empty result list as a pass.

`validate_contract()` runs at construction: a type must override either the complete legacy
contract (`compute_roi`, `detect_objects`, `check_planogram_compliance`) or all three hooks
(`TypeError` otherwise); legacy-only types need both `roi_detection_prompt` and
`object_identification_prompt`; `requires_slots_definition` types need a `slots_definition`
(`ValueError` otherwise).

## Adding a planogram type

A migrated type is composition only — no CV, OCR, prompt or scoring code of its own.
`InkWall` (`types/ink_wall.py`) is the reference.

1. **Shape profile(s).** Say what classical CV should propose; profiles are data.

   ```python
   from parrot_pipelines.planogram.perception.profiles import PRICE_TAG_PROFILE
   from parrot_pipelines.planogram.perception.shapes import propose_shapes

   candidates = await ctx.executor.run(propose_shapes, bgr, [PRICE_TAG_PROFILE])
   ```

2. **Anchoring rule.** Turn proposals into rows and slots.

   ```python
   from parrot_pipelines.planogram.perception.rows import group_rows
   from parrot_pipelines.planogram.perception.slots import AnchorRule, build_slots

   rows = group_rows(candidates, image.width)
   slots = build_slots(rows, size, image_id=image_id, rule=AnchorRule.TAG_BELOW_PRODUCT,
                       fill_gaps=True, untagged_bottom_row=True)
   ```

   Build shape ids with `candidate_shape_id(image_id, candidate)` so slots join their anchors,
   then label membership with `assign_membership(shapes, zones, size)`.

3. **Descriptor vocabulary.** Tell stage 2 which `Descriptors` fields to report and resolve
   what was read to a definition product id — never from the slot's expectation.

   ```python
   result = await identify_strips(bgr, perception, ctx, vocabulary=["family", "colors", "pack", "xl"])
   product, candidates = resolve_identity(identification, ctx.definition)
   ```

   `compare` then chains `register_image` → `merge_positions` → `score_shelves` → `summarize`
   → `project_compliance` → `finalize_comparison`.

4. **Register it.** Add the class to `planogram/types/__init__.py`, to
   `PlanogramCompliance._PLANOGRAM_TYPES` (`"ink_wall": InkWall`), to the lazy exports of
   `planogram/__init__.py` and to `parrot_pipelines.PIPELINE_REGISTRY`, and set the four
   ClassVars (`InkWall`: `STRIPS`, slots required, fallback under 8 usable shapes, untouched image).

## Result keys

The eight legacy keys are always present:

- `step3_compliance_results` / `compliance_results` — the same list, one `ComplianceResult` per shelf (each may carry an additive `assessment`).
- `overall_compliance_score` — unweighted mean of shelf scores (lenient credit for migrated types).
- `overall_compliant` — never `True` with an empty result list or an inconclusive assessment.
- `identified_products`, `shelf_regions` — legacy payload, or a projection of the identifications for migrated types.
- `rendered_image`, `overlay_path` — the first successfully processed image.

Additive keys:

- `detections`, `identifications` — per-image stage-1 / stage-2 outputs.
- `position_results`, `shelf_scores` — per-facing decisions and per-shelf measures.
- `coverage` — resolved facings / expected facings (global over facings).
- `definition_coverage` — fraction of expected facings with sufficient descriptors.
- `assessment_status` — `complete`, `inconclusive` or `legacy_unmeasured`.
- `strict_compliance_score` — the same mean with strict credits.
- `evidence_quality` — mean evidence weight of the deciding observations; never changes a credit.
- `detection_source` — `cv`, `llm`, `legacy_llm` or `mixed`.
- `ocr_available`, `resolved_backend`, `renders` (one per image), `errors`.

*Compliance* says how well the visible shelf matches the plan; *coverage* says how much of the
plan could be assessed at all; *evidence quality* says how strong the deciding observations
were. A shelf with unresolved facings is never `COMPLIANT`.

## Optional local OCR

`pip install "ai-parrot-pipelines[planogram]"` — without it text is read by the LLM only and `ocr_available=False`.
