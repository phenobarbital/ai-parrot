---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: New Planogram Compliance Pipeline (CV+OCR → LLM → compare)

**Date**: 2026-09-18
**Author**: Jesus Lara (with Claude)
**Status**: exploration
**Recommended Option**: A

**Review consolidation**: 2026-09-18. The contracts below incorporate the
evaluation follow-up. Numerical spike and evidence defaults remain provisional
until validated; this document is still an exploration, not an approved spec.

**Related**: FEAT-565 `new-planogram-compliance-algo` (merged) — produced the
standalone `examples/planogram/plancheck/` engine this feature draws on. FEAT-048
`planogram-compliance-modular` — introduced `AbstractPlanogramType`.

---

## Problem Statement

`parrot_pipelines.planogram.PlanogramCompliance` is a **pure-LLM** pipeline. Its
cycle is `compute_roi → detect_objects_roi → detect_objects →
check_planogram_compliance`, delegated to an `AbstractPlanogramType` composable.
Three problems:

1. **ROI is a single point of failure.** Everything downstream is scoped to the
   ROI the LLM finds in step 1. `plan.py` wraps `compute_roi` in a bare
   `try/except` that only logs — when the ROI is not found, the rest of the run
   works on nothing and the result is meaningless.
2. **Detection is done by the LLM**, which is the thing LLMs are worst at:
   counting and localising ~100 small similar objects. Bounding boxes drift,
   facings are merged or invented, and there is no deterministic evidence to
   audit.
3. **No type can express a dense wall.** `planogram_type="ink_wall"` is accepted
   by `PlanogramConfig` but raises `ValueError` in `PlanogramCompliance.__init__`
   — there is no `InkWall` class. The reference for such a wall (102 products,
   104 facings, 6 shelves) does not fit `PlanogramDescription`'s
   `shelves → products(name, quantity_range)` shape.

FEAT-565 proved a different cycle in `examples/planogram/plancheck/`:
deterministic OpenCV detection of price tags + RapidOCR, then an LLM that only
*identifies* what is inside regions it is handed, then a deterministic
comparison against the planogram. That engine is a standalone example, ink-wall
specific, and not reachable from the production handler.

**Who is affected**: field-compliance users of `POST /api/v1/planogram/compliance`
(`PlanogramComplianceHandler`), and developers adding planogram types.

**Goal**: make the three-step cycle the *only* cycle of `PlanogramCompliance`,
with the existing public call and response shapes, and with type-specific parts
expressed per `AbstractPlanogramType`. Migrated ProductOnShelves configurations
require a reviewed data migration before deployment; this is not an unchanged
configuration or unchanged score-semantics guarantee.

### The operating cycle (user-defined)

1. **Perceive (deterministic)** — full-resolution image → OpenCV finds shapes,
   RapidOCR reads text inside each shape → structured output: shape location
   (coords, shelf position) + detected text. No ROI gate.
2. **Identify (LLM)** — step-1 JSON **plus the image** go to the LLM
   (`ask_to_image`, structured input and structured output). The LLM identifies
   product + brand per shape, confirms or corrects the OCR text, and returns a
   **confidence score** per identification.
3. **Compare (deterministic)** — identified detections vs the planogram
   definition of that type → compliance, **global and per-shelf**.

## Constraints & Requirements

- **Public API compatibility, with an explicit configuration migration.**
  `PlanogramCompliance(planogram_config=..., llm=...)`
  and `await pipeline.run(image, output_dir=..., image_id=...)` keep working.
  The handler reads exactly four result keys — `overlay_path`,
  `overall_compliant`, `overall_compliance_score`, `compliance_results` — and
  the examples additionally read `step3_compliance_results` and
  `rendered_image`. **All eight existing keys are preserved**; new keys are
  additive. Existing ProductOnShelves configurations must receive a validated
  `slots_definition` before the new runtime is deployed. See Migration and
  compatibility contract; preserving keys does not promise identical scores.
- **Total replacement of the run cycle** (user decision). The ROI-first
  orchestration in `plan.py` goes away; it is not kept behind a flag.
- **Unmigrated types keep working through an adapter in the base class** (user
  decision). `GraphicPanelDisplay`, `ProductCounter`,
  `EndcapNoShelvesPromotional`, `EndcapBacklitMultitier` retain their algorithms;
  provider-neutral call-site updates are still in scope. The
  base `AbstractPlanogramType` provides default implementations of the new
  hooks that wrap their existing `compute_roi` / `detect_objects` /
  `check_planogram_compliance`.
- **Scope of migrated types**: `InkWall` (new; price-tag anchored) and
  `ProductOnShelves` (existing; product/shelf/backlit anchored). These are the
  two archetypes; the other four migrate in later features.
- **Re-write, inspired by `plancheck`** (user decision) — algorithms are the
  reference, but the code is re-implemented against the package's models and
  conventions. `plancheck` is not imported, moved, or vendored.
- **LLM call granularity is declared by the type** (user decision): full image
  in one call, or per-shelf/row strips in parallel.
- **CV failure degrades to an LLM detector** (user decision): when shapes fall
  under a per-type threshold, the LLM proposes boxes on the full image and the
  cycle continues; the result records `detection_source="llm"`.
- **One image or several** (user decision): `run()` accepts a single image or a
  list; several photos of the same fixture are merged per facing.
- **Slot definition comes from a JSON** (user decision): `PlanogramConfig` says
  *what type* the planogram is; a separate JSON defines shelves, slots and
  products (an InkWall may have 102 products or 50). `planogram_page1.json` is
  the InkWall definition; **an equivalent JSON must be authored for
  ProductOnShelves**.
- **Local OCR is an optional extra**, with lazy imports; without RapidOCR,
  text is read by the LLM only. OpenCV remains an existing hard dependency;
  this feature does not move it into an extra. Declare directly used runtime
  dependencies in the package rather than relying on transitive installs.
- **Model benchmark is a deliverable** (user decision): reproducible
  descriptive comparison of `gemini-3.5-flash` vs Claude Sonnet 5 informs the
  user's default selection. It measures speed and reported outputs, not accuracy
  or recall. The perception spike has a separate manually checked sample.
- **Slots definition source** (user decision, round 4): the definition may come
  from a **new JSONB column on `troc.planograms_configurations`** *or* from a
  JSON file — "JSON on disk" and "JSONB from Postgres" are the same thing to
  `PlanogramConfig`, which receives a dict (or a path it loads). This is what
  gives the fine granularity: how many shelves, slots and products a given
  fixture has.
- **Prompts become optional** (user decision, round 4):
  `roi_detection_prompt` and `object_identification_prompt` are required today
  but object detection — and potentially the ROI — is now done zero-shot by
  OpenCV. They stay accepted (the adapter path of unmigrated types still uses
  them) but are no longer mandatory.
- **Provider-neutral, by homologating the clients** (user decision, round 4).
  Must run on both Google and Anthropic clients. In scope of this spec:
  add `no_memory` to `AnthropicClient.ask_to_image`, and add a
  `detect_objects` to `AnthropicClient` with the same signature and return
  shape as Google's. See Code Context.
- **No hard-coded models or Google client** (user decision, round 4). Every
  `model="gemini-3.5-flash"` literal and the unconditional
  `GoogleGenAIClient` `roi_client` in `AbstractPipeline` go away; provider and
  model come from the pipeline's `llm` / `llm_provider` / `llm_model`, so either
  client can drive the whole run.
- **`ProductOnShelves` tests are a deliverable** (user decision, round 4):
  characterization tests for the currently untested compliance, fact-tag OCR
  and illumination logic are built as part of this feature, before migrating it.
- **Benchmark needs no labelled ground truth** (user decision, round 4). It
  reports, per backend and per photo: identification **confidence**, compliance
  **scoring**, **number of objects detected**, and **duration**. The user
  judges the default from those numbers; there is no automated pass bar.
- **Round-5 decisions** (user, 2026-09-18):
  - **Spike first.** The first task is a time-boxed spike measuring
    profile-driven shape proposals on real ProductOnShelves photos; it fixes the
    profiles. Its manually checked sample and provisional acceptance criteria
    are defined below. A failed or inconclusive spike ⇒ ProductOnShelves starts
    on the LLM-detector fallback, perception hook unchanged.
  - **The LLM may add shapes** the CV missed, in every type, flagged
    `source="llm_added"` with a lower evidence weight. Raw model confidence is
    preserved; source weights do not directly reduce compliance credit.
  - **`slots_definition` replaces** `planogram_config.shelves[].products` as the
    expected-products reference for migrated types; **non-product expectations
    stay in `planogram_config`** (backlit/poster, illumination,
    `text_requirements`, `compliance_threshold`, per-shelf weights,
    `advertisement_endcap`).
  - **Field/column name `slots_definition`** (`JSONB NULL`), plus an idempotent
    ALTER script for deployed databases (also drops `NOT NULL` on both prompts).
  - **Backend (provider + model) is a `PlanogramConfig` field**; explicit
    constructor arguments still win. Benchmark compares `gemini-3.5-flash` vs
    `claude-sonnet-5`.
  - **Anthropic vision default bumped to `ClaudeModel.SONNET_5`** (`ask_to_image`
    and the new `detect_objects`).
  - **LLM-assisted descriptor utility** is in scope: proposes descriptors per
    position from the **POG PDF only** (catalog/SKU/price lookup discarded — no
    data to back it yet); never proposes `price`; the user reviews.
  - **Backend field is one `"provider:model"` string** (the `LLMFactory.create`
    format), with a matching nullable DB column.
  - **`run(image=…)` accepts one image or a list**; the handler stays
    single-file in this feature.
  - **Header/backlit/poster are zones detected apart**, outside row→shelf
    registration; product rows register in increasing order.
  - **Perception, OCR and LLM crops use the untouched full-resolution image**;
    `_enhance_image` stays only on the legacy adapter path.
  - **`examples/planogram/plancheck/` stays as it is** — independent tool and
    live reference. Not moved, deleted or rewired.
- Repo rules: async-first, no blocking I/O on the event loop. CPU-bound
  OpenCV/OCR and image encoding run in a bounded process executor; blocking
  file I/O may use `asyncio.to_thread`. Pydantic v2 models, `self.logger`, `aiohttp`
  only, Google-style docstrings, no new `requests`/`httpx`.
- This repository is public: real store photos and `planogram_page1.json` are
  git-ignored. **Tests must run on synthetic fixtures**, offline, with a fake
  LLM backend (as `plancheck`'s 15 test files already do).

---

## Options Explored

### Option A: Three-stage template method in `PlanogramCompliance` + per-type hooks (adapter default)

`PlanogramCompliance.run()` becomes a fixed three-stage template:
**perceive → identify → compare**, plus shared render/assemble. Each stage calls
a hook on the type handler. `AbstractPlanogramType` gains the new hooks as
**concrete methods with a default implementation that wraps the legacy abstract
methods** — so the four unmigrated types run unchanged through the new `run()`.
`InkWall` and `ProductOnShelves` override the hooks with the real CV+OCR path.

A new perception layer inside the package provides type-agnostic building
blocks the hooks compose:

- a **shape proposer** driven by per-type *shape profiles* (size band, aspect
  band, brightness polarity, rectangularity, contrast) — the generalisation of
  `plancheck.detection.find_candidates`, whose constants today describe only a
  white landscape price label;
- **row/shelf structure** from aligned shapes (generalised `group_rows`) and,
  for shelf-anchored types, horizontal shelf-edge detection;
- **slot geometry** (generalised `grid.build_slots`: tag-below-product is one
  anchoring rule, not the only one);
- a lazy **OCR reader** (RapidOCR, optional);
- a **provider-neutral vision adapter** (`ask_to_image` + `structured_output`,
  kwargs normalised per provider, schema-aware disk cache, one repair retry) —
  modelled on `plancheck.vision.VisionBackend`;
- a **reference loader** that parses the slots JSON into facings + descriptors;
- **registration + scoring** (row→shelf DP alignment, per-facing decision list,
  strict/lenient credits, per-shelf and global metrics), mapped back onto
  `ComplianceResult` so existing consumers see the same shape.

✅ **Pros:**
- Honours every user decision at once: total replacement, adapter in the base,
  per-type strategy, re-write against package models.
- No ROI gate: perception always produces *something* auditable; the LLM
  fallback covers the low-shape case explicitly instead of silently.
- Deterministic stages 1 and 3 are unit-testable offline with synthetic
  images — the coverage the current pipeline lacks.
- The generalisation seam is narrow and already identified: everything
  downstream of detection consumes only rows/slots, so a new type is mostly a
  shape profile + an anchoring rule + a descriptor vocabulary.
- Provider-neutrality is solved once, in the adapter, not per type.

❌ **Cons:**
- **Generic zero-shot shape detection does not exist yet.** `plancheck`
  detects one thing — bright landscape labels via six fixed global thresholds,
  no morphology, no edges. Detecting printers, product boxes, posters and
  backlits with classical CV is new R&D with unproven recall (see Remaining
  Validation). This is the feature's main technical risk.
- `ProductOnShelves` is 1683 lines with **no tests** on
  `check_planogram_compliance`, fact-tag OCR or illumination. Migrating it
  without characterization tests risks silent regressions.
- The adapter means two generations of type contract coexist until the other
  four types migrate.
- Large surface: new subpackage, new type, one migrated type, config change,
  extra, benchmark.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `opencv-python-headless>=4.8` | shape proposals, strips, annotation | **already a hard dep** of `ai-parrot-pipelines` |
| `numpy` | array ops | used transitively today, **not declared** — declare it |
| `rapidocr` (3.9.2 installed) | local OCR of tag/label crops | NEW, optional extra; API assumed: `RapidOCR()(img).txts` |
| `onnxruntime` (1.30.0 installed) | RapidOCR backend | never imported directly; pulled by rapidocr |
| `rapidfuzz` (3.11.0 installed) | brand/alias fuzzy match | in core `ai-parrot` deps already; declare directly as a runtime dep if comparison uses it |
| `pydantic` v2 | all contracts | existing |
| `pillow` | `open_image`, overlay render | existing (transitive); declare directly for runtime image handling |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py` — keep `__init__`, `_PLANOGRAM_TYPES`, `render_evaluated_image`, the result-dict keys; replace the body of `run()`.
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py` — extend with the new hooks; keep `_check_illumination`, `_refine_shelves_from_fact_tags`, `get_render_colors`.
- `packages/ai-parrot/src/parrot/models/detections.py`, `compliance.py` — `DetectionBox`, `ShelfRegion`, `IdentifiedProduct`, `ComplianceResult`, `ComplianceStatus` stay the public result vocabulary.
- `examples/planogram/plancheck/*` — **algorithmic reference only** (detection, grid, prices, vision, identify, verify, reference, registration, scoring, report) and its test suite as a model for offline tests.
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/` — `CellResultMerger._deduplicate` / `_compute_iou` for cross-strip dedup.

---

### Option B: Promote `plancheck` as the engine; `PlanogramCompliance` becomes a façade

Move `examples/planogram/plancheck/` into the package more or less intact and
make `PlanogramCompliance.run()` build a `Settings`, call `run_check()`, and
translate `ComplianceReport` → the legacy result dict. Types become thin
configuration objects over the engine.

✅ **Pros:**
- Fastest path to a working InkWall in production; the code is tested (15
  offline test files) and already multi-photo.
- One engine, no re-implementation drift.

❌ **Cons:**
- **Contradicts the user's "re-write inspired" decision.**
- The engine is ink-wall shaped end to end: tag-below-product grid, `$` price
  regex, `family/xl/colors/pack` descriptors hard-coded into `SlotReading` and
  `resolve_identity` rule 2, `CLOSEOUT` sentinel, strictly-increasing shelf
  assignment. `ProductOnShelves` (no tags, backlit, illumination, fact tags,
  text requirements) does not fit without rewriting most of it anyway.
- It has its own models (`Box`, `Slot`, `PositionResult`…) parallel to
  `DetectionBox` / `IdentifiedProduct` / `ComplianceResult` — a permanent
  translation layer.
- Writes its own report directory (`exist_ok=False`), mixes relative and
  absolute (`from plancheck…`) imports, no `self.logger`.

📊 **Effort:** Medium (for InkWall) → High (once ProductOnShelves is forced in)

📦 **Libraries / Tools:** same as Option A.

🔗 **Existing Code to Reuse:**
- `examples/planogram/plancheck/` — moved wholesale.
- `examples/planogram/tests/` — moved with it.

---

### Option C: Open-vocabulary detector for shape proposals (unconventional)

Replace classical-CV proposals with a zero-shot open-vocabulary detector
(text-prompted: "printer", "ink cartridge box", "price tag", "backlit poster",
"shelf"), keep RapidOCR, then the same LLM-identify and compare stages. The type
supplies the prompt vocabulary instead of a geometric shape profile.

✅ **Pros:**
- Genuinely zero-shot on *objects*, not just on high-contrast rectangles —
  directly addresses Option A's main risk (printers are not clean rectangles).
- Returns class hints for free, shrinking the LLM's job.
- No training, matching the "no pre-training" requirement.

❌ **Cons:**
- Heavy dependencies (`torch` + model weights, GPU strongly preferred) in a
  package whose current hard deps are OpenCV + pytesseract. The handler runs on
  gunicorn/aiohttp workers — weights per worker and cold-start cost.
- This is what `legacy.py` (`RetailDetector`: YOLO + CLIP + torch) already
  tried and the project moved away from.
- Small dense objects (104 facings on one wall) are a known weak spot for these
  detectors; price tags are better found by plain thresholds.
- Non-deterministic across model versions; harder to unit-test offline.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `transformers` + `torch` | OWLv2 / Grounding-DINO style zero-shot detection | heavy; GPU recommended |
| `ultralytics` | YOLO-World open-vocab detection | AGPL-3.0 licence — check before adopting |
| `rapidocr` | OCR | as Option A |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/legacy.py` — `RetailDetector` as prior art for model loading/device handling.

---

### Option D: LLM proposes, CV verifies (inverted order — unconventional)

Keep the LLM as the first detector (full image → boxes + labels, structured
output), then use OpenCV/OCR *per proposed box* to snap the box to real edges,
read text locally, and reject boxes with no supporting pixels evidence. Compare
stage as in A.

✅ **Pros:**
- Smallest change to today's flow; no generic shape-proposal R&D.
- CV becomes a cheap hallucination filter and an OCR grounding step.

❌ **Cons:**
- Keeps the core weakness: recall and counting are still the LLM's. On a
  104-facing wall the LLM will not enumerate every facing.
- **Contradicts the stated cycle** (CV first, LLM second) and the
  "one-shot, zero-shot CV detection" goal.
- A missed LLM box is unrecoverable — the same class of failure as the ROI
  problem, moved one level down.

📊 **Effort:** Medium

📦 **Libraries / Tools:** same as Option A.

🔗 **Existing Code to Reuse:**
- `types/product_on_shelves.py:_find_poster`, `_detect_legacy` — existing LLM detection calls.

---

## Recommendation

**Option A** is recommended because it is the only option consistent with all
the decisions taken during discovery (total replacement, adapter in the base,
per-type LLM strategy, re-write against package models) and it fixes the actual
defect: a non-deterministic, un-auditable first stage with a single point of
failure.

What we trade off, honestly:

- **We accept R&D risk on generic shape detection.** Classical CV is proven
  here only for price tags. The recommendation is to contain that risk rather
  than avoid it: (a) ship **InkWall first** — its detector is already proven;
  (b) treat `ProductOnShelves` perception as a profile-driven proposer whose
  recall is measured on the spike's manually checked sample before it becomes
  the default; (c) let the identify stage **add** shapes the CV missed (flagged
  `source="llm_added"`) while preserving evidence provenance and uncertainty;
  (d) keep the explicit LLM-detector fallback. Option C stays on the
  table as a later swap *behind the same perception hook* if measured recall is
  not good enough — the hook makes that a contained change.
- **We accept a transitional dual contract** (legacy abstract methods + new
  hooks) in exchange for not rewriting four working types in one feature.
- **We reject B** despite its speed because it would import an ink-shaped engine
  and a parallel model vocabulary into the package, and reject **D** because it
  preserves the failure mode we are trying to remove.

---

## Feature Description

### User-Facing Behavior

- **The handler keeps its request and existing response fields.**
  `POST /api/v1/planogram/compliance` still returns `rendered_image_base64`, `overall_compliant`,
  `overall_compliance_score`, and `shelf_results`, produced from the same
  result keys. Add `assessment_status`, `coverage`, and `errors` to the response
  so an incomplete assessment is distinguishable from observed non-compliance.
  This additive response change is part of the consolidation.
- Callers of `PlanogramCompliance.run()` get the existing eight keys plus new,
  additive ones:
  - `detections` — stage-1 output: shapes with pixel box, kind, shelf/row,
    slot index, OCR text, OCR confidence.
  - `identifications` — stage-2 output: per shape, product, brand,
    confirmed/corrected text, **confidence**, evidence, `source`
    (`cv` | `llm_added` | `llm`).
  - `position_results` — per expected facing: status (`match`, `misplaced`,
    `variant_unresolved`, `mismatch`, `empty`, `inferred_present`,
    `occupied_unassigned`, `conflict`, `not_assessed`, `not_visible`), credits.
  - `shelf_scores` — per-shelf strict/lenient %, coverage, occupancy.
  - `coverage`, `definition_coverage`, `assessment_status`, `strict_compliance_score`,
    `evidence_quality`, `detection_source`, `errors`.
- `run()` accepts one image or a list of images of the same fixture.
- A new planogram type `ink_wall` is selectable via
  `PlanogramConfig.planogram_type`.
- `PlanogramConfig` gains a way to point at / embed a **slots definition JSON**.
- Installing `ai-parrot-pipelines[planogram]` enables local OCR; without it the
  pipeline still runs and reports that local OCR was unavailable.
- `PlanogramConfig` no longer requires `roi_detection_prompt` /
  `object_identification_prompt`.
- The same run works with a Google or an Anthropic client — no model name or
  provider is hard-coded anywhere in the pipeline or the types.
- A benchmark script runs the same photos through each backend and reports, per
  photo and aggregated: identification confidence, compliance scoring, number
  of objects detected (CV shapes, identified, LLM-added) and duration per stage.
  No ground truth is required; the user picks the default from that report.

### Migration and compatibility contract

- Ship a preflight/conversion utility for existing ProductOnShelves config
  dicts or exported DB rows. It emits candidate slots JSON and a validation
  report, without changing the database. Preserve the original config for
  review and rollback. Fixed quantities can seed candidate facings; quantity
  ranges and ambiguous positions require human resolution. Never invent an
  exact layout from a range or copy one fixture's sample JSON to every config.
- Before activating the replacement runtime, apply the idempotent schema
  ALTER, review and backfill `slots_definition` for every active migrated
  configuration, then run a read-only preflight that reports unresolved rows.
  A nullable column alone is not a completed migration. The user applies the
  database changes; this feature supplies scripts and the runbook.
- `InkWall` and migrated `ProductOnShelves` fail construction with a precise
  migration/validation error when slots are missing or invalid. Legacy types
  do not require slots; validate their required prompts at construction.
  There is no implicit runtime conversion or hidden old-cycle switch.
- Give shelves, expected products/facings, and non-product zones stable IDs
  within a versioned definition. Keep non-product rules in `planogram_config`,
  with explicit bindings to these IDs. The migration must extract and preserve
  nested `illumination_required`, `illumination_penalty`, `text_requirements`,
  and visual features currently stored in `shelves[].products`, as well as
  poster/backlit, promotional, threshold, and shelf-weight settings.
  Preserve legacy entries for rollback; migrated comparison reads expected
  products only from slots and non-product rules through the validated bindings.
  Reject dangling or ambiguous bindings instead of silently dropping rules.
- Legacy adapter characterization tests must cover the complete old
  orchestration, including enhancement, promotional OCR, poster/logo injection,
  virtual shelves, shelf assignment, fact-tag refinement and corroboration.
  Delegating only the three named public methods is insufficient. Legacy
  types retain their scoring behavior; migrated types use the explicit scoring
  contract below. Explain the score-semantics change in the migration runbook.
- For multi-image calls, identify all observations and boxes by `image_id`;
  merge only after registration to stable expected-facing IDs. Return additive
  per-image render records; the existing singular render/path keys represent
  the first successfully processed input image. Never draw boxes from one photo
  on another photo. If all images fail, these keys are `None` and the assessment
  is inconclusive.

### Fixture membership and observation validation

Perception proposes shapes across the whole image. A separate membership step
uses fixture anchors, shelf continuity, and spatial relationships to assign
`on_fixture`, `off_fixture`, or `uncertain` to each observation. Header/backlit
and box-stack anchors are useful evidence, not mandatory gates. An LLM may
suggest membership, with its evidence and source recorded. Expected SKU matches
alone must never establish membership or select among neighbouring fixtures.

Only `on_fixture` observations enter product-row registration and scoring.
Keep other proposals in the audit output. When anchors are absent or membership
is ambiguous, continue perception/identification and report unassessed facings;
do not silently select the fixture that best matches the planogram. The spike
must exercise adjacent fixtures, repeated SKUs, missing anchors, and partial
views; its outcome validates this proposed membership policy.

Identification responses contain separate `existing_identifications` and
`added_shapes` collections. Unknown IDs in the former are invalid references;
missing known IDs become uncertain. Additions have no authority to choose an
existing detection/facing ID: validate image/strip ownership, finite in-bounds
boxes, positive area, membership, and duplicates, then allocate pipeline-owned
IDs with `source="llm_added"`. Retain additions as proposals until these checks
pass. Normalize strip coordinates into their source image before deduplication.

Resolve duplicate observations within an image before cross-photo merging.
Concordant observations for the same registered facing retain all provenance;
prefer stronger evidence for presentation only. Incompatible admissible
identities become `conflict`, regardless of whether either source is CV.
Uncertain/unreadable evidence does not override a supported identification.
CV localization alone never wins an identity disagreement. Registration ties
remain uncertain; candidate identity cannot force a facing assignment.

### Internal Behavior

`PlanogramCompliance.run()` — shared orchestration only:

1. **Load** image(s) at full resolution, **untouched** — `open_image` always
   applies `_enhance_image` today, so the new cycle needs a load path without
   it; enhancement remains only for the legacy adapter path.
2. **Perceive** — async `type_handler` hook, offloading CPU work to the bounded
   process executor. Produces shapes grouped into rows/shelves and derived
   slots. Reads text in each shape with the OCR reader when available and
   records provisional fixture membership.
3. **Fallback check** — if usable on-fixture shapes are below the type's
   threshold, run the LLM detector over the full image through the vision
   adapter and mark `detection_source="llm"`. Distractor counts cannot suppress
   fallback. Apply the same membership validation to fallback observations.
4. **Identify** — the type declares a strategy: *full image* (one call: image +
   stage-1 JSON) or *strips* (one call per shelf/row, Set-of-Marks overlay,
   bounded concurrency via one shared semaphore). Structured input (the stage-1
   JSON) and structured output (Pydantic contract with confidence and
   evidence). Validate existing IDs and new proposals through the separate
   collections defined above; missing IDs become uncertain. Revalidate membership
   for additions and corrected observations. Optional closed-set verification
   pass for unresolved slots (expected SKU + distractors, evidence-gated).
5. **Compare** — load the slots definition, register observed rows to planogram
   shelves, decide a status per expected facing (merging observations across
   photos), compute strict/lenient credits, per-shelf and global scores, then
   **project onto `List[ComplianceResult]`** (one per shelf), following the
   unknown-state and aggregation rules below. Preserve field types while
   documenting the changed assessment semantics for migrated configurations.
6. **Render + assemble** — existing `render_evaluated_image`, existing keys,
   new keys.

`AbstractPlanogramType` — new concrete hooks with adapter defaults:

- *perceive* default: execute the full characterized legacy preparation and
  detection sequence (including the shared helpers listed above), wrap the
  `IdentifiedProduct`s as already-identified detections
  (`detection_source="legacy_llm"`).
- *identify* default: pass-through (legacy types identified during detection).
- *compare* default: call legacy `check_planogram_compliance`.
- The four legacy methods receive explicit unsupported-operation defaults
  instead of abstract requirements (`InkWall` implements none of them).
  Validate at construction that a type supplies either the complete legacy
  contract or all new hooks; reject incomplete types before a run starts.

`InkWall` — price-tag-anchored: bright-label shape profile → tag rows → slots
above tags (+ gap-filled and untagged bottom row) → strips per row → descriptor
identity (`family/xl/colors/pack`) → optional price compliance.

`ProductOnShelves` — product/shelf/backlit-anchored: shape profiles for product
bodies, boxes, fact tags and the backlit/poster; shelf edges give rows; full-
image identify; existing illumination check, text requirements, promotional
aliasing and `_assign_products_to_shelves` semantics carried into the compare
hook.

### Compliance, coverage, and evidence contract

Keep these three measures separate. A detector source does not establish SKU
identity, and model-reported confidence is not a calibrated probability.
`raw_confidence` is retained unchanged. The provisional evidence source weights
are `cv=1.0`, `llm_added=0.5`, and `llm=0.5`; report the resulting evidence-quality
measure separately. These weights do not multiply compliance credit or decide
identity conflicts. The descriptive benchmark can inform a later policy review,
but cannot calibrate confidence or validate these weights without reference data.

An admissible exact match needs validated fixture membership and registration,
plus product-discriminating evidence tied to the crop (for example readable
identifiers or required visible variant attributes). Neither a rectangle nor
an expected SKU offered in a verification prompt is sufficient. Unresolved
identity remains unresolved regardless of source or self-reported confidence.

Provisional per-facing credits, represented in a validated Pydantic policy:

| Facing status | Strict credit | Lenient credit | Assessment treatment |
|---|---|---|---|
| `match` with admissible exact identity evidence | 1.0 | 1.0 | Assessed |
| `misplaced` with supported identity | 0.0 | 0.5 | Assessed, placement violation |
| `variant_unresolved`, `inferred_present` | 0.0 | 0.5 | Partially supported; unresolved for coverage |
| `mismatch`, visibly `empty` | 0.0 | 0.0 | Assessed violation |
| `occupied_unassigned`, `conflict`, `not_assessed`, `not_visible` | 0.0 | 0.0 | Unresolved; never assert missing from absence of evidence |

- All expected facings remain in the denominator: per-shelf strict/lenient
  scores are summed credits divided by the number of expected facings. The
  lenient score is a policy credit measure, not an estimate of unseen compliance.
  Partial views cannot achieve 100% by excluding unseen positions.
- `coverage` is the fraction of expected facings with resolved assessments
  (`match`, `misplaced`, `mismatch`, or visibly `empty`). Report visible and
  occupied fractions separately; visibility is not assessment coverage.
  `definition_coverage` is the fraction with descriptors sufficient to resolve
  the required identity. An undescribed SKU stays unresolved unless an exact,
  independently readable identifier links it to the definition.
- `overall_compliance_score` is the mean of per-shelf lenient scores, preserving
  the current global aggregation rule; `strict_compliance_score` is the same
  mean for strict scores. Existing per-shelf rule weights remain local to each
  shelf. Do not silently switch to facing-weighted global aggregation.
  Report global coverage over facings, not as a mean of shelf percentages.
- Carry characterized text, brand, illumination, and promotional checks into
  shelf evaluation through the explicit rule bindings. Apply their existing
  shelf-local combination/penalty semantics once; specify the exact combination
  formula in the spec and pin it with characterization examples before coding.
  Required zone-only shelves retain their own checks; do not divide by zero or
  manufacture product facings for them.
- `assessment_status` is `complete` only when every expected facing and required
  non-product rule is assessed; otherwise it is `inconclusive`. It describes
  completeness independently of whether observed violations exist.
- `overall_compliant` is true only when the assessment is complete and all
  shelf thresholds and mandatory rules pass. Inconclusive means false in this
  legacy boolean, with the additive status/coverage explaining why. Zero
  coverage always yields false and inconclusive; supported partial identities
  may still earn lenient credit. Zero usable evidence yields score 0. Never
  interpret partial credit or an empty result list as a pass.
- Project unresolved shelves to `ComplianceStatus.NON_COMPLIANT`, with additive
  shelf assessment metadata explaining incompleteness. Only proven missing or
  misplaced products populate those legacy lists/statuses; do not label unseen
  products as missing. `ComplianceResult`'s existing enum remains unchanged.
- A full LLM-detector fallback can reach full compliance if the same evidence
  and completeness requirements are met. There is no source-imposed 50% cap.
  It retains lower evidence-quality weighting and `detection_source="llm"`.
- Legacy adapter types retain their characterized scoring. New coverage fields
  that their contract cannot establish are `None`, with
  `assessment_status="legacy_unmeasured"`; never fabricate full coverage.

### Perception spike and backend benchmark

The first task is a **two-engineering-day spike** (provisional time box). Use the
named ProductOnShelves photo plus available private photos covering partial
views and neighbouring fixtures. Keep photos and manual annotations git-ignored;
commit only aggregate results and synthetic regression cases. Record unavailable
conditions rather than claiming generalization from one photo.

Manually enumerate target-fixture objects/anchors and neighbouring distractors
on this small sample, with boxes and fixture membership. Match proposals to
annotations one-to-one (provisional IoU threshold 0.5); report precision and
recall separately for each shape profile and photo, plus off-fixture admissions.
Tag-anchored proposals must additionally demonstrate that their derived slots
cover the intended products; tag recall alone is not product-slot recall.

Provisional acceptance for making CV the default on the evaluated fixture
profile: at least 90% product-slot recall and 90% precision on each evaluable
photo, zero off-fixture observations admitted into scoring, and successful
synthetic cases for partial shelves, repeated SKUs, absent anchors, and ambiguous
membership. Report thresholds as engineering gates, not population accuracy
claims. Insufficient photos, untested membership conditions, or any failed gate
make the result inconclusive/failed and select the LLM-detector fallback. The
fallback must still obey membership and unknown-state rules; it does not bypass
them. The spec records accepted profiles and the spike outcome.

The separate **backend benchmark remains unlabelled** and has no automated
quality pass bar. It reports raw confidence distributions, evidence quality,
coverage, compliance, object counts, additions, errors, and per-stage duration.
Pin definition/image hashes, prompts/schemas, provider/model IDs, parameters,
package versions, concurrency, and retry limits. Report cold uncached runs
separately from cache hits and record repeated runs to expose variability.
The user chooses the backend from that report and inspection; do not call its
counts or self-reported confidence accuracy or recall. Verify requested model
availability at execution time and report unavailable backends explicitly.

### Backend selection and execution boundaries

Name the nullable config/DB field `llm_backend` (`provider:model`). Resolve an
explicit `llm` instance/string first; otherwise apply explicitly supplied
`llm_provider`/`llm_model` overrides to the configured backend, then use the
documented package default. Use an unset sentinel for omitted constructor
arguments so the existing `"google"` default cannot mask `llm_backend`.
If an explicit provider differs from the configured provider and no model is
supplied, use that provider's default, never the other provider's model ID.
An explicit model alone uses the configured provider (or package default).
Test the full precedence matrix and record the resolved backend in results.

Vision calls must honor the resolved model even where a client method has its
own default argument. Anthropic parity and its requested default-model update
remain in scope; a new method default must not override a caller's selection.
`no_memory` is accepted by both vision clients after parity work; the adapter
does not manage conversation history and does not drop unrelated kwargs silently.

Use a bounded, lifecycle-managed process executor for CPU-heavy CV/OCR/encoding,
with OCR initialized lazily inside workers. Await submissions from async hooks;
do not move async LLM calls into process workers. Use one shared bounded LLM
semaphore per run, bounded image/strip queues, finite retries/timeouts, and
cancellation cleanup. Blocking file I/O may use `asyncio.to_thread`. Specify
worker limits per gunicorn worker to avoid unbounded memory/process growth.

### Edge Cases & Error Handling

- **No shapes / too few shapes** → LLM detector fallback; never an empty silent
  result. If the fallback also fails, facings are `not_assessed`, coverage is
  low, and `errors` says why.
- **Partial view** (photo covers 3 of 6 shelves) → registration assigns visible
  on-fixture rows only when the alignment is supported and unambiguous;
  uncovered facings are `not_visible`, not `missing`. Ambiguous alignment
  remains unassessed.
- **Several admissible photo observations disagree** → `conflict` status for
  that facing, irrespective of source; unreadable evidence does not contradict
  an otherwise supported identity.
- **OCR unavailable** (extra not installed) → text read by LLM only; reported in
  the result.
- **LLM returns invalid structure** → one repair retry, then the affected
  strip's slots become uncertain; the rest of the run continues.
- **One strip/photo fails** → isolated; recorded in `errors`.
- **Slots JSON missing/invalid for a type that requires it** → fail fast at
  construction with a clear `ValueError` (slot sequence must be `1..n`, no
  duplicate facing ids, conflicting descriptors for one SKU rejected).
- **Undescribed SKUs** → listed, not fatal; a definition with *zero* described
  positions is rejected. (`planogram_page1.json` has only 2 of 102 positions
  described today.)
- **Provider differences** → adapter normalizes explicitly supported kwargs
  (`no_memory` is accepted by both clients after parity; Anthropic additionally
  supports `system_prompt`). A client with no `ask_to_image`
  fails fast with a clear error (`ClaudeAgentClient` raises
  `NotImplementedError`).
- **Blocking work** → CPU-bound OpenCV/OCR/PNG encoding uses the bounded process
  executor; file I/O may use `asyncio.to_thread`, with lifecycle and cancellation
  handled as described above.

---

## Capabilities

### New Capabilities
- `planogram-perception`: deterministic, profile-driven shape proposal, row/shelf structure and slot geometry from a full-resolution photo (no ROI gate).
- `planogram-ocr-reader`: optional, lazy local OCR of shape crops with LLM fallback.
- `planogram-vision-adapter`: provider-neutral `ask_to_image` + structured output, kwarg normalisation, response cache, repair retry.
- `planogram-llm-identification`: structured-input/structured-output identification with confidence, per-type call strategy (full image | strips), optional closed-set verification.
- `planogram-slots-definition`: JSON definition of shelves/slots/products/descriptors, loadable from `PlanogramConfig`.
- `planogram-config-migration`: offline candidate conversion, stable rule bindings, read-only DB preflight, and deployment/rollback runbook for migrated configurations.
- `planogram-fixture-membership`: auditable on/off/uncertain fixture assignments before registration, independent of expected SKU matching.
- `planogram-registration-scoring`: row→shelf registration, per-facing decision, multi-photo merge, strict/lenient, per-shelf and global scores, projection to `ComplianceResult`.
- `planogram-type-ink-wall`: new `InkWall` type.
- `planogram-shape-spike`: time-boxed measurement of profile-driven shape proposals on real ProductOnShelves photos; output fixes the shape profiles (first task).
- `planogram-descriptor-assistant`: LLM-assisted utility proposing per-position descriptors from the POG PDF, for human review (no catalog/SKU/price lookup).
- `planogram-config-backend`: `llm_backend` and `slots_definition` fields on `PlanogramConfig`, optional prompts, matching nullable DB columns + idempotent ALTER script, explicit constructor precedence.
- `planogram-llm-benchmark`: reproducible backend comparison (confidence, scoring, object counts, duration) that informs the default model; no ground truth.
- `anthropic-vision-parity`: `AnthropicClient.ask_to_image(no_memory=...)` and a new `AnthropicClient.detect_objects(...)` matching the Google client's contract.
- `planogram-provider-neutral-llm`: removal of hard-coded model literals and of the unconditional Google `roi_client`; provider/model resolved from the pipeline.
- `product-on-shelves-characterization-tests`: offline tests pinning today's `check_planogram_compliance`, fact-tag OCR/corroboration, shelf assignment and illumination behaviour.

### Modified Capabilities
- `planogram-compliance-modular` (FEAT-048): `PlanogramCompliance.run()` cycle replaced; `AbstractPlanogramType` contract extended with adapter defaults.
- `planogram-new-types`: `ProductOnShelves` migrated to the new cycle.
- `planogram-compliance-handler` (FEAT-047): existing request/response fields retained; additive assessment status, coverage, errors, and shelf assessment metadata. Multi-image upload remains out of scope.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot_pipelines/planogram/plan.py` | modifies | `run()` body replaced; signature widened to accept a list; result keys preserved + extended; `_PLANOGRAM_TYPES` gains `ink_wall` |
| `parrot_pipelines/planogram/types/abstract.py` | modifies | new concrete hooks with legacy-wrapping defaults; legacy methods no longer mandatory |
| `parrot_pipelines/planogram/types/product_on_shelves.py` | modifies | overrides new hooks; legacy LLM detection becomes the fallback |
| `parrot_pipelines/planogram/types/ink_wall.py` | new | price-tag anchored type |
| `parrot_pipelines/planogram/<perception subpackage>` | new | shapes, rows, slots, OCR, vision adapter, reference, registration, scoring |
| `parrot_pipelines/models.py` (`PlanogramConfig`) | extends | `slots_definition` (dict or path), `llm_backend`, versioned rule bindings; prompts become optional with type-specific validation |
| `parrot_pipelines/abstract.py` (`AbstractPipeline`) | modifies | remove the unconditional `GoogleGenAIClient` `roi_client`; auxiliary vision calls go through the pipeline's own client |
| `parrot_pipelines/planogram/types/*.py` (all six) | modifies | replace every hard-coded `model="gemini-3.5-flash"` / `self.pipeline.roi_client` use — touches the four unmigrated types too, minimally |
| `parrot_pipelines/handlers/planogram_compliance.py` | modifies | retains existing fields, adds assessment metadata; hydrates both new config columns, tolerates nullable prompts, resolves configured backend |
| `troc.planograms_configurations` (Postgres) | extends | nullable `slots_definition JSONB` and `llm_backend TEXT`; migrated active configurations require reviewed backfill |
| `packages/ai-parrot-client-anthropic/.../anthropic/client.py` | extends | `ask_to_image(no_memory=...)`; new `detect_objects(image, prompt, reference_images, output_dir) -> List[Dict[str, Any]]` |
| `parrot_pipelines/__init__.py` (`PIPELINE_REGISTRY`) | extends | add `InkWall` (3 existing types are already missing from it) |
| `packages/ai-parrot-pipelines/pyproject.toml` | extends | optional local OCR extra; declare directly used `numpy`, `pillow`, and comparison dependencies; OpenCV stays a hard dependency |
| `packages/ai-parrot/src/parrot/models/detections.py`, `compliance.py` | depends on / extends | backward-compatible shelf assessment metadata with defaults; keep existing compliance enum and existing fields |
| `examples/planogram/` | extends | benchmark script, ProductOnShelves `slots_definition` JSON, descriptor utility CLI; **`plancheck/` is left untouched** |
| `parrot_pipelines/table.sql` + new ALTER script | extends | `slots_definition JSONB NULL`, `llm_backend TEXT NULL`; prompts lose `NOT NULL`; idempotent ALTER for deployed DBs |
| planogram migration utility + deployment documentation | new | candidate conversion, explicit non-product rule bindings, preflight report, reviewed backfill and rollback sequence |
| `tests/pipelines/`, `packages/ai-parrot-pipelines/tests/` | extends | offline synthetic tests; characterization tests for `ProductOnShelves` first |

Existing handler fields and call shapes remain compatible; additional metadata
explains changed assessment semantics. Configuration migration is a deployment
prerequisite for migrated types. The adapter must preserve existing private
helper calls for legacy subclasses, verified by characterization tests; incomplete
contracts fail at construction. Audit changes to shared clients and
`AbstractPipeline` for consumers outside planogram as well.

---

## Code Context

### User-Provided Code

```python
# Source: user-provided (mirrors plan.py:37-43)
    _PLANOGRAM_TYPES = {
        "product_on_shelves": ProductOnShelves,
        "graphic_panel_display": GraphicPanelDisplay,
        "product_counter": ProductCounter,
        "endcap_no_shelves_promotional": EndcapNoShelvesPromotional,
        "endcap_backlit_multitier": EndcapBacklitMultitier,
    }
```

User-named files: `examples/planogram/planogram_check.py` (user wrote
`planogra_check.py`), `examples/planogram/planogram_page1.json` (user wrote
`planogram-page1.json`), `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/legacy.py`.

### Verified Codebase References

Paths below are relative to `packages/ai-parrot-pipelines/src/parrot_pipelines/`
unless they start with `packages/` or `examples/`.

#### Classes & Signatures

```python
# planogram/plan.py
class PlanogramCompliance(AbstractPipeline):                       # L24-485
    _PLANOGRAM_TYPES = {...}                                       # L37-43 (5 entries, no ink_wall)
    def __init__(self, planogram_config: PlanogramConfig, llm: Any = None,
                 llm_provider: str = "google", llm_model: Optional[str] = None,
                 **kwargs: Any): ...                               # L45-69; unknown type -> ValueError L65-68
    async def run(self, image: Union[str, Path, Image.Image],
                  output_dir: Optional[Union[str, Path]] = None,
                  image_id: Optional[str] = None, **kwargs) -> Dict[str, Any]: ...   # L71-370
    def render_evaluated_image(self, image, *, shelf_regions=None, detections=None,
                               identified_products=None, ...): ...  # L376-485
# run() return dict (L361-370): step3_compliance_results, compliance_results (same list),
#   overall_compliance_score, overall_compliant, identified_products, shelf_regions,
#   rendered_image, overlay_path
# run() calls private type helpers via hasattr: _generate_virtual_shelves,
#   _assign_products_to_shelves, _ocr_fact_tags, _corroborate_products_with_fact_tags;
#   and _refine_shelves_from_fact_tags when planogram_config["use_fact_tag_boundaries"].
# run() hard-codes model="gemini-3.5-flash" + no_memory=True in its promo OCR call.

# planogram/types/abstract.py
class AbstractPlanogramType(ABC):                                  # L30-478
    def __init__(self, pipeline: "PlanogramCompliance", config: "PlanogramConfig") -> None  # L48
    @abstractmethod
    async def compute_roi(self, img: Image.Image) -> Tuple[Optional[Tuple[int,int,int,int]],
        Optional[Any], Optional[Any], Optional[Any], List[Any]]    # L57-76
    @abstractmethod
    async def detect_objects_roi(self, img: Image.Image, roi: Any) -> List[Detection]   # L78-95
    @abstractmethod
    async def detect_objects(self, img: Image.Image, roi: Any, macro_objects: Any
        ) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]     # L97-113
    @abstractmethod
    def check_planogram_compliance(self, identified_products: List[IdentifiedProduct],
        planogram_description: Any) -> List[ComplianceResult]      # L115-129  (SYNC)
    async def _check_illumination(self, img, zone_bbox=None, roi=None,
        planogram_description=None) -> Optional[str]               # L151-249 (roi_client, gemini-3.5-flash)
    def _cluster_fact_tag_rows(self, fact_tags: List[Any], cluster_threshold: int = 50) -> List[int]  # L330-357
    def _refine_shelves_from_fact_tags(self, shelf_regions, identified_products) -> List[ShelfRegion] # L359-446
    def get_render_colors(self) -> Dict[str, Tuple[int,int,int]]   # L448-462
    def get_grid_strategy(self) -> "AbstractGridStrategy"          # L464-478 (NoGrid default)

# planogram/types/product_on_shelves.py
class ProductOnShelves(AbstractPlanogramType):                     # L35-1683
    async def compute_roi(self, img)                               # L58-82   (-> _find_poster L801-971)
    async def detect_objects(self, img, roi, macro_objects)        # L119-222 (grid vs _detect_legacy L262-382)
    def check_planogram_compliance(self, identified_products, planogram_description)  # L384-795 (~410 lines)
    def _generate_virtual_shelves(self, roi_bbox: DetectionBox, image_size, planogram) -> List[ShelfRegion]  # L1132-1217
    async def _ocr_fact_tags(self, identified_products, img, planogram_description, shelf_regions=None
        ) -> Dict[str, List[str]]                                  # L1219-1383
    def _corroborate_products_with_fact_tags(self, identified_products, fact_tag_shelf_map,
        planogram_description) -> None                             # L1385-1492 (in place)
    def _assign_products_to_shelves(self, products, shelves, use_y1_assignment: bool = False)  # L1494-1683
# LLM calls: ask_to_image(..., model="gemini-3.5-flash", no_memory=True, structured_output=Detections) L826;
#            ask_to_image(... max_tokens=128) L1358; self.pipeline.llm.detect_objects(...) L330.

# models.py
class PlanogramConfig(BaseModel):                                  # L29-108
    planogram_id: Optional[int] = None                             # L34
    config_name: str = "default_planogram_config"                  # L39
    planogram_type: str = "product_on_shelves"                     # L44-47 (doc mentions ink_wall, tv_wall)
    planogram_config: Dict[str, Any]                               # L50-52  REQUIRED
    roi_detection_prompt: str                                      # L55-57  REQUIRED
    object_identification_prompt: str                              # L60-62  REQUIRED
    reference_images: Dict[str, Union[str, Path, List[str], List[Path], Image.Image]]  # L65-71
    confidence_threshold: float = 0.25                             # L74
    detection_model: str = "yolo11l.pt"                            # L79
    endcap_geometry: EndcapGeometry                                # L84
    detection_grid: Optional[DetectionGridConfig] = None           # L90-96
    def get_planogram_description(self) -> PlanogramDescription    # L102-108

# abstract.py
class AbstractPipeline:                                            # L13-172
    def __init__(self, llm: Any = None, llm_provider: str = "google",
                 llm_model: Optional[str] = None, **kwargs: Any)   # L16-40
    # L40: self.roi_client = GoogleGenAIClient(model="gemini-3-flash-preview", temperature=0.0,
    #                                          max_retries=2, timeout=20)   UNCONDITIONAL
    def _get_llm(self, provider, model=None, **kwargs)             # L42-71 (LLMFactory.supported_clients)
    def open_image(self, image_path) -> Image.Image                # L73-87 (always _enhance_image)
    def _downscale_image(...)                                      # L146-158

# handlers/planogram_compliance.py
class PlanogramComplianceHandler(BaseView):                        # L28-362
    # L146-149: llm = GoogleGenAIClient(model=DEFAULT_LLM_MODEL);
    #           pipeline = PlanogramCompliance(planogram_config=_config, llm=llm)
    #           result = await pipeline.run(image=_image_path, output_dir=str(_tmp_dir))
    # reads: overlay_path L156-159, overall_compliant L162, overall_compliance_score L163,
    #        compliance_results L168
    # config: SELECT * FROM troc.planograms_configurations WHERE config_name=$1 AND is_active  L284-294
    #         _build_planogram_config L296-333 (reference images resolved against PLANOGRAM_FOLDER)

# packages/ai-parrot/src/parrot/models/detections.py
class DetectionBox(BaseModel)       # L37-60  x1,y1,x2,y2:int; confidence; class_id; class_name; area; label; ocr_text
class ShelfRegion(BaseModel)        # L62-68  shelf_id, bbox: DetectionBox, level, objects, is_background
class IdentifiedProduct(BaseModel)  # L71-206 product_type (req), product_model, brand, confidence,
                                    #         visual_features, shelf_location, position_on_shelf, ocr_text,
                                    #         detection_box, extra: Dict[str,str], out_of_place
class ShelfProduct(BaseModel)       # L246-253 name, product_type, quantity_range, position_preference, mandatory, visual_features
class ShelfConfig(BaseModel)        # L302-326
class PlanogramDescription(BaseModel)  # L364-407
# packages/ai-parrot/src/parrot/models/compliance.py
class ComplianceStatus(str, Enum)   # L9-14  compliant | non_compliant | missing | misplaced
class ComplianceResult(BaseModel)   # L32-52 shelf_level, expected_products, found_products, missing_products,
                                    #        unexpected_products, compliance_status, compliance_score, text_*...

# Provider clients — ask_to_image is NOT on AbstractClient
# packages/ai-parrot-client-google/src/parrot/clients/google/client.py:4999
async def ask_to_image(self, prompt: str, image: Union[Path, bytes], reference_images=None,
    model=None, max_tokens=None, temperature=None, structured_output=None,
    count_objects: bool = False, history=None, no_memory: bool = False) -> AIMessage
# packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py:1307
async def ask_to_image(self, prompt: str, image: Union[Path, bytes, Image.Image], reference_images=None,
    model: Union[ClaudeModel, str] = ClaudeModel.SONNET_4, max_tokens=None, temperature=None,
    structured_output=None, count_objects: bool = False, history=None,
    system_prompt: Optional[str] = None, context_1m: bool = False) -> AIMessage
# packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py:1234   (GOOGLE ONLY)
async def detect_objects(self, image, prompt: str, reference_images=None, output_dir=None) -> List[Dict[str, Any]]
```

Reference engine (`examples/planogram/plancheck/`, algorithmic reference only):

```python
# detection.py
_THRESHOLDS = (130, 150, 170, 190, 210, 230)                                   # L19
def find_candidates(image: np.ndarray, min_width: float = 0.025, max_width: float = 0.09) -> list[dict[str, Any]]  # L22
    # filters: 0.025W<bw<0.09W, 0.014H<bh<0.06H, 1.65<aspect<4.4, rectangularity>=0.75, gray std>=25,
    #          dedup overlap/min(area)>0.5.  THRESH_BINARY only — no morphology / edges.
def group_rows(items, image_width: int, min_row_labels: int = 4, max_slope: float = 0.12) -> tuple[list[dict], list[int]]  # L68
def detect_tags(image: np.ndarray, image_id: str, *, work_width: int = 2048,
                roi: tuple[float,float,float,float] | None = None) -> tuple[list[TagRow], list[Box]]  # L136
# grid.py
def build_slots(rows: list[TagRow], image_size: tuple[int, int]) -> list[Slot]              # L78  (tag sits BELOW product)
def strip_box(slots, image_size, pad: float = 0.04) -> Box                                  # L185
def to_strip_norm(box: Box, strip: Box) -> list[int]                                        # L229 ([ymin,xmin,ymax,xmax] 0-1000)
# prices.py
class TagOcr: __init__() L77 (import probe), read(crop: np.ndarray) -> str L87 (lazy RapidOCR(); result.txts)
def parse_price(text: str) -> PriceReading                                                  # L36
async def read_prices(image, slots, ocr, backend, *, semaphore=None, errors=None) -> dict[str, PriceReading]  # L207
# vision.py
class VisionBackend: __init__(llm: str, *, cache_dir: Path, base_url=None, api_key=None,
                              max_tokens: int = 8192, client=None)                          # L105
    async def ask(self, prompt: str, images: Sequence[bytes], schema: type[T], *, stage: str,
                  prompt_version: str) -> T                                                 # L163
    # L131: LLMFactory.create(llm, model_args={"temperature":0.0,"max_tokens":...}, **kwargs)
    # lanes L213-228: client.image_understanding(...)  else  client.ask_to_image(prompt, image=images[0],
    #                 reference_images=..., structured_output=schema, temperature=0.0, max_tokens=...)
def cache_key(llm, base_url, max_tokens, stage, prompt_version, prompt, schema, images) -> str   # L45
# identify.py
SUBSTRIP_MAX_SLOTS = 8; CLOUD_SPLIT_ABOVE = 20                                              # L29-30
def render_strip(image, slots, *, marks: bool = True) -> tuple[bytes, Box]                  # L73 (Set-of-Marks)
async def identify_rows(image, slots, backend, catalog, semaphore, *, marks=True
    ) -> tuple[list[SlotObservation], list[str]]                                            # L252
# verify.py
def pick_distractors(facing, planogram, catalog, n: int = 3) -> list[str]                   # L27
async def verify_rows(image, observations, planogram, catalog, backend, semaphore) -> list[str]  # L172
# reference.py
def load_planogram(path: Path) -> PlanogramRef                                              # L30
DESCRIPTOR_FIELDS = ("display_name","family","xl","colors","pack","identifiers","aliases","price")  # L96
def load_descriptors(path: Path, planogram: PlanogramRef) -> tuple[Catalog, list[str], dict[str, Decimal]]  # L142
def resolve_identity(reading: SlotReading, catalog: Catalog) -> tuple[str | None, list[str], Resolution]    # L255
# registration.py
def align_row(row_obs, facings, catalog, pitch: float) -> tuple[float, dict[str, str], int] # L93  (NW-style DP)
def register_image(image_id, observations, planogram, catalog, pitches) -> ImageRegistration  # L197 (increasing shelves only)
# scoring.py
def merge_positions(planogram, observations, catalog, weights, prices) -> list[PositionResult]  # L251 (multi-photo merge)
def shelf_scores(positions) -> list[ShelfScore]                                             # L356
def summarize(positions, shelf_scores_, catalog, prices) -> ComplianceSummary               # L473
# pipeline.py
async def run_check(settings: Settings, *, backend_factory=None) -> ComplianceReport        # L159
```

`planogram_page1.json` schema (git-ignored; structure only): top level
`{"planogram": {...}, "shelves": [...]}`. `planogram` meta: `product_count`
(102), `physical_facing_count` (104), `source`, `shelves` (6), `segments` (2),
`planogram` ("Ink"), `fixture`, `option`. Each shelf: `shelf`, `shelf_number`,
`product_count`, `facing_count`, `products` (dict keyed `"pos <shelf>:<n>"`).
Each position has 20 keys: `position, segment, segment_number, slot,
segment_slot, product, brand, shelf, facings, confidence, read_method, notes` +
descriptors `display_name, family, xl, colors, pack, identifiers, aliases,
price`. **Only 2 of 102 positions are described today.**

Provider-neutrality worklist (verified by literal count, 2026-09-18) —
occurrences of `model="gemini…"`, `roi_client`, `GoogleGenAIClient`,
`llm.detect_objects` or `no_memory` under `parrot_pipelines/`:

| File | Count |
|---|---|
| `planogram/types/endcap_backlit_multitier.py` | 18 |
| `planogram/types/graphic_panel_display.py` | 12 |
| `planogram/types/product_on_shelves.py` | 7 |
| `planogram/types/product_counter.py` | 6 |
| `planogram/types/endcap_no_shelves_promotional.py` | 6 |
| `planogram/types/abstract.py` | 3 |
| `planogram/plan.py` | 3 |
| `abstract.py` | 2 |
| `handlers/planogram_compliance.py` | 2 (`GoogleGenAIClient(model=DEFAULT_LLM_MODEL)` L146; `DEFAULT_LLM_MODEL` from `parrot.conf` L16) |
| `planogram/grid/detector.py` | 1 (`self.llm.detect_objects`, L130) |

So removing the hard-coding touches **all six types**, not only the two being
migrated — 60 call sites in 10 files.

```sql
-- packages/ai-parrot-pipelines/src/parrot_pipelines/table.sql  (shipped as package-data "*.sql")
-- CREATE TABLE troc.planograms_configurations (               -- L3
--     planogram_config JSONB NOT NULL,                        -- L13
--     roi_detection_prompt TEXT NOT NULL,                     -- L16
--     object_identification_prompt TEXT NOT NULL,             -- L17
--     reference_images JSONB DEFAULT '{}',                    -- L20
-- GIN index on planogram_config                               -- L56
-- There is NO planogram_type-independent slots column today.
```

```python
# packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/models.py
class ClaudeModel:  SONNET_5 = "claude-sonnet-5"   # L15   (exists)
                    SONNET_4 = "claude-sonnet-4-20250514"   # L33
# .../anthropic/client.py: ask_to_image default model = ClaudeModel.SONNET_4  (L1312) — stale default
```

#### Reference photo for ProductOnShelves (spike input)

`examples/planogram/photo_2026-09-18_20-36-30.jpg` — git-ignored, 1280×955,
viewed 2026-09-18. An Epson EcoTank endcap:

- **Backlit header**: large luminous panel, "EPSON — Goodbye Cartridges. Hello
  Savings.", person + printer artwork. The largest, brightest rectangle in frame.
- **Display shelf**: 3 white printers side by side on a white riser — low
  contrast against the riser (hard case for threshold/contour proposals).
- **3 electronic price tags** (white with a red band) on the riser's front edge,
  one under each printer — same tag-below-product anchoring as the ink wall.
- **Box stack below**: 6 product boxes in a 3-column × 2-row grid (white and
  blue Epson boxes, strong rectangular edges), with small tags at the base.
- **Distractors**: the left aisle shows other printers with price tags and the
  right aisle shows unrelated products — all *outside* the fixture, all
  detectable shapes.

Implications for the spike: three shape profiles at very different scales
(backlit ≫ boxes > printers ≫ tags); tags here are not plain white; printers need
an edge/structure cue, not a brightness threshold; and fixture scoping must be
solved without re-introducing a hard ROI gate.

#### Verified Imports
```python
from parrot_pipelines.planogram import PlanogramCompliance, AbstractPlanogramType   # planogram/__init__.py L4-22 (lazy __getattr__)
from parrot_pipelines.planogram.types import (AbstractPlanogramType, ProductOnShelves, GraphicPanelDisplay,
    ProductCounter, EndcapNoShelvesPromotional, EndcapBacklitMultitier)             # types/__init__.py L2-16
from parrot_pipelines.models import PlanogramConfig, EndcapGeometry
from parrot_pipelines.planogram.grid import (AbstractGridStrategy, CellResultMerger, DetectionGridConfig,
    GridCell, GridDetector, GridType, HorizontalBands, NoGrid, get_strategy)
from parrot.models.detections import Detection, Detections, DetectionBox, IdentifiedProduct, ShelfRegion
from parrot.models.compliance import ComplianceResult, ComplianceStatus
from parrot.clients.factory import LLMFactory                                       # used at plancheck/vision.py:131
from parrot.pipelines.planogram.plan import PlanogramCompliance                     # back-compat shim (core)
```

#### Key Attributes & Constants
- `PlanogramCompliance._type_handler` → resolved composable (plan.py:69)
- `PlanogramCompliance.reference_images`, `.left_margin_ratio`, `.right_margin_ratio` (plan.py:56-61)
- `AbstractPipeline.roi_client` → `GoogleGenAIClient` always (abstract.py:40)
- `AbstractPlanogramType.pipeline / .config / .logger` (types/abstract.py:53-55)
- `PIPELINE_REGISTRY` (parrot_pipelines/__init__.py:4-15) — lacks `ProductCounter`, `EndcapNoShelvesPromotional`, `EndcapBacklitMultitier`
- `packages/ai-parrot-pipelines/pyproject.toml` deps: `ai-parrot>=1.0.4`, `opencv-python-headless>=4.8`, `pytesseract>=0.3.13`
- Installed versions observed: rapidocr 3.9.2, onnxruntime 1.30.0, rapidfuzz 3.11.0, opencv-python 4.10.0.84, numpy 2.4.6
- `plancheck` default LLM string: `google:gemini-3.8-flash` (models.py `Settings.llm`)
- Existing tests: `packages/ai-parrot-pipelines/tests/test_planogram_types.py`, `test_endcap_no_shelves_promotional.py`; `tests/pipelines/test_*grid*`, `test_product_counter.py`, `test_endcap_no_shelves.py`, `test_config_extensions.py`; `packages/ai-parrot/tests/handlers/test_planogram_compliance.py`; `examples/planogram/tests/` (15 offline files, `conftest.FakeBackend` L187)

### Does NOT Exist (Anti-Hallucination)
- ~~`InkWall` / `ink_wall` class or module~~ — only docstrings and a config string; `planogram_type="ink_wall"` raises `ValueError` today.
- ~~`InkWallAnalysis`~~ — referenced in a docstring (`parrot/interfaces/images/plugins/analisys.py:65`), never defined.
- ~~`AbstractClient.ask_to_image`~~ — not declared in `parrot/clients/base.py`; per-provider convention only.
- ~~`no_memory` on Anthropic `ask_to_image`~~ — Google-only kwarg **today; this feature adds it**.
- ~~`detect_objects` on Anthropic / OpenAI clients~~ — Google-only (`analysis.py:1234`) **today; this feature adds the Anthropic one** (OpenAI stays out of scope).
- ~~A slots/facings column on `troc.planograms_configurations`~~ — none; this feature adds it.
- ~~`ClaudeAgentClient.ask_to_image`~~ — raises `NotImplementedError`.
- ~~`[project.optional-dependencies]` in `ai-parrot-pipelines/pyproject.toml`~~ — section absent; no extras exist.
- ~~`rapidocr` in any workspace `pyproject.toml`~~ — installed in the venv, declared nowhere.
- ~~`numpy`, `pillow`, `rapidfuzz`, `onnxruntime` declared by `ai-parrot-pipelines`~~ — transitive only.
- ~~A `PlanogramConfig` field that loads a JSON file~~ — none; config comes from a DB row.
- ~~Generic shape detection (products, boxes, posters, backlits) in `examples/planogram/`~~ — `plancheck/detection.py` detects **only bright landscape price labels**; no Canny, adaptive threshold, morphology or Hough anywhere in `plancheck`, `inkcheck` or `white_label_detector`.
- ~~Shelf-edge detection~~ — rows come only from aligned price tags.
- ~~A separate catalog file / `load_catalog()` / `Settings.catalog`~~ — removed in `f39b69c026`; descriptors live in the planogram JSON.
- ~~Real linear share~~ — `BrandShare.linear_share` is a stub equal to `observed_share` (`scoring.py:445`).
- ~~Non-monotone row→shelf registration~~ — `register_image` only tries strictly increasing shelf combinations.
- ~~Tests for `ProductOnShelves.check_planogram_compliance`, `_ocr_fact_tags`, `_corroborate_products_with_fact_tags`, `_check_illumination`~~ — none.
- ~~Any planogram tool in `ai-parrot-tools`~~ — zero references.
- ~~Packaging for `plancheck`~~ — bare directory on `sys.path`, not importable from the package.
- ~~Labelled ground truth for the example photos~~ — none (README: "No accuracy claim").

---

## Parallelism Assessment

- **Internal parallelism**: moderate. After the initial perception spike, a
  contract task fixes the shared
  contracts (perception/identification/position models + the new
  `AbstractPlanogramType` hooks), these are independent: (a) shape
  proposer + rows + slots, (b) OCR reader, (c) vision adapter, (d) slots
  definition loader + `PlanogramConfig` field, (e) registration + scoring.
  `InkWall`, the `ProductOnShelves` migration, the `run()` rewrite and the
  benchmark are sequential on top of those. `ProductOnShelves`
  characterization tests can start immediately, in parallel with everything —
  and so can the Anthropic client parity work (`no_memory`, `detect_objects`),
  which lives in a different distribution (`ai-parrot-client-anthropic`) and
  shares no file with the pipeline. The hard-coding removal (60 call sites, 10
  files) should land **after** the characterization tests and **before** the
  `ProductOnShelves` migration, as its own mechanical task.
- **Cross-feature independence**: no in-flight feature touches
  `parrot_pipelines/planogram/` (open indexes: FEAT-481, 536, 539, 540, 569,
  572 — all other subsystems). Shared-file risk is limited to
  `packages/ai-parrot-pipelines/pyproject.toml` and, if extended, core
  `parrot/models/detections.py`.
- **Recommended isolation**: `per-spec`.
- **Rationale**: almost every task edits `plan.py`, `types/abstract.py` or the
  shared models; the contract must stabilise before fan-out, and the
  `sdd-worker` per-task sub-worktrees already give task-level parallelism for
  the independent modules inside one feature worktree.

---

## Consolidated Decisions and Remaining Validation

Checked entries record the current design, including the authorized review
consolidation. Earlier discovery rounds are superseded where their wording
conflicts with the contracts above. Provisional numerical defaults still need
the spike/spec validation listed at the end.

- [x] Feature or hotfix, base branch — *Owner: Jesus Lara*: feature, `dev`.
- [x] Fate of the pure-LLM ROI cycle — *Owner: Jesus Lara*: total replacement; public signature kept.
- [x] Types in scope — *Owner: Jesus Lara*: `InkWall` + `ProductOnShelves`; the other four later.
- [x] Unmigrated types — *Owner: Jesus Lara*: adapter defaults in `AbstractPlanogramType` wrapping the legacy methods.
- [x] How `plancheck` code is reused — *Owner: Jesus Lara*: re-written, inspired by it; not moved or imported.
- [x] Single or multiple images — *Owner: Jesus Lara*: one or several, merged per facing.
- [x] LLM call granularity — *Owner: Jesus Lara*: declared by the type (full image | strips).
- [x] CV finds too few shapes — *Owner: Jesus Lara*: fall back to an LLM detector; mark `detection_source`.
- [x] Where the slot definition lives — *Owner: Jesus Lara*: `PlanogramConfig` names the type; a JSON defines shelves/slots/products; a ProductOnShelves JSON must be created.
- [x] Output contract — *Owner: Jesus Lara*: same keys + new additive keys.
- [x] Dependencies: local OCR is an optional extra with lazy imports; OpenCV remains a hard dependency. Declare directly used dependencies explicitly.
- [x] Model benchmark — *Owner: Jesus Lara*: unlabelled descriptive deliverable; the user selects the default. It makes no accuracy or recall claim.
- [x] **How does the slots JSON reach a DB-driven config?** — *Owner: Jesus Lara*: both sources are valid and equivalent — a **new JSONB column** on `troc.planograms_configurations` (DB-driven configs) or a JSON file (scripts/examples). `PlanogramConfig` names the type; the slots JSON gives the fine granularity (shelves, slots, products). `table.sql` needs the new nullable column.
- [x] **Name and nullability of the new column / field** — *Owner: Jesus Lara*: `slots_definition` — `JSONB NULL` on `troc.planograms_configurations`, same name on `PlanogramConfig`. The feature ships an **idempotent ALTER script** (`ADD COLUMN IF NOT EXISTS slots_definition`, `ALTER COLUMN … DROP NOT NULL` on both prompts) next to the updated `table.sql`; the user applies it to deployed databases.
- [x] **Generic shape detection is unproven**: the first task is the perception spike with a manually checked sample, per-profile precision/recall, and fixture-membership tests. Failed or inconclusive gates select the LLM-detector fallback. The hook remains ready for another detector (Option C).
- [x] **May the LLM add shapes the CV missed?**: yes, through validated `added_shapes` with pipeline-owned IDs and `source="llm_added"`. Keep raw confidence intact and lower only the separate evidence-quality weight; no detector-source cap on compliance.
- [x] **Hard-coded models / Google client** — *Owner: Jesus Lara*: eliminate them; either client must be able to drive the whole run. 60 call sites in 10 files (see Code Context worklist).
- [x] **Client homologation** — *Owner: Jesus Lara*: in scope of this spec — add `no_memory` to `AnthropicClient.ask_to_image` and add `detect_objects` to `AnthropicClient`, matching the Google client.
- [x] **`ProductOnShelves` tests** — *Owner: Jesus Lara*: must be built in this feature.
- [x] **Benchmark ground truth** — *Owner: Jesus Lara*: none. The benchmark reports confidence, scoring, number of objects detected and duration per backend; the user judges from those numbers. No automated pass bar.
- [x] **Which model ids does the benchmark compare?** — *Owner: Jesus Lara*: `gemini-3.5-flash` vs `claude-sonnet-5` (`ClaudeModel.SONNET_5`).
- [x] **Where does the default provider/model live once literals are gone?** — *Owner: Jesus Lara*: a field on `PlanogramConfig` (provider + model), so each planogram can pin its backend; explicit `llm=` / `llm_provider=` / `llm_model=` passed to `PlanogramCompliance` still win.
- [x] **`AnthropicClient.ask_to_image` default model** — *Owner: Jesus Lara*: bump to `ClaudeModel.SONNET_5`, and use the same default for the new `detect_objects`.
- [x] **`planogram_page1.json` has 2/102 positions described**: the descriptor utility proposes `display_name/family/xl/colors/pack` and readable identifiers/aliases from the POG PDF only, with page evidence for human review. No catalog lookup or generated price. Partial definitions remain legal, with definition coverage and unresolved identities explicit.
- [x] **ProductOnShelves slots JSON: replace or complement?** — *Owner: Jesus Lara*: `slots_definition` **replaces** `planogram_config.shelves[].products` as the expected-products reference for migrated types. Non-product expectations — backlit/poster, illumination, `text_requirements`, `compliance_threshold`, per-shelf weights, `advertisement_endcap` — **stay in `planogram_config`**.
- [x] **`roi_detection_prompt` / `object_identification_prompt` required?** — *Owner: Jesus Lara*: no longer mandatory — OpenCV does object detection (and potentially the ROI) zero-shot. They become optional on `PlanogramConfig`; `table.sql` has them `TEXT NOT NULL` (L16-17) and must relax too. Unmigrated types that still need them must fail with a clear message when absent.
- [x] **`AbstractPipeline.roi_client` is always Google** — *Owner: Jesus Lara*: remove the hard-coding; auxiliary calls (`_check_illumination`, fact-tag OCR) go through the pipeline's own client.
- [x] **Multi-image API shape** — *Owner: Jesus Lara*: `run(image=…)` accepts one image or a list (backwards compatible). The handler keeps single-file upload in this feature; multi-upload is a later feature.
- [x] **Registration assumes strictly increasing shelves** — *Owner: Jesus Lara*: header/backlit/poster are **zones detected apart** (large luminous shape) and do not take part in row→shelf alignment; product rows register in increasing order.
- [x] **What happens to `examples/planogram/plancheck/`** — *Owner: Jesus Lara*: stays as it is — an independent tool and a live reference for comparing results. Not moved, not deleted, not rewired.
- [x] **`open_image` always enhances brightness/contrast** — *Owner: Jesus Lara*: perception, OCR and the crops sent to the LLM use the **untouched full-resolution image**; enhancement is kept only for the legacy adapter path.
- [x] **Which real ProductOnShelves photo feeds the spike and the first `slots_definition`?** — *Owner: Jesus Lara*: `examples/planogram/photo_2026-09-18_20-36-30.jpg` (git-ignored, 1280×955). See "Reference photo" under Code Context for what it contains.
- [x] **Which catalog backs the SKU lookup of the descriptor utility?** — *Owner: Jesus Lara*: none — **discarded**. There is no data yet to back SKU or price lookups. The descriptor utility works from the **POG PDF only**; `price` is never proposed by it and stays an optional, manually supplied field.
- [x] **Backend field and precedence**: nullable `llm_backend` (`provider:model`) on config and DB, added by the same ALTER script. Explicit `llm` wins, then explicit provider/model overrides, then config, then documented defaults. Omitted arguments use a sentinel; changing provider cannot inherit another provider's model.
- [x] **Evidence weight of `llm_added` shapes**: provisional `0.5`, configurable, applied only to evidence quality. Raw confidence and compliance remain separate. This supersedes the previous strict-zero/lenient-50% fallback rule.
- [x] **Fixture scoping without an ROI gate**: full-image proposals followed by evidence-based on/off/uncertain membership before registration. Expected SKU agreement cannot establish membership. Missing anchors do not stop perception; ambiguous membership prevents a conclusive assessment.
- [x] **Configuration compatibility**: reviewed ProductOnShelves slots backfill and non-product rule bindings are required before deployment. Ship candidate conversion and read-only preflight; nullable schema additions alone are insufficient.
- [x] **Unknown states and public scores**: retain all expected facings in score denominators, report coverage separately, preserve the unweighted shelf mean, and require complete assessment before `overall_compliant=True`. Add assessment metadata to handler responses; keep the existing enum.
- [x] **Observation conflicts**: merge agreeing evidence with provenance; incompatible admissible identities become `conflict`, independent of source. CV localization does not override identity evidence.
- [x] **CPU work**: bounded process executor for CV/OCR/encoding; thread offload is limited to blocking I/O. Async hooks and LLM calls remain in the event loop.
- [ ] **Spike validation**: confirm or revise the provisional two-day time box, 0.5 IoU, and 90% precision/recall gates using the available private sample. Record tested conditions, failures, and whether membership exclusion is reliable. — *Owner: implementation spike / Jesus Lara*
- [ ] **Scoring examples for the spec**: pin shelf-local non-product combination formulas and status projection with characterization fixtures; include zero evidence, partial identity, incomplete definitions, conflicting photos, zone-only shelves, and full LLM fallback. — *Owner: specification task*
- [ ] **Photo resolution.** The reference photo is 1280×955 (messenger-compressed); price-tag text is a few pixels tall. Is this the resolution production will receive, or will originals be available? OCR expectations for ProductOnShelves depend on it. — *Owner: Jesus Lara*
