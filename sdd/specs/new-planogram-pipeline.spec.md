---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: New Planogram Compliance Pipeline (perceive → identify → compare)

**Feature ID**: FEAT-574
**Date**: 2026-09-18
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: ai-parrot-pipelines 1.1.0 (ai-parrot-client-anthropic: next patch)

**Source**: `sdd/proposals/new-planogram-pipeline.brainstorm.md` (Recommended Option **A**)
**Related**: FEAT-565 `new-planogram-compliance-algo` (merged — the standalone
`examples/planogram/plancheck/` reference engine), FEAT-048
`planogram-compliance-modular` (`AbstractPlanogramType`), FEAT-047
`planogram-compliance-handler`.

---

## 1. Motivation & Business Requirements

### Problem Statement

`parrot_pipelines.planogram.PlanogramCompliance` is a **pure-LLM** pipeline. Its
cycle is `compute_roi → detect_objects → check_planogram_compliance`, delegated
to an `AbstractPlanogramType` composable. Three problems:

1. **ROI is a single point of failure.** Everything downstream is scoped to the
   ROI the LLM finds in step 1. `plan.py:98-102` wraps `compute_roi` in a bare
   `try/except` that only logs — when the ROI is not found, the rest of the run
   works on nothing and the result is meaningless.
2. **Detection is done by the LLM**, which is the thing LLMs are worst at:
   counting and localising ~100 small similar objects. Bounding boxes drift,
   facings are merged or invented, and there is no deterministic evidence to
   audit.
3. **No type can express a dense wall.** `planogram_type="ink_wall"` is accepted
   by `PlanogramConfig` but raises `ValueError` in `PlanogramCompliance.__init__`
   (`plan.py:66-68`) — there is no `InkWall` class. The reference for such a wall
   (102 products, 104 facings, 6 shelves) does not fit `PlanogramDescription`'s
   `shelves → products(name, quantity_range)` shape.

FEAT-565 proved a different cycle in `examples/planogram/plancheck/`:
deterministic OpenCV detection of price tags + RapidOCR, then an LLM that only
*identifies* what is inside regions it is handed, then a deterministic
comparison against the planogram. That engine is a standalone example, ink-wall
specific, and not reachable from the production handler.

**Who is affected**: field-compliance users of `POST /api/v1/planogram/compliance`
(`PlanogramComplianceHandler`), and developers adding planogram types.

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

### Goals

- **G1 — One cycle.** perceive → identify → compare becomes the *only* cycle of
  `PlanogramCompliance.run()`. The ROI-first orchestration in `plan.py` is
  removed, not kept behind a flag.
- **G2 — Public API compatibility.** `PlanogramCompliance(planogram_config=..., llm=...)`
  and `await pipeline.run(image, output_dir=..., image_id=...)` keep working. All
  **eight** existing result keys are preserved (`step3_compliance_results`,
  `compliance_results`, `overall_compliance_score`, `overall_compliant`,
  `identified_products`, `shelf_regions`, `rendered_image`, `overlay_path`); new
  keys are additive. Preserving keys does **not** promise identical scores for
  migrated types.
- **G3 — Unmigrated types keep working through an adapter in the base class.**
  `GraphicPanelDisplay`, `ProductCounter`, `EndcapNoShelvesPromotional`,
  `EndcapBacklitMultitier` retain their algorithms and their characterized
  scoring; the base `AbstractPlanogramType` provides default implementations of
  the new hooks that wrap the complete legacy orchestration.
- **G4 — Two migrated archetypes.** `InkWall` (new; price-tag anchored) and
  `ProductOnShelves` (existing; product/shelf/backlit anchored).
- **G5 — Re-write, inspired by `plancheck`.** Algorithms are the reference; the
  code is re-implemented against the package's models and conventions.
  `plancheck` is not imported, moved, vendored, deleted or rewired.
- **G6 — LLM call granularity declared by the type**: full image in one call, or
  per-row strips in parallel.
- **G7 — CV failure degrades to an LLM detector.** When usable on-fixture shapes
  fall under a per-type threshold, the LLM proposes boxes on the full image and
  the cycle continues; the result records `detection_source="llm"`.
- **G8 — One image or several.** `run(image=…)` accepts a single image or a
  list; several photos of the same fixture are merged per facing. The handler
  stays single-file in this feature.
- **G9 — Slots definition.** `PlanogramConfig` says *what type* the planogram
  is; a separate `slots_definition` (dict, or a path to a JSON file — a JSONB
  column and a JSON file are the same thing to `PlanogramConfig`) defines
  shelves, slots, products and descriptors. It **replaces**
  `planogram_config.shelves[].products` as the expected-products reference for
  migrated types; non-product expectations (backlit/poster, illumination,
  `text_requirements`, `compliance_threshold`, per-shelf weights,
  `advertisement_endcap`) **stay in `planogram_config`** and are tied to the
  definition through explicit, validated rule bindings.
- **G10 — Prompts become optional.** `roi_detection_prompt` and
  `object_identification_prompt` stay accepted (the adapter path uses them) but
  are no longer mandatory on `PlanogramConfig` nor `NOT NULL` in `table.sql`.
  Legacy types that need them fail at construction with a clear message.
- **G11 — Provider-neutral.** No hard-coded model literal and no unconditional
  `GoogleGenAIClient` anywhere under `parrot_pipelines/`; either a Google or an
  Anthropic client can drive a whole run. Client homologation is in scope:
  `AnthropicClient.ask_to_image(no_memory=...)`, a new
  `AnthropicClient.detect_objects(...)`, and the Anthropic vision default bumped
  to `ClaudeModel.SONNET_5`.
- **G12 — Backend is a config field.** One nullable `llm_backend`
  (`"provider:model"`, the `LLMFactory.create` format) on `PlanogramConfig` and
  on `troc.planograms_configurations`; explicit constructor arguments still win.
- **G13 — Fixture membership without an ROI gate.** Full-image proposals, then
  an evidence-based `on_fixture` / `off_fixture` / `uncertain` assignment before
  registration. Expected-SKU agreement never establishes membership.
- **G14 — Honest scoring.** Compliance, coverage and evidence quality are three
  separate measures; unknown is never reported as missing; an incomplete
  assessment is never a pass.
- **G15 — Configuration migration as a deliverable**: candidate conversion,
  rule bindings, read-only preflight, idempotent ALTER script and runbook.
- **G16 — Deliverable tooling**: perception spike (first task), unlabelled
  backend benchmark (`gemini-3.5-flash` vs `claude-sonnet-5`), LLM-assisted
  descriptor utility (POG PDF only, never proposes `price`).
- **G17 — Tests.** Characterization tests for today's untested
  `ProductOnShelves` compliance / fact-tag / illumination logic and for the full
  legacy orchestration, built **before** migrating; all new tests run offline on
  synthetic fixtures with a fake LLM backend.

### Non-Goals (explicitly out of scope)

- Migrating `GraphicPanelDisplay`, `ProductCounter`,
  `EndcapNoShelvesPromotional`, `EndcapBacklitMultitier` to the CV path — later
  features. They receive only the provider-neutral call-site updates.
- Multi-file upload in `PlanogramComplianceHandler` — a later feature.
- `detect_objects` / parity work for the OpenAI client.
- Catalog / SKU / price lookup in the descriptor utility — discarded, no data to
  back it; `price` stays an optional, manually supplied field.
- Labelled ground truth or any accuracy/recall claim from the backend benchmark.
- An open-vocabulary detector (OWLv2 / Grounding-DINO / YOLO-World) — rejected
  for this feature in brainstorm (Option C); the perception hook keeps it
  swappable later. Promoting `plancheck` as the engine (Option B) and
  LLM-proposes/CV-verifies (Option D) were also rejected — see
  `sdd/proposals/new-planogram-pipeline.brainstorm.md`.
- Moving OpenCV into an extra — it remains a hard dependency.
- Touching `examples/planogram/plancheck/` or `planogram/legacy.py`'s algorithm
  (the latter only loses its `roi_client` dependency, see Module 6).
- Applying database changes. The feature ships scripts and the runbook; the user
  applies them.

---

## 2. Architectural Design

### Overview

`PlanogramCompliance.run()` becomes a fixed three-stage **template method** —
**perceive → identify → compare**, plus shared load / fallback / render /
assemble. Each stage calls an async hook on the type handler.
`AbstractPlanogramType` gains the hooks as **concrete methods whose default
implementation wraps the legacy contract**, so the four unmigrated types run
unchanged through the new `run()`. `InkWall` and `ProductOnShelves` override the
hooks and compose type-agnostic building blocks that live in three new
subpackages of `parrot_pipelines/planogram/`:

| Subpackage | Contents |
|---|---|
| `perception/` | profile-driven **shape proposer**, **row / shelf-edge structure**, **slot geometry** (anchoring rules), lazy optional **OCR reader**, **fixture membership**, bounded **CPU executor** |
| `identification/` | provider-neutral **vision adapter** (`ask_to_image` + structured output, kwarg normalisation, schema-aware disk cache, one repair retry), **identify** strategies (full image / Set-of-Marks strips), **LLM detector** fallback, optional **closed-set verification** |
| `comparison/` | **slots definition** models + loader + rule bindings, row→shelf **registration**, per-facing decision + multi-photo merge + **scoring**, **projection** onto `List[ComplianceResult]` |

Shared Pydantic contracts for the three stages live in
`parrot_pipelines/planogram/contracts.py`. Backend (provider/model) resolution
lives in `parrot_pipelines/planogram/backend.py`.

**User-facing behaviour**

- The handler keeps its request and its existing response fields
  (`rendered_image_base64`, `content_type`, `overall_compliant`,
  `overall_compliance_score`, `shelf_results`) and adds `assessment_status`,
  `coverage` and `errors`, so an incomplete assessment is distinguishable from
  observed non-compliance.
- Callers of `run()` get the existing eight keys plus additive ones:
  `detections`, `identifications`, `position_results`, `shelf_scores`,
  `coverage`, `definition_coverage`, `assessment_status`,
  `strict_compliance_score`, `evidence_quality`, `detection_source`,
  `ocr_available`, `resolved_backend`, `renders`, `errors`.
- `planogram_type="ink_wall"` is selectable.
- Installing `ai-parrot-pipelines[planogram]` enables local OCR; without it the
  pipeline still runs, text is read by the LLM only, and the result reports
  `ocr_available=False`.
- The same run works with a Google or an Anthropic client.

**Perception default per type (spike-gated).** `InkWall` runs CV perception by
default — its price-tag detector is proven (FEAT-565). `ProductOnShelves`
perception is a profile-driven proposer whose recall is *unproven*; until the
Module 1 spike passes its gates, `ProductOnShelves` defaults to
`perception_mode="llm_detector"` (the G7 fallback used as the primary detector,
same hook, same membership and unknown-state rules). `planogram_config["perception_mode"] = "cv"`
opts a configuration into CV; a passed spike flips the class default in a
follow-up one-line change recorded in this spec's revision history.

**Compliance, coverage and evidence — three separate measures.** A detector
source does not establish SKU identity and model-reported confidence is not a
calibrated probability. `raw_confidence` is retained unchanged. Provisional
evidence source weights are `cv=1.0`, `llm_added=0.5`, `llm=0.5` (configurable
through `EvidenceWeights`); they feed **only** `evidence_quality`. They never
multiply compliance credit and never decide an identity conflict. A full
LLM-detector fallback can reach full compliance when the same evidence and
completeness requirements are met — there is no source-imposed cap.

An admissible exact match needs validated fixture membership and registration
**plus** product-discriminating evidence tied to the crop (readable identifiers
or required visible variant attributes). Neither a rectangle nor an expected SKU
offered in a verification prompt is sufficient. Unresolved identity remains
unresolved regardless of source or self-reported confidence.

**Per-facing credits** (`CreditPolicy`, a validated Pydantic model; values
provisional):

| Facing status | Strict | Lenient | Assessment treatment |
|---|---|---|---|
| `match` (admissible exact identity evidence) | 1.0 | 1.0 | Resolved |
| `misplaced` (supported identity, wrong facing) | 0.0 | 0.5 | Resolved, placement violation |
| `variant_unresolved`, `inferred_present` | 0.0 | 0.5 | Partially supported; **unresolved** for coverage |
| `mismatch`, visibly `empty` | 0.0 | 0.0 | Resolved violation |
| `occupied_unassigned`, `conflict`, `not_assessed`, `not_visible` | 0.0 | 0.0 | Unresolved; never assert missing from absence of evidence |

**Scoring contract for migrated types** (this pins the brainstorm's open
"scoring examples" item; §4 lists the fixtures that lock it). For shelf *s*
with expected facings *F_s* (from `slots_definition`) and bound rules *R_s*:

```
facing_strict(s)  = Σ strict_credit(f)  / |F_s|          for f in F_s      (|F_s| > 0)
facing_lenient(s) = Σ lenient_credit(f) / |F_s|
        # every expected facing stays in the denominator — a partial view
        # can never reach 100% by excluding unseen positions

text_score(s)     = Σ confidence(r) for found r / |text requirements|      (1.0 when none apply)
visual_score(s)   = mean(visual-feature match of matched facings/zones that
                         declare visual_features)                          (1.0 when none apply)
zone_score(s)     = fraction of required zones on s that were observed     (only for shelves with zones)

# weights — same resolution as today (product_on_shelves.py:745-764) …
header/endcap shelf : Wp = endcap.product_weight·(1-0.2)   Wt = endcap.text_weight   Wv = endcap.product_weight·0.2
other shelves       : Wv = shelf.visual_weight  or 0.2
                      Wt = shelf.text_weight    or 0.1
                      Wp = shelf.product_weight or (1 - Wv)
# … but NORMALISED for migrated types (today's non-header defaults sum to 1.1
# and are silently clamped, product_on_shelves.py:777):
W' = W / (Wp + Wt + Wv)  over the terms that APPLY to the shelf

product_term(s, mode) = facing_{mode}(s)            if |F_s| > 0
                      = zone_score(s)               if |F_s| == 0 and s has required zones
combined(s, mode)     = product_term·Wp' + text_score·Wt' + visual_score·Wv'

# illumination — existing penalty semantics, applied ONCE to the combined score
penalty(s)            = Σ illumination_penalty(mismatching bound rule) / max(1, |F_s|)
shelf_compliance(s, mode) = clamp01( combined(s, mode) · max(0, 1 - penalty(s)) )
```

- `ComplianceResult.compliance_score = shelf_compliance(s, lenient)`;
  the strict value is reported in the additive `ShelfAssessment`.
- A shelf with neither expected facings nor bound rules is rejected when the
  definition is validated — never scored, never divided by zero, and no product
  facing is manufactured for a zone-only shelf.
- `overall_compliance_score = mean_s shelf_compliance(s, lenient)` — the current
  unweighted shelf mean (`plan.py:350`) is preserved; it is **not** switched to
  facing-weighted aggregation. `strict_compliance_score` is the same mean over
  `shelf_compliance(s, strict)`.
- `coverage` = resolved facings / expected facings, **globally over facings**
  (not a mean of shelf percentages), where resolved = `match | misplaced |
  mismatch | empty`. Visible and occupied fractions are reported separately.
  `definition_coverage` = fraction of expected facings whose descriptors are
  sufficient to resolve the required identity; an undescribed SKU stays
  unresolved unless an exact, independently readable identifier links it.
- `evidence_quality` = mean of `EvidenceWeights[source]` over the deciding
  observation of each resolved facing; `None` when nothing is resolved.
- `assessment_status = "complete"` only when every expected facing is resolved
  **and** every mandatory bound rule was assessed; otherwise `"inconclusive"`.
  It describes completeness, independently of whether violations exist.
- **Shelf status projection** (existing `ComplianceStatus` enum, unchanged):
  `COMPLIANT` iff the shelf is completely assessed, `facing_lenient(s) ≥
  shelf.compliance_threshold` (default 0.8, `detections.py:307`), no mandatory
  rule failed, no illumination mismatch and no major unexpected product;
  `MISSING` iff the shelf is completely assessed and every facing is visibly
  `empty`; `MISPLACED` iff completely assessed and every violation on the shelf
  is `misplaced`; otherwise `NON_COMPLIANT` — including every shelf with
  unresolved facings, whose `ShelfAssessment` explains the incompleteness.
  `missing_products` lists only facings proven `empty` (plus the existing
  illumination pseudo-entries); unseen products are never labelled missing.
- `overall_compliant = assessment_status == "complete" and all shelves COMPLIANT`.
  Inconclusive ⇒ `False`. Zero coverage ⇒ `False` + inconclusive. Zero usable
  evidence ⇒ score `0.0`. An **empty result list is never a pass** — this also
  fixes today's quirk where `compliance_results == []` yields
  `overall_compliant=True` (`plan.py:347-351`); it is the single intended
  behaviour change on the legacy adapter path and is pinned by a test.
- **Legacy adapter types** retain their characterized per-shelf scoring. Fields
  their contract cannot establish (`coverage`, `definition_coverage`,
  `strict_compliance_score`, `evidence_quality`) are `None` with
  `assessment_status="legacy_unmeasured"`; full coverage is never fabricated.

**Observation validity.** Identification responses carry two collections:
`existing_identifications` (unknown IDs are invalid references; missing known
IDs become uncertain) and `added_shapes` (no authority to pick an existing
detection/facing ID — validated for image/strip ownership, finite in-bounds
boxes, positive area, membership and duplicates, then given pipeline-owned IDs
with `source="llm_added"`). Strip coordinates are normalised into their source
image before deduplication. Duplicates are resolved within an image before
cross-photo merging; concordant observations of one facing keep all provenance;
incompatible admissible identities become `conflict` regardless of source;
unreadable evidence never overrides a supported identification; CV localisation
alone never wins an identity disagreement; registration ties stay uncertain.

**Backend selection.** Resolution order: explicit `llm` (instance or
`"provider:model"` string) → explicit `llm_provider` / `llm_model` overrides
applied to the configured backend → `PlanogramConfig.llm_backend` → the
documented package default `DEFAULT_LLM_BACKEND = f"google:{parrot.conf.DEFAULT_LLM_MODEL}"`
(today's effective handler behaviour, `handlers/planogram_compliance.py:146`).
Omitted constructor arguments use an `UNSET` sentinel so the historical
`llm_provider="google"` default cannot mask `llm_backend`. An explicit provider
that differs from the configured provider, with no model, uses **that
provider's default** — never the other provider's model id. An explicit model
alone uses the configured provider. The resolved backend is recorded in the
result. Vision calls always pass the resolved model explicitly, so a client
method's own default argument can never override the caller's selection.

**Execution boundaries.** CPU-bound OpenCV / OCR / image encoding run in a
bounded, lifecycle-managed **process** executor (OCR initialised lazily inside
workers); blocking file I/O may use `asyncio.to_thread`; async hooks and LLM
calls stay on the event loop. One shared bounded LLM semaphore per run, bounded
strip queues, finite retries/timeouts, cancellation cleanup. Limits are
per-gunicorn-worker: `cpu_workers` (default 2), `llm_concurrency` (default 4),
`llm_timeout` (default 120 s), `llm_retries` (default 1 repair retry).

### Component Diagram

```
PlanogramCompliance.run(image | [images])
  │
  ├─ load ─────────── full-resolution, UNTOUCHED  (open_image(enhance=False))
  │                    └─ legacy adapter path keeps open_image() + _enhance_image
  │
  ├─ 1 PERCEIVE ───── type_handler.perceive(image, image_id, ctx) → PerceptionResult
  │     InkWall / ProductOnShelves                       legacy types (default)
  │     perception.shapes ─→ rows ─→ slots               types.legacy_adapter.legacy_perceive
  │     perception.ocr (optional)                          compute_roi → detect_objects → promo OCR →
  │     perception.membership                              virtual shelves → fact tags → injections
  │          └── CpuExecutor (bounded process pool)        (detection_source="legacy_llm")
  │
  ├─ fallback check ─ usable on-fixture shapes < type threshold
  │                    └─ identification.detector.llm_detect_shapes → detection_source="llm"
  │                       (+ same membership validation)
  │
  ├─ 2 IDENTIFY ───── type_handler.identify(image, perception, ctx) → IdentificationResult
  │     identification.identify  (FULL_IMAGE | STRIPS, Set-of-Marks)   legacy: pass-through
  │     identification.verify    (optional closed-set pass)
  │          └── VisionAdapter ──→ llm.ask_to_image(structured_output=…)   Google | Anthropic
  │                 (shared semaphore · cache · one repair retry · resolved model)
  │
  ├─ 3 COMPARE ────── type_handler.compare(perceptions, identifications, ctx) → ComparisonResult
  │     comparison.definition   (slots_definition + rule bindings)      legacy: check_planogram_compliance
  │     comparison.registration (row→shelf DP, per image)               + assessment_status="legacy_unmeasured"
  │     comparison.scoring      (per-facing decision, multi-photo merge, credits)
  │     comparison.projection   (→ List[ComplianceResult] + ShelfAssessment)
  │
  └─ render + assemble  render_evaluated_image per image → 8 legacy keys + additive keys
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot_pipelines/planogram/plan.py` | modifies | `run()` body replaced; signature widened to accept a list; result keys preserved + extended; `_PLANOGRAM_TYPES` gains `ink_wall`; constructor uses the `UNSET` sentinel |
| `parrot_pipelines/planogram/types/abstract.py` | modifies | new concrete hooks with legacy-wrapping defaults; the four legacy methods lose `@abstractmethod`; construction-time contract validation |
| `parrot_pipelines/planogram/types/product_on_shelves.py` | modifies | overrides the new hooks; legacy LLM detection becomes the fallback detector prompt source |
| `parrot_pipelines/planogram/types/ink_wall.py` | new | price-tag anchored type |
| `parrot_pipelines/planogram/{perception,identification,comparison}/`, `contracts.py`, `backend.py` | new | building blocks and contracts |
| `parrot_pipelines/models.py` (`PlanogramConfig`) | extends | `slots_definition` (dict or path), `llm_backend`; prompts optional |
| `parrot_pipelines/abstract.py` (`AbstractPipeline`) | modifies | removes the unconditional `GoogleGenAIClient` `roi_client`; `open_image(enhance=...)`; sentinel-aware constructor |
| `parrot_pipelines/planogram/types/*.py` (all six), `plan.py`, `grid/detector.py`, `legacy.py` | modifies | every `model="gemini…"` literal and `roi_client` use replaced — 63 matching lines in 11 files (§6 worklist) |
| `parrot_pipelines/handlers/planogram_compliance.py` | modifies | hydrates `slots_definition` / `llm_backend`, tolerates null prompts, stops building a `GoogleGenAIClient`, adds `assessment_status` / `coverage` / `errors` |
| `troc.planograms_configurations` (Postgres) | extends | nullable `slots_definition JSONB`, `llm_backend TEXT`; prompts lose `NOT NULL`; idempotent ALTER script shipped as package data |
| `parrot/clients/anthropic/client.py` (`ai-parrot-client-anthropic`) | extends | `ask_to_image(no_memory=...)`, default model resolution → `SONNET_5`, new `detect_objects(...)` |
| `parrot/models/compliance.py` (core) | extends | additive `ShelfAssessment` + `ComplianceResult.assessment: Optional[ShelfAssessment] = None`; enum and existing fields unchanged |
| `parrot_pipelines/__init__.py` (`PIPELINE_REGISTRY`) | extends | adds `InkWall` and the three types already missing from it |
| `packages/ai-parrot-pipelines/pyproject.toml` | extends | `[project.optional-dependencies] planogram`; declares directly used `numpy`, `pillow`, `rapidfuzz` |
| `examples/planogram/` + `.gitignore` | extends | spike harness, benchmark script, descriptor utility (tracked through new negation lines); **`plancheck/` untouched** |
| `docs/pipelines/` | new | migration / deployment / rollback runbook |

Audit note: `AbstractPipeline` and the Anthropic client are shared surfaces —
Module 4 and Module 6 must grep for other consumers of `roi_client` and of
`AnthropicClient.ask_to_image(model=…)` defaults before changing them.

### Data Models

```python
# parrot_pipelines/planogram/contracts.py  (new) — all Pydantic v2 BaseModel / str Enum
class ShapeKind(str, Enum):        PRICE_TAG, PRODUCT, BOX, FACT_TAG, ZONE, UNKNOWN
class ObservationSource(str, Enum): CV = "cv"; LLM_ADDED = "llm_added"; LLM = "llm"; LEGACY_LLM = "legacy_llm"
class FixtureMembership(str, Enum): ON_FIXTURE, OFF_FIXTURE, UNCERTAIN
class IdentifyStrategy(str, Enum):  FULL_IMAGE, STRIPS
class FacingStatus(str, Enum):      MATCH, MISPLACED, VARIANT_UNRESOLVED, MISMATCH, EMPTY, INFERRED_PRESENT,
                                    OCCUPIED_UNASSIGNED, CONFLICT, NOT_ASSESSED, NOT_VISIBLE
class AssessmentStatus(str, Enum):  COMPLETE, INCONCLUSIVE, LEGACY_UNMEASURED

class Shape(BaseModel):            shape_id, image_id, kind, box: DetectionBox, profile, row_index, slot_index,
                                   ocr_text, ocr_confidence, source, membership, membership_evidence
class Slot(BaseModel):             slot_id, image_id, row_index, slot_index, box: DetectionBox, anchor_shape_id, inferred
class PerceptionResult(BaseModel): image_id, image_size, shapes, slots, zones, row_count, detection_source,
                                   ocr_available, legacy: Optional[LegacyPayload], errors
class Identification(BaseModel):   shape_id, image_id, product, brand, text, descriptors, raw_confidence,
                                   evidence, source, uncertain
class AddedShape(BaseModel):       box_norm (0-1000, [ymin,xmin,ymax,xmax]), kind, product, brand, text,
                                   descriptors, raw_confidence, evidence
class IdentificationResponse(BaseModel):   existing_identifications, added_shapes      # LLM structured output
class IdentificationResult(BaseModel):     image_id, identifications, added, errors
class PositionResult(BaseModel):   facing_id, shelf_id, status, strict_credit, lenient_credit, identity,
                                   observations (provenance, per image_id), notes
class ShelfScore(BaseModel):       shelf_id, shelf_level, expected_facings, facing_strict, facing_lenient,
                                   strict_score, lenient_score, coverage, visible_fraction, occupied_fraction, rule_results
class RuleOutcome(BaseModel):      rule_id, assessed: bool, passed: Optional[bool], score: float, penalty: float, detail
class CreditPolicy(BaseModel) / EvidenceWeights(BaseModel)                              # validated, provisional defaults
class ComparisonResult(BaseModel): compliance_results, position_results, shelf_scores, overall_compliance_score,
                                   strict_compliance_score, overall_compliant, coverage, definition_coverage,
                                   evidence_quality, assessment_status, errors
class RenderRecord(BaseModel):     image_id, rendered_image, overlay_path

# parrot_pipelines/planogram/comparison/definition.py  (new)
class SlotsDefinition(BaseModel):  version, meta, shelves: List[ShelfDefinition], zones: List[ZoneDefinition]
class ShelfDefinition(BaseModel):  shelf_id, shelf_number, level, facings: List[FacingDefinition]
class FacingDefinition(BaseModel): facing_id, shelf_id, slot, product, brand, facings, descriptors: Descriptors
class Descriptors(BaseModel):      display_name, family, xl, colors, pack, identifiers, aliases, price  (all optional)
class ZoneDefinition(BaseModel):   zone_id, kind (header|backlit|poster|box_stack), shelf_id, required
class RuleBinding(BaseModel):      rule_id, kind (illumination|text_requirements|visual_features|zone_present),
                                   target_id (facing_id|zone_id|shelf_id), params, mandatory

# packages/ai-parrot/src/parrot/models/compliance.py  (extends, additive)
class ShelfAssessment(BaseModel):  assessment_status, coverage, strict_score, lenient_score, expected_facings,
                                   resolved_facings, unresolved_facing_ids, rule_results
```

### New Public Interfaces

```python
from parrot_pipelines.planogram import PlanogramCompliance
from parrot_pipelines.models import PlanogramConfig

config = PlanogramConfig(
    planogram_type="ink_wall",
    planogram_config={...},                       # non-product expectations + rule_bindings
    slots_definition="planogram_page1.json",      # or a dict (JSONB row value)
    llm_backend="anthropic:claude-sonnet-5",      # optional; constructor args still win
)
pipeline = PlanogramCompliance(planogram_config=config)
result = await pipeline.run(image=["wall_left.jpg", "wall_right.jpg"], output_dir="out/")
result["overall_compliance_score"], result["assessment_status"], result["coverage"]
```

---

## 3. Module Breakdown

> Paths are relative to `packages/ai-parrot-pipelines/src/parrot_pipelines/`
> unless they start with `packages/`, `examples/`, `docs/` or `sdd/`.
> Tests live in `packages/ai-parrot-pipelines/tests/` (new subfolder
> `tests/planogram_cycle/`) unless stated otherwise.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Perception spike | no | — | R&D: profile constants and proposer cues are the *output* of the task |
| M2: Cycle contracts | yes | every model and field fixed in §2 Data Models + skeleton | — |
| M3: Legacy characterization tests | no | — | must read 1683 lines of behaviour and decide what to pin; judgement-heavy |
| M4: Anthropic vision parity | yes | signatures, return dict shape and model resolution fixed in skeleton | — |
| M5: Config & backend resolution | yes | precedence matrix, sentinel, SQL statements fixed | — |
| M6: Provider-neutral call sites | yes | mechanical replacement over the §6 worklist with a fixed idiom | — |
| M7: Perception structure | no | — | generalising `group_rows` / `build_slots` needs algorithmic judgement |
| M8: OCR reader + packaging | yes | lazy-import pattern, extra name and dependency list fixed | — |
| M9: Slots definition & rule bindings | yes | schema, validation errors and loader contract fixed | — |
| M10: Vision adapter | yes | kwargs table, cache key, retry rule fixed | — |
| M11: Fixture membership | no | — | evidence policy is validated by the spike; heuristics need judgement |
| M12: Identification | no | — | prompt design + added-shape validation interplay |
| M13: Registration & scoring | no | — | DP alignment and the decision list need judgement; formula itself is fixed in §2 |
| M14: Type hooks & legacy adapter | no | — | must move `run()` orchestration without behaviour drift |
| M15: `run()` template | no | — | orchestration, cancellation and multi-image edge cases |
| M16: `InkWall` | no | — | composes every block; descriptor identity rules |
| M17: `ProductOnShelves` migration | no | — | carries characterized semantics into new hooks |
| M18: Handler | yes | hydrated columns and response keys fixed | — |
| M19: Config migration tooling | no | — | conversion heuristics over real configs; ambiguity handling |
| M20: Descriptor assistant | yes | CLI contract, output schema and "never price" rule fixed | — |
| M21: Backend benchmark | yes | report columns and pinning list fixed | — |
| M22: Registry, exports, docs | yes | export list fixed | — |

### Module 1: Perception spike + shape proposer *(first task)*
- **Path**: `planogram/perception/__init__.py`, `planogram/perception/profiles.py`,
  `planogram/perception/shapes.py`, `examples/planogram/perception_spike/`
  (`run_spike.py`, `evaluate.py`, `README.md`), `.gitignore` (negations for the
  harness `*.py` / `README.md`), `docs/pipelines/planogram-perception-spike.md`
- **Responsibility**: a profile-driven classical-CV shape proposer (the
  generalisation of `plancheck.detection.find_candidates`, whose constants only
  describe a bright landscape price label) and a harness that measures it.
  Two-engineering-day time box (provisional). Inputs: the named photo
  `examples/planogram/photo_2026-09-18_20-36-30.jpg` plus available private
  photos covering partial views and neighbouring fixtures; photos and manual
  annotations stay git-ignored — only aggregate results and synthetic regression
  cases are committed. Proposals are matched one-to-one to annotations
  (IoU ≥ 0.5, provisional); precision and recall are reported **per shape
  profile and per photo**, plus off-fixture admissions; tag-anchored proposals
  must additionally show that their derived slots cover the intended products.
  Gates for CV-by-default on the evaluated fixture profile: ≥ 90 % product-slot
  recall and ≥ 90 % precision on each evaluable photo, zero off-fixture
  observations admitted into scoring, and passing synthetic cases for partial
  shelves, repeated SKUs, absent anchors and ambiguous membership. Insufficient
  photos, untested conditions or any failed gate ⇒ inconclusive/failed ⇒
  `ProductOnShelves` stays on `perception_mode="llm_detector"`. The report
  records accepted profiles, tested conditions, failures, and the outcome.
  Ships the proven `PRICE_TAG_PROFILE` (InkWall) regardless of the outcome.
- **Depends on**: nothing (uses `opencv`, `numpy` only)
- **Interface Skeleton**:
  ```python
  # planogram/perception/profiles.py  (new)
  class ShapeProfile(BaseModel):
      """Geometric/photometric description of one kind of shape to propose."""
      name: str
      kind: str                                   # ShapeKind value; str to keep M1 free of M2
      min_width: float; max_width: float          # fractions of image width
      min_height: float; max_height: float        # fractions of image height
      min_aspect: float; max_aspect: float        # w / h
      polarity: Literal["bright", "dark", "edge"]
      min_rectangularity: float = 0.75
      min_contrast_std: float = 25.0
      thresholds: Tuple[int, ...] = (130, 150, 170, 190, 210, 230)
      dedup_overlap: float = 0.5

  class ShapeCandidate(BaseModel):
      """One proposed rectangle in source-image pixels."""
      profile: str; kind: str
      x1: int; y1: int; x2: int; y2: int
      score: float

  PRICE_TAG_PROFILE: ShapeProfile                 # constants from plancheck/detection.py:19-66 (reference only)

  # planogram/perception/shapes.py  (new)
  def propose_shapes(image: np.ndarray, profiles: Sequence[ShapeProfile], *,
                     work_width: int = 2048) -> List[ShapeCandidate]:
      """Propose rectangles for every profile on a BGR image. Pure, synchronous, picklable
      (runs inside CpuExecutor). Coordinates are scaled back to the source image.
      Returns [] when nothing qualifies; never raises on a valid image."""
  ```

### Module 2: Cycle contracts
- **Path**: `planogram/contracts.py`; `packages/ai-parrot/src/parrot/models/compliance.py` (additive)
- **Responsibility**: every Pydantic model / enum of §2 Data Models, the credit
  and evidence policies with their provisional defaults, and the additive
  `ShelfAssessment` on the core `ComplianceResult`.
- **Depends on**: `parrot.models.detections.DetectionBox`
- **Interface Skeleton**:
  ```python
  # planogram/contracts.py  (new)
  from parrot.models.detections import DetectionBox, IdentifiedProduct, ShelfRegion  # verified: detections.py:37,71,62
  from parrot.models.compliance import ComplianceResult                              # verified: compliance.py:32

  class CreditPolicy(BaseModel):
      """Strict/lenient credit per FacingStatus. Validates 0<=credit<=1 and strict<=lenient."""
      strict: Dict[FacingStatus, float]
      lenient: Dict[FacingStatus, float]
      @classmethod
      def default(cls) -> "CreditPolicy": """The §2 table."""
      def is_resolved(self, status: FacingStatus) -> bool:
          """True for MATCH, MISPLACED, MISMATCH, EMPTY."""

  class EvidenceWeights(BaseModel):
      """Evidence-quality weight per ObservationSource (cv=1.0, llm_added=0.5, llm=0.5, legacy_llm=0.5).
      Never multiplies compliance credit."""

  class LegacyPayload(BaseModel):
      """What the legacy adapter carries between hooks."""
      identified_products: List[IdentifiedProduct]
      shelf_regions: List[ShelfRegion]

  class CycleContext(BaseModel):
      """Per-run shared services handed to every hook (arbitrary_types_allowed)."""
      vision: Any            # identification.vision.VisionAdapter
      executor: Any          # perception.executor.CpuExecutor
      ocr: Any               # perception.ocr.OcrReader
      definition: Optional[Any] = None   # comparison.definition.SlotsDefinition
      bindings: List[Any] = []           # comparison.definition.RuleBinding
      credit_policy: CreditPolicy
      evidence_weights: EvidenceWeights
      output_dir: Optional[Path] = None
      errors: List[str] = []

  # packages/ai-parrot/src/parrot/models/compliance.py  (modifies :32-52, additive only)
  class ShelfAssessment(BaseModel):
      """Additive shelf metadata; all fields optional so legacy producers need not set it."""
  class ComplianceResult(BaseModel):
      assessment: Optional[ShelfAssessment] = None      # NEW field, default None
  ```

### Module 3: Legacy characterization tests + fake vision client
- **Path**: `packages/ai-parrot-pipelines/tests/conftest.py` (new),
  `tests/planogram_cycle/test_pos_compliance_characterization.py`,
  `test_pos_fact_tags_characterization.py`, `test_illumination_characterization.py`,
  `test_legacy_run_orchestration.py`
- **Responsibility**: pin **today's** behaviour before anything changes:
  `ProductOnShelves.check_planogram_compliance` (the §6 scoring math, including
  the quirks listed there), `_ocr_fact_tags`, `_corroborate_products_with_fact_tags`,
  `_assign_products_to_shelves`, `_check_illumination`, and the **complete**
  `run()` orchestration (enhancement, promotional OCR, poster/logo injection,
  virtual shelves, shelf assignment, fact-tag refinement and corroboration — the
  20 steps in §6). Offline, synthetic images, fake LLM. These tests must stay
  green through Modules 6, 14 and 15 for legacy types.
- **Depends on**: nothing
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-pipelines/tests/conftest.py  (new)
  class FakeVisionClient:
      """Offline stand-in for a provider client. Records calls; pops canned responses per method."""
      client_name: str = "fake"
      model: Optional[str] = None
      calls: List[Dict[str, Any]]
      def queue(self, method: str, *responses: Any) -> None: ...
      async def ask_to_image(self, prompt: str, image: Any, **kwargs: Any) -> Any:
          """Returns an object with .output / .structured_output, or raises a queued Exception."""
      async def detect_objects(self, image: Any, prompt: str, reference_images: Any = None,
                               output_dir: Any = None, **kwargs: Any) -> List[Dict[str, Any]]: ...
      async def __aenter__(self) -> "FakeVisionClient": ...
      async def __aexit__(self, *exc: Any) -> None: ...

  @pytest.fixture
  def fake_vision_client() -> FakeVisionClient: ...
  @pytest.fixture
  def synthetic_shelf_image() -> "PIL.Image.Image": ...
  ```

### Module 4: Anthropic vision parity
- **Path**: `packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py`,
  `packages/ai-parrot-client-anthropic/tests/unit/test_vision_parity.py`
- **Responsibility**: `no_memory` on `ask_to_image` (gates history replay only —
  the method already touches no memory); method default changed so it can no
  longer mask the caller's selection (explicit arg → client's configured model →
  `ClaudeModel.SONNET_5`); new `detect_objects` with Google's positional
  signature and return-dict shape.
- **Depends on**: nothing
- **Interface Skeleton**:
  ```python
  # .../anthropic/client.py  (modifies :1307-1483)
  async def ask_to_image(
      self, prompt: str, image: Union[Path, bytes, Image.Image],
      reference_images: Optional[List[Union[Path, bytes, Image.Image]]] = None,
      model: Union[ClaudeModel, str, None] = None,      # was ClaudeModel.SONNET_4 (:1312)
      max_tokens: Optional[int] = None, temperature: Optional[float] = None,
      structured_output: Union[type, StructuredOutputConfig] = None,
      count_objects: bool = False,
      history: Optional[Sequence[HistoryMessage]] = None,
      system_prompt: Optional[str] = None, context_1m: bool = False,
      no_memory: bool = False,                          # NEW — keyword position last, non-breaking
  ) -> AIMessage:
      """no_memory=True ⇒ messages = self._format_history(())   (today: :1352 replays `history or ()`).
      Model: explicit `model` → `self.model` → ClaudeModel.SONNET_5, then self._resolve_model()."""

  async def detect_objects(                             # NEW — mirrors google/analysis.py:1234-1239
      self, image: Union[str, Path, Image.Image], prompt: str,
      reference_images: Optional[List[Union[str, Path, Image.Image]]] = None,
      output_dir: Optional[Union[str, Path]] = None, *,
      model: Union[ClaudeModel, str, None] = None,
  ) -> List[Dict[str, Any]]:
      """Returns dicts shaped like Google's: {"label": str, "box_2d": [x1, y1, x2, y2] in ORIGINAL-image
      pixels, "confidence": float, "mask_image": None, "overlay_image": None, **passthrough}.
      Built on ask_to_image(structured_output=<0-1000 normalised box schema>, no_memory=True);
      degenerate boxes skipped; unparseable answer ⇒ [] (never raises for a bad model answer).
      `output_dir` is created when given; nothing is written (no masks on Anthropic)."""
  ```

### Module 5: Config & backend resolution
- **Path**: `models.py`, `planogram/backend.py` (new), `abstract.py`, `table.sql`,
  `alter_planograms_configurations_feat574.sql` (new, shipped by the existing
  `"*.sql"` package-data glob, `pyproject.toml:46-47`)
- **Responsibility**: `PlanogramConfig.slots_definition` / `llm_backend`;
  optional prompts; the `UNSET` sentinel and the full precedence matrix;
  `AbstractPipeline.open_image(enhance=...)`; schema + idempotent ALTER.
- **Depends on**: nothing
- **Interface Skeleton**:
  ```python
  # models.py  (modifies PlanogramConfig :29-108)
  roi_detection_prompt: Optional[str] = None            # was required str (:55-57)
  object_identification_prompt: Optional[str] = None    # was required str (:60-62)
  slots_definition: Optional[Union[Dict[str, Any], str, Path]] = None   # NEW — dict (JSONB) or path to JSON
  llm_backend: Optional[str] = None                     # NEW — "provider:model"
  @field_validator("llm_backend")
  def _check_backend(cls, v): """Must parse via LLMFactory.parse_llm_string into a non-empty provider."""

  # planogram/backend.py  (new)
  class _Unset(Enum): UNSET = "unset"
  UNSET = _Unset.UNSET
  DEFAULT_LLM_BACKEND: str            # f"google:{parrot.conf.DEFAULT_LLM_MODEL}"  verified: conf.py:443

  class ResolvedBackend(BaseModel):
      provider: str
      model: Optional[str]            # None ⇒ provider default
      origin: Literal["llm_instance", "llm_string", "constructor", "config", "package_default"]
      def as_string(self) -> str: ...

  def resolve_backend(llm: Any, llm_provider: Union[str, _Unset], llm_model: Union[str, None, _Unset],
                      config_backend: Optional[str]) -> ResolvedBackend:
      """Implements the §2 precedence. Provider switch without a model never inherits the other
      provider's model id. Raises ValueError for an unparseable backend string."""

  # abstract.py  (modifies AbstractPipeline :16-40, :73-87)
  def __init__(self, llm: Any = None, llm_provider: Union[str, _Unset] = UNSET,
               llm_model: Union[str, None, _Unset] = UNSET, *, config_backend: Optional[str] = None,
               **kwargs: Any): """Sets self.llm, self.llm_provider, self.resolved_backend. NO roi_client."""
  def open_image(self, image_path: Union[Path, Image.Image], *, enhance: bool = True) -> Image.Image: ...
  ```
  ```sql
  -- alter_planograms_configurations_feat574.sql  (new, idempotent)
  ALTER TABLE troc.planograms_configurations ADD COLUMN IF NOT EXISTS slots_definition JSONB NULL;
  ALTER TABLE troc.planograms_configurations ADD COLUMN IF NOT EXISTS llm_backend TEXT NULL;
  ALTER TABLE troc.planograms_configurations ALTER COLUMN roi_detection_prompt DROP NOT NULL;
  ALTER TABLE troc.planograms_configurations ALTER COLUMN object_identification_prompt DROP NOT NULL;
  -- table.sql mirrors the same four changes (:16-17 lose NOT NULL).
  ```

### Module 6: Provider-neutral call sites
- **Path**: the 11 files of the §6 worklist
- **Responsibility**: mechanical removal of every `model="gemini…"` literal and
  every `roi_client` use. Fixed idiom: `async with self.pipeline.llm as client:`
  (verified idiom: `legacy.py:1473`) and
  `model=self.pipeline.resolved_backend.model` passed **only when not `None`**;
  `no_memory=True` is kept (both vision clients accept it after Module 4).
  `grid/detector.py:130` and `product_on_shelves.py:330` keep calling
  `llm.detect_objects(...)` — now available on both clients.
  `legacy.py:2282-2287` switches from `self.roi_client` to `self.llm`.
  No algorithm changes. Module 3 tests stay green.
- **Depends on**: M3 (pins behaviour), M4 (Anthropic accepts the kwargs), M5 (`resolved_backend`)
- **Interface Skeleton**:
  ```python
  # planogram/types/abstract.py  (new helper, used by every rewritten call site)
  def _vision_kwargs(self, **extra: Any) -> Dict[str, Any]:
      """Returns {"no_memory": True, **extra} plus "model" when the resolved backend pins one."""
  ```

### Module 7: Perception structure (rows, shelf edges, slots, executor)
- **Path**: `planogram/perception/rows.py`, `slots.py`, `executor.py`
- **Responsibility**: rows from aligned shapes (generalised `group_rows`),
  horizontal shelf-edge detection for shelf-anchored types, slot geometry with
  pluggable anchoring (tag-below-product is one rule, not the only one; gap
  filling and an untagged bottom row for InkWall), and the bounded process
  executor.
- **Depends on**: M1, M2
- **Interface Skeleton**:
  ```python
  # perception/rows.py
  def group_rows(candidates: Sequence[ShapeCandidate], image_width: int, *, min_row_items: int = 4,
                 max_slope: float = 0.12) -> List[List[ShapeCandidate]]:
      """Rows ordered top→bottom, items left→right. Reference: plancheck/detection.py:68."""
  def detect_shelf_edges(image: np.ndarray, *, min_length: float = 0.35) -> List[int]:
      """Y coordinates of long horizontal edges, top→bottom. [] when none."""

  # perception/slots.py
  class AnchorRule(str, Enum): TAG_BELOW_PRODUCT = "tag_below_product"; SHAPE_IS_SLOT = "shape_is_slot"
  def build_slots(rows: Sequence[Sequence[ShapeCandidate]], image_size: Tuple[int, int], *, image_id: str,
                  rule: AnchorRule, fill_gaps: bool = True, untagged_bottom_row: bool = False) -> List[Slot]:
      """Reference: plancheck/grid.py:78. slot_index is 1..n per row; gap-filled slots have inferred=True."""
  def strip_box(slots: Sequence[Slot], image_size: Tuple[int, int], pad: float = 0.04) -> DetectionBox: ...
  def to_strip_norm(box: DetectionBox, strip: DetectionBox) -> List[int]:
      """[ymin, xmin, ymax, xmax] in 0-1000 relative to the strip."""
  def from_strip_norm(norm: Sequence[int], strip: DetectionBox) -> DetectionBox:
      """Inverse of to_strip_norm, into SOURCE-image pixels. Raises ValueError on non-finite/out-of-range."""

  # perception/executor.py
  class CpuExecutor:
      """Lazily created, bounded ProcessPoolExecutor; one per PlanogramCompliance instance."""
      def __init__(self, max_workers: int = 2) -> None: ...
      async def run(self, fn: Callable[..., T], *args: Any) -> T:
          """fn must be module-level and picklable. Cancellation-safe."""
      async def aclose(self) -> None: ...
  ```

### Module 8: OCR reader + packaging
- **Path**: `planogram/perception/ocr.py`, `packages/ai-parrot-pipelines/pyproject.toml`
- **Responsibility**: lazy, optional local OCR; and **all** `pyproject.toml`
  edits of this feature (single owner of that file).
- **Depends on**: nothing
- **Interface Skeleton**:
  ```python
  # perception/ocr.py
  class OcrReader:
      """RapidOCR wrapper. Import is probed at construction and the engine is built lazily on first
      read — inside the worker process when called through CpuExecutor."""
      available: bool
      def __init__(self) -> None: ...
      def read(self, crop: np.ndarray) -> Tuple[str, float]:
          """(text, confidence); ("", 0.0) when unavailable or nothing is read. Never raises ImportError."""
  def read_crop(crop: np.ndarray) -> Tuple[str, float]:
      """Module-level, picklable entry point using a per-process OcrReader singleton."""
  ```
  ```toml
  # pyproject.toml — dependencies gain: "numpy", "pillow", "rapidfuzz"
  [project.optional-dependencies]
  planogram = ["rapidocr>=3.9", "onnxruntime>=1.20"]
  ```

### Module 9: Slots definition & rule bindings
- **Path**: `planogram/comparison/__init__.py`, `planogram/comparison/definition.py`
- **Responsibility**: parse a dict or a JSON path into a validated
  `SlotsDefinition`; accept the existing `planogram_page1.json` layout
  (`{"planogram": {...}, "shelves": [{"shelf", "shelf_number", "products": {"pos <shelf>:<n>": {...}}}]}`)
  and normalise it; stable IDs; validate `planogram_config["rule_bindings"]`.
- **Depends on**: M2
- **Interface Skeleton**:
  ```python
  def load_slots_definition(source: Union[Dict[str, Any], str, Path]) -> SlotsDefinition:
      """Blocking file read — call via asyncio.to_thread from async code.
      Raises SlotsDefinitionError (ValueError) when: slot sequence of a shelf is not 1..n; duplicate
      facing_id / zone_id / shelf_id; conflicting descriptors for one SKU; zero described positions;
      a shelf with neither facings nor zones."""
  def definition_coverage(definition: SlotsDefinition) -> Tuple[float, List[str]]:
      """(fraction of facings with sufficient descriptors, undescribed facing_ids). Not fatal."""
  def validate_bindings(definition: SlotsDefinition, planogram_config: Dict[str, Any]) -> List[RuleBinding]:
      """Reads planogram_config["rule_bindings"]. Raises SlotsDefinitionError on a dangling or ambiguous
      target_id — rules are never silently dropped."""
  class SlotsDefinitionError(ValueError): ...
  ```

### Module 10: Vision adapter
- **Path**: `planogram/identification/__init__.py`, `planogram/identification/vision.py`
- **Responsibility**: the only place that calls `ask_to_image` for the new
  cycle. Capability guard (`hasattr(client, "ask_to_image")`, fail fast — e.g.
  `ClaudeAgentClient` raises `NotImplementedError`); per-provider kwarg
  normalisation (explicitly supported kwargs only — unknown kwargs raise, they
  are not silently dropped); resolved model always passed when pinned;
  schema-aware disk cache (optional `cache_dir`); one repair retry on invalid
  structure; shared semaphore; timeout.
- **Depends on**: M2, M5
- **Interface Skeleton**:
  ```python
  class VisionError(RuntimeError): ...
  class VisionAdapter:
      def __init__(self, client: Any, backend: ResolvedBackend, *, semaphore: asyncio.Semaphore,
                   cache_dir: Optional[Path] = None, max_tokens: int = 8192,
                   timeout: float = 120.0, repair_retries: int = 1) -> None:
          """Raises VisionError when the client has no ask_to_image."""
      async def ask(self, prompt: str, images: Sequence[bytes], schema: Type[T], *, stage: str,
                    prompt_version: str, system_prompt: Optional[str] = None) -> T:
          """images[0] is the main image, the rest go as reference_images. Returns a validated `schema`
          instance. Raises VisionError after the repair retry fails or on timeout."""
  def cache_key(backend: str, max_tokens: int, stage: str, prompt_version: str, prompt: str,
                schema: Type[BaseModel], images: Sequence[bytes]) -> str:
      """sha256 over all arguments incl. schema JSON — a schema change invalidates the cache."""
  ```

### Module 11: Fixture membership
- **Path**: `planogram/perception/membership.py`
- **Responsibility**: assign `on_fixture` / `off_fixture` / `uncertain` to every
  shape from fixture anchors (header/backlit, box stack — evidence, not gates),
  shelf continuity and spatial relationships. An LLM suggestion may be recorded
  as evidence with its source. Expected-SKU matches are **not** an input. Absent
  anchors ⇒ `uncertain`, perception continues. Only `on_fixture` observations
  reach registration; the rest stay in the audit output.
- **Depends on**: M2
- **Interface Skeleton**:
  ```python
  def assign_membership(shapes: Sequence[Shape], zones: Sequence[Shape], image_size: Tuple[int, int],
                        *, llm_hints: Optional[Dict[str, FixtureMembership]] = None) -> List[Shape]:
      """Returns copies with membership + membership_evidence set. Pure and deterministic."""
  def usable_shapes(shapes: Sequence[Shape]) -> List[Shape]:
      """on_fixture only — the count the fallback threshold is compared against. Distractor counts
      can never suppress the fallback."""
  ```

### Module 12: Identification (strategies, LLM detector, verification)
- **Path**: `planogram/identification/identify.py`, `detector.py`, `verify.py`
- **Responsibility**: structured-input / structured-output identification in
  the strategy the type declares — `FULL_IMAGE` (one call: image + stage-1 JSON)
  or `STRIPS` (one call per row, Set-of-Marks overlay, sub-strips above 8 slots,
  bounded by the shared semaphore); validation of `existing_identifications`
  and `added_shapes` per §2 *Observation validity*; the LLM detector fallback;
  optional closed-set verification (expected SKU + distractors, evidence-gated).
  A failed strip makes its slots uncertain and is recorded in `errors`; the run
  continues.
- **Depends on**: M2, M7, M9, M10, M11
- **Interface Skeleton**:
  ```python
  # identification/identify.py
  IDENTIFY_PROMPT_VERSION: str
  async def identify_full_image(image: np.ndarray, perception: PerceptionResult, ctx: CycleContext,
                                *, vocabulary: Sequence[str]) -> IdentificationResult: ...
  async def identify_strips(image: np.ndarray, perception: PerceptionResult, ctx: CycleContext,
                            *, vocabulary: Sequence[str], marks: bool = True,
                            substrip_max_slots: int = 8) -> IdentificationResult: ...
  def validate_response(response: IdentificationResponse, perception: PerceptionResult, *,
                        strip: Optional[DetectionBox], next_shape_id: Callable[[], str]
                        ) -> Tuple[List[Identification], List[Shape], List[str]]:
      """(identifications, accepted added shapes with pipeline-owned ids and source=llm_added, errors)."""

  # identification/detector.py
  async def llm_detect_shapes(image: np.ndarray, image_id: str, ctx: CycleContext, *, prompt: str
                              ) -> List[Shape]:
      """Full-image LLM proposals through VisionAdapter; every shape has source=llm. [] on failure
      (the failure is appended to ctx.errors)."""

  # identification/verify.py
  async def verify_unresolved(image: np.ndarray, identifications: List[Identification],
                              definition: SlotsDefinition, ctx: CycleContext, *, n_distractors: int = 3
                              ) -> List[Identification]:
      """Closed-set pass for unresolved slots. An offered expected SKU is never evidence by itself."""
  ```

### Module 13: Registration, scoring, projection
- **Path**: `planogram/comparison/registration.py`, `scoring.py`, `projection.py`
- **Responsibility**: per-image row→shelf registration (NW-style DP; product rows
  register in **strictly increasing** shelf order; header/backlit/poster zones
  are detected apart and take no part); per-facing decision list; multi-photo
  merge keyed by `facing_id` **after** registration; credits, per-shelf and
  global measures exactly as §2; rule evaluation through bindings; projection
  onto `List[ComplianceResult]` (one per definition shelf, definition order).
- **Depends on**: M2, M9
- **Interface Skeleton**:
  ```python
  # comparison/registration.py
  class ImageRegistration(BaseModel): image_id; row_to_shelf: Dict[int, str]; assignments: Dict[str, str]; ambiguous: bool
  def register_image(image_id: str, slots: Sequence[Slot], identifications: Sequence[Identification],
                     definition: SlotsDefinition) -> ImageRegistration:
      """Ambiguous or unsupported alignment ⇒ ambiguous=True and NO assignments (facings stay
      not_assessed / not_visible). Candidate identity can never force a facing assignment."""

  # comparison/scoring.py
  def merge_positions(definition: SlotsDefinition, registrations: Sequence[ImageRegistration],
                      identifications: Sequence[Identification], policy: CreditPolicy) -> List[PositionResult]: ...
  def score_shelves(positions: Sequence[PositionResult], definition: SlotsDefinition,
                    bindings: Sequence[RuleBinding], rule_outcomes: Dict[str, RuleOutcome],
                    description: PlanogramDescription, policy: CreditPolicy) -> List[ShelfScore]: ...
  def summarize(shelf_scores: Sequence[ShelfScore], positions: Sequence[PositionResult],
                definition: SlotsDefinition, weights: EvidenceWeights) -> ComparisonResult: ...

  # comparison/projection.py
  def project_compliance(shelf_scores: Sequence[ShelfScore], positions: Sequence[PositionResult],
                         definition: SlotsDefinition, description: PlanogramDescription
                         ) -> List[ComplianceResult]:
      """Status rules of §2. Sets ComplianceResult.assessment."""
  ```

### Module 14: Type hooks & legacy adapter
- **Path**: `planogram/types/abstract.py`, `planogram/types/legacy_adapter.py` (new)
- **Responsibility**: the new hook contract with adapter defaults. The legacy
  orchestration currently inlined in `plan.py:98-343` moves, **behaviour-preserving**,
  into `legacy_adapter.legacy_perceive` (it keeps calling the private helpers
  through the same `hasattr` guards). The four legacy methods lose
  `@abstractmethod` and default to `raise NotImplementedError("<Type> does not implement the legacy contract")`.
  `validate_contract()` runs at construction: a type must supply either the
  complete legacy contract (`compute_roi`, `detect_objects`,
  `check_planogram_compliance`) or all three new hooks — otherwise `TypeError`
  before any run starts. Legacy types validate their required prompts here.
- **Depends on**: M2, M3, M6 (same file)
- **Interface Skeleton**:
  ```python
  # planogram/types/abstract.py  (modifies :30-478)
  class AbstractPlanogramType(ABC):
      identify_strategy: ClassVar[IdentifyStrategy] = IdentifyStrategy.FULL_IMAGE
      requires_slots_definition: ClassVar[bool] = False
      min_usable_shapes: ClassVar[int] = 0          # fallback threshold; 0 disables the fallback
      uses_enhanced_image: ClassVar[bool] = True    # legacy default; migrated types set False

      def validate_contract(self) -> None:
          """TypeError on an incomplete contract; ValueError when a legacy type lacks its prompts or a
          migrated type lacks a valid slots_definition (message names the migration runbook)."""
      async def perceive(self, image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult:
          """Default: legacy_adapter.legacy_perceive → detection_source='legacy_llm'."""
      async def identify(self, image: Image.Image, perception: PerceptionResult,
                         ctx: CycleContext) -> IdentificationResult:
          """Default: pass-through (legacy types identified during detection)."""
      async def compare(self, perceptions: Sequence[PerceptionResult],
                        identifications: Sequence[IdentificationResult], ctx: CycleContext) -> ComparisonResult:
          """Default: check_planogram_compliance on the first image's LegacyPayload; mean / all-COMPLIANT
          aggregation of plan.py:350-351; coverage fields None; assessment_status=LEGACY_UNMEASURED;
          empty result list ⇒ overall_compliant False."""
      def fallback_detection_prompt(self) -> Optional[str]:
          """Prompt for the LLM detector; None ⇒ generic prompt."""

  # planogram/types/legacy_adapter.py  (new)
  async def legacy_perceive(handler: AbstractPlanogramType, image: Image.Image, image_id: str,
                            ctx: CycleContext) -> PerceptionResult:
      """Steps 5-17 of today's run() (plan.py:98-343), unchanged in order and guards."""
  ```

### Module 15: `run()` template
- **Path**: `planogram/plan.py`
- **Responsibility**: shared orchestration only — load (full-resolution,
  untouched, unless `type_handler.uses_enhanced_image`), build `CycleContext`,
  perceive per image, fallback check, identify, compare, render per image,
  assemble. `image` may be one image or a sequence; `image_id` one id or a
  matching sequence (default ids `img0..imgN`; the output filename suffix rule
  `_sfx` of `plan.py:82` is kept for the single-image call). Observations and
  boxes are keyed by `image_id`; boxes of one photo are never drawn on another.
  Singular `rendered_image` / `overlay_path` represent the **first successfully
  processed** image; all-failed ⇒ both `None` and the assessment is
  inconclusive. One failed photo is isolated and recorded in `errors`. Executor
  and semaphore are created per run and closed in `finally` (cancellation-safe).
- **Depends on**: M5, M7, M8, M10, M12, M14
- **Interface Skeleton**:
  ```python
  # planogram/plan.py  (modifies :45-69, replaces :71-370)
  ImageInput = Union[str, Path, Image.Image]
  def __init__(self, planogram_config: PlanogramConfig, llm: Any = None,
               llm_provider: Union[str, _Unset] = UNSET, llm_model: Union[str, None, _Unset] = UNSET,
               *, cpu_workers: int = 2, llm_concurrency: int = 4, llm_timeout: float = 120.0,
               vision_cache_dir: Optional[Path] = None, **kwargs: Any): ...
  async def run(self, image: Union[ImageInput, Sequence[ImageInput]],
                output_dir: Optional[Union[str, Path]] = None,
                image_id: Optional[Union[str, Sequence[str]]] = None, **kwargs: Any) -> Dict[str, Any]:
      """Returns the 8 legacy keys + the additive keys of §2. Raises ValueError when image_id is a
      sequence whose length differs from image."""
  ```

### Module 16: `InkWall`
- **Path**: `planogram/types/ink_wall.py`, `planogram/types/__init__.py`, `planogram/plan.py` (`_PLANOGRAM_TYPES`)
- **Responsibility**: price-tag-anchored type — `PRICE_TAG_PROFILE` → tag rows →
  slots above tags (gap-filled + untagged bottom row) → `STRIPS` identify →
  descriptor identity (`family / xl / colors / pack`, identifiers, aliases via
  `rapidfuzz`) → optional price compliance when the definition carries `price`.
  `requires_slots_definition = True`; implements none of the legacy methods.
- **Depends on**: M7, M8, M9, M11, M12, M13, M14, M15
- **Interface Skeleton**:
  ```python
  class InkWall(AbstractPlanogramType):
      identify_strategy = IdentifyStrategy.STRIPS
      requires_slots_definition = True
      min_usable_shapes = 8
      uses_enhanced_image = False
      async def perceive(self, image, image_id, ctx) -> PerceptionResult: ...
      async def identify(self, image, perception, ctx) -> IdentificationResult: ...
      async def compare(self, perceptions, identifications, ctx) -> ComparisonResult: ...
  def resolve_identity(identification: Identification, definition: SlotsDefinition
                       ) -> Tuple[Optional[str], List[str]]:
      """(facing product id or None, candidate ids). Reference: plancheck/reference.py:255."""
  ```

### Module 17: `ProductOnShelves` migration
- **Path**: `planogram/types/product_on_shelves.py`
- **Responsibility**: override the three hooks. Perception per
  `perception_mode` (`"llm_detector"` default until the spike passes; `"cv"`
  uses the accepted profiles for product bodies, boxes, fact tags and the
  backlit/poster zone + shelf edges). `FULL_IMAGE` identify. Compare through
  Module 13 with rule outcomes produced by the existing, characterized logic:
  `_check_illumination`, `TextMatcher` text requirements, promotional aliasing
  (`_PROMO_TYPES`), brand check, `_calculate_visual_feature_match`.
  `requires_slots_definition = True`. The legacy methods stay in the file (the
  fallback detector reuses `_detect_legacy`'s prompt) but are no longer the
  run path.
- **Depends on**: M1 (profiles/outcome), M3, M6, M13, M14, M15
- **Interface Skeleton**:
  ```python
  class ProductOnShelves(AbstractPlanogramType):          # modifies :35-1683
      identify_strategy = IdentifyStrategy.FULL_IMAGE
      requires_slots_definition = True
      min_usable_shapes = 3
      uses_enhanced_image = False
      DEFAULT_PERCEPTION_MODE: ClassVar[Literal["cv", "llm_detector"]] = "llm_detector"
      async def perceive(...) -> PerceptionResult: ...
      async def identify(...) -> IdentificationResult: ...
      async def compare(...) -> ComparisonResult: ...
      async def _evaluate_rules(self, bindings: Sequence[RuleBinding], images: Dict[str, Image.Image],
                                identifications: Sequence[IdentificationResult], ctx: CycleContext
                                ) -> Dict[str, RuleOutcome]: ...
  ```

### Module 18: Handler
- **Path**: `handlers/planogram_compliance.py`, `packages/ai-parrot/tests/handlers/test_planogram_compliance.py`
- **Responsibility**: `_build_planogram_config` hydrates `slots_definition` and
  `llm_backend` and tolerates `NULL` prompts; the handler no longer imports or
  builds `GoogleGenAIClient` (`:144-146`) — it constructs
  `PlanogramCompliance(planogram_config=_config)` and lets the backend resolve;
  response adds `assessment_status`, `coverage`, `errors`. A construction
  `ValueError` (missing/invalid slots) becomes a failed job with the message,
  not a 500.
- **Depends on**: M5, M15
- **Interface Skeleton**:
  ```python
  def _build_planogram_config(self, row: dict) -> PlanogramConfig:     # modifies :296-333
      """Additionally reads row.get("slots_definition"), row.get("llm_backend")."""
  # response dict (:161-166, :179) gains: "assessment_status", "coverage", "errors"
  ```

### Module 19: Config migration tooling + runbook
- **Path**: `planogram/migration.py` (new; `python -m parrot_pipelines.planogram.migration`),
  `docs/pipelines/planogram-cycle-migration.md` (new)
- **Responsibility**: offline **candidate** conversion of an existing
  ProductOnShelves config dict or exported DB row into slots JSON +
  `rule_bindings` + a validation report — never touching the database and never
  the original config (kept for review/rollback). Fixed quantities
  (`quantity_range == (n, n)`) may seed *n* candidate facings; ranges and
  ambiguous positions are reported for human resolution — an exact layout is
  never invented, and one fixture's sample JSON is never copied to other
  configs. Extracts nested `illumination_required`, `illumination_penalty`,
  `text_requirements`, `visual_features` from `shelves[].products[]` into
  bindings. Read-only DB preflight listing active migrated-type rows with
  missing/invalid `slots_definition` or dangling bindings. Runbook: ALTER →
  review + backfill → preflight → deploy → rollback, plus the score-semantics
  change (weight normalisation, denominators, inconclusive ⇒ `False`).
- **Depends on**: M5, M9
- **Interface Skeleton**:
  ```python
  class ConversionReport(BaseModel): candidate: Dict[str, Any]; bindings: List[Dict[str, Any]]
                                     unresolved: List[str]; warnings: List[str]
  def convert_config(planogram_config: Dict[str, Any], *, planogram_type: str) -> ConversionReport: ...
  class PreflightRow(BaseModel): config_name: str; planogram_type: str; ok: bool; problems: List[str]
  async def preflight(dsn: str) -> List[PreflightRow]:
      """SELECT-only (asyncdb, same driver the handler uses)."""
  ```

### Module 20: Descriptor assistant
- **Path**: `examples/planogram/descriptor_assistant.py`, `.gitignore` negation
- **Responsibility**: CLI that proposes `display_name / family / xl / colors /
  pack / identifiers / aliases` per position from the **POG PDF only**, with page
  evidence, through `VisionAdapter`. Never proposes `price`. Writes a *proposal*
  file next to the definition for human review; never overwrites the definition.
- **Depends on**: M9, M10
- **Interface Skeleton**:
  ```python
  async def propose_descriptors(pdf: Path, definition: SlotsDefinition, adapter: VisionAdapter
                                ) -> Dict[str, DescriptorProposal]:
      """facing_id → proposal (descriptors without price, page number, evidence text)."""
  ```

### Module 21: Backend benchmark
- **Path**: `examples/planogram/backend_benchmark.py`, `.gitignore` negation
- **Responsibility**: runs the same photos through each backend
  (`google:gemini-3.5-flash`, `anthropic:claude-sonnet-5`; availability verified
  at execution time, unavailable backends reported explicitly) and reports per
  photo and aggregated: raw confidence distribution, evidence quality, coverage,
  compliance (lenient + strict), object counts (CV shapes / identified /
  LLM-added), errors, per-stage duration. Pins definition/image hashes,
  prompt/schema versions, provider/model ids, parameters, package versions,
  concurrency and retry limits. Cold uncached runs reported separately from
  cache hits; repeated runs expose variability. No ground truth, no pass bar, no
  accuracy/recall wording.
- **Depends on**: M16, M17
- **Interface Skeleton**:
  ```python
  async def run_benchmark(photos: Sequence[Path], config: PlanogramConfig, backends: Sequence[str],
                          *, repeats: int = 3, out: Path) -> BenchmarkReport: ...
  ```

### Module 22: Registry, exports, docs
- **Path**: `parrot_pipelines/__init__.py`, `planogram/__init__.py`,
  `docs/pipelines/planogram-compliance-cycle.md` (new)
- **Responsibility**: `PIPELINE_REGISTRY` gains `InkWall`, `ProductCounter`,
  `EndcapNoShelvesPromotional`, `EndcapBacklitMultitier`; lazy export of
  `InkWall`; developer doc "adding a planogram type" (shape profile + anchoring
  rule + descriptor vocabulary).
- **Depends on**: M16

---

## 4. Test Specification

All tests are offline: synthetic images drawn with OpenCV/Pillow, a
`FakeVisionClient`, no network, no real photos, no `planogram_page1.json`.

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_price_tag_profile_finds_synthetic_tags` | M1 | bright landscape labels on a dark wall are proposed; distractor blobs are not |
| `test_propose_shapes_scales_back_to_source` | M1 | coordinates are in source pixels when `work_width` < image width |
| `test_spike_evaluator_one_to_one_matching` | M1 | IoU 0.5 matching yields expected precision/recall on a hand-built case |
| `test_credit_policy_defaults_and_validation` | M2 | §2 table; `strict > lenient` rejected |
| `test_compliance_result_assessment_is_optional` | M2 | legacy construction of `ComplianceResult` without `assessment` still validates |
| `test_pos_basic_score_and_status_characterization` | M3 | pins `n_matched / n_expected`, threshold on `basic_score`, `MISSING` rule |
| `test_pos_weights_sum_quirk_characterization` | M3 | non-header defaults 0.8/0.1/0.2 clamp to 1.0 (today's behaviour) |
| `test_pos_zone_only_shelf_characterization` | M3 | zero expected ⇒ `NON_COMPLIANT`, score 0.3 (today's behaviour) |
| `test_pos_illumination_penalty_characterization` | M3 | nested `illumination_required` / `illumination_penalty` (default 0.5), multiplier on combined score |
| `test_pos_header_text_requirements_characterization` | M3 | endcap text score, mandatory flag, "no promos on header" path |
| `test_pos_fact_tag_ocr_and_corroboration_characterization` | M3 | `_ocr_fact_tags` row crops + `_corroborate_products_with_fact_tags` in-place edits |
| `test_pos_assign_products_to_shelves_characterization` | M3 | centre vs `use_y1_assignment` |
| `test_legacy_run_orchestration_order` | M3 | the 20 steps of §6 happen in order with a fake client, incl. promo OCR and injections |
| `test_anthropic_ask_to_image_no_memory_skips_history` | M4 | `no_memory=True` ⇒ no replayed history in the payload |
| `test_anthropic_ask_to_image_model_resolution` | M4 | explicit > client model > `SONNET_5` |
| `test_anthropic_detect_objects_shape` | M4 | pixel `[x1,y1,x2,y2]`, degenerate boxes dropped, bad JSON ⇒ `[]` |
| `test_backend_precedence_matrix` | M5 | every row of the §2 precedence, incl. provider switch without model and sentinel vs `"google"` |
| `test_planogram_config_optional_prompts_and_new_fields` | M5 | prompts optional; `slots_definition` dict/path; invalid `llm_backend` rejected |
| `test_no_hardcoded_models_or_roi_client` | M6 | grep-style test: zero matches of the §6 worklist regex (except `no_memory`) under `parrot_pipelines/` |
| `test_group_rows_and_gap_filled_slots` | M7 | rows ordered, `slot_index` 1..n, `inferred=True` on gap fills |
| `test_strip_norm_roundtrip_and_bounds` | M7 | `from_strip_norm(to_strip_norm(b)) ≈ b`; non-finite / out-of-range raises |
| `test_cpu_executor_bounded_and_cancellable` | M7 | never more than `max_workers`; cancellation leaves no orphan task |
| `test_ocr_reader_unavailable_is_silent` | M8 | import failure ⇒ `available=False`, `("", 0.0)` |
| `test_slots_definition_validation_errors` | M9 | non-1..n slots, duplicate ids, conflicting descriptors, zero described, empty shelf |
| `test_slots_definition_accepts_page1_layout` | M9 | synthetic file in the `planogram_page1.json` layout normalises to stable ids |
| `test_rule_bindings_reject_dangling_and_ambiguous` | M9 | never silently dropped |
| `test_vision_adapter_repair_retry_then_error` | M10 | one repair retry, then `VisionError` |
| `test_vision_adapter_cache_is_schema_aware` | M10 | schema change ⇒ cache miss |
| `test_vision_adapter_passes_resolved_model_and_rejects_unknown_kwargs` | M10 | per-provider kwargs; client without `ask_to_image` fails fast |
| `test_membership_ignores_expected_sku_and_handles_missing_anchors` | M11 | no anchors ⇒ `uncertain`, perception continues |
| `test_added_shapes_validation` | M12 | out-of-bounds / zero-area / duplicate / wrong-strip additions rejected; accepted ones get pipeline ids + `llm_added` |
| `test_unknown_and_missing_existing_ids` | M12 | unknown id ⇒ error; missing known id ⇒ uncertain |
| `test_failed_strip_is_isolated` | M12 | its slots uncertain, `errors` populated, others identified |
| `test_registration_partial_view_not_visible` | M13 | 3 of 6 shelves visible ⇒ rest `not_visible`, never `empty` |
| `test_registration_ambiguous_stays_unassessed` | M13 | tie ⇒ no assignments |
| `test_scoring_fixture_*` (7 fixtures below) | M13 | the pinned scoring examples |
| `test_projection_statuses` | M13 | COMPLIANT / MISSING / MISPLACED / NON_COMPLIANT rules of §2; unseen never in `missing_products` |
| `test_validate_contract_rejects_incomplete_type` | M14 | neither contract complete ⇒ `TypeError` at construction |
| `test_legacy_type_missing_prompts_fails_at_construction` | M14 | clear `ValueError` |
| `test_legacy_adapter_empty_results_not_compliant` | M14 | the single intended legacy deviation |
| `test_run_preserves_eight_keys_for_every_type` | M15 | all six types + `InkWall` |
| `test_run_multi_image_renders_and_failures` | M15 | per-image `renders`; first-success singular keys; all-failed ⇒ `None` + inconclusive |
| `test_run_fallback_sets_detection_source_llm` | M15 | below threshold ⇒ LLM detector; membership still applied |
| `test_run_uses_untouched_image_for_migrated_types` | M15 | `_enhance_image` not called; called for legacy types |
| `test_ink_wall_end_to_end_synthetic` | M16 | synthetic wall, fake LLM ⇒ expected statuses and scores |
| `test_pos_migrated_end_to_end_synthetic` | M17 | both `perception_mode`s; illumination/text rules through bindings |
| `test_pos_missing_slots_definition_fails_construction` | M17 | message points at the runbook |
| `test_handler_response_additive_fields` | M18 | old fields intact + `assessment_status`, `coverage`, `errors`; no `GoogleGenAIClient` import |
| `test_convert_config_fixed_quantities_and_ranges` | M19 | fixed ⇒ candidates; ranges ⇒ `unresolved`; nested illumination/text extracted into bindings |
| `test_descriptor_assistant_never_proposes_price` | M20 | `price` absent even when the fake LLM returns one |
| `test_benchmark_report_columns_and_unavailable_backend` | M21 | pinned metadata present; unavailable backend reported, not raised |

**Pinned scoring fixtures** (M13 — resolve the brainstorm's "scoring examples" item):

| Fixture | Setup | Expected |
|---|---|---|
| `zero_evidence` | no observations at all | every facing `not_assessed`; scores 0.0; coverage 0.0; `inconclusive`; `overall_compliant=False` |
| `partial_identity` | 10 facings: 6 `match`, 4 `variant_unresolved` | `facing_lenient=0.8`, `facing_strict=0.6`, coverage 0.6, `inconclusive`, shelf `NON_COMPLIANT` |
| `incomplete_definition` | 10 facings, 4 undescribed and unreadable | `definition_coverage=0.6`; the 4 stay unresolved; an independently readable identifier resolves one |
| `conflicting_photos` | two photos, incompatible admissible identities for one facing | `conflict`, credits 0/0, both provenances kept; an unreadable second photo does **not** create a conflict |
| `zone_only_shelf` | header shelf: 0 facings, required backlit zone, 2 text requirements, illumination rule | no division by zero; `product_term = zone_score`; illumination mismatch multiplies once |
| `full_llm_fallback` | all shapes `source="llm"`, all matched with admissible evidence | compliance 1.0, `complete`, `overall_compliant=True`, `evidence_quality=0.5`, `detection_source="llm"` |
| `weight_normalisation` | non-header shelf, default weights, `facing_lenient=0.9`, text 1.0, visual 1.0 | `(0.9·0.8+0.1+0.2)/1.1 = 0.927…` — not the legacy clamped 1.0 |

### Integration Tests
| Test | Description |
|---|---|
| `test_cycle_runs_on_google_and_anthropic_fakes` | same synthetic run with fakes exposing each provider's kwarg surface ⇒ identical structure, `resolved_backend` recorded |
| `test_legacy_types_unchanged_through_new_run` | the four unmigrated types produce the results pinned by M3 through the new `run()` |
| `test_alter_script_is_idempotent_text` | the ALTER script contains only `IF NOT EXISTS` / `DROP NOT NULL` statements (static check; no DB needed) |

### Test Data / Fixtures
```python
@pytest.fixture
def synthetic_ink_wall() -> np.ndarray:
    """Dark wall, 3 rows × 8 bright landscape labels, one gap, one untagged bottom row."""

@pytest.fixture
def synthetic_slots_definition() -> dict:
    """3 shelves × 8 facings, stable ids, 20 described / 4 undescribed, one header zone + bindings."""

@pytest.fixture
def fake_vision_client() -> FakeVisionClient:
    """Queue-driven fake (M3 conftest)."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

**Compatibility**
- [ ] `PlanogramCompliance(planogram_config=..., llm=...)` and `await pipeline.run(image, output_dir=..., image_id=...)` work unchanged for a single image.
- [ ] `run()` returns all eight existing keys for every planogram type; every new key is additive.
- [ ] `plan.py` contains no ROI-first orchestration and no flag that re-enables it.
- [ ] The four unmigrated types produce, through the new `run()`, the per-shelf results pinned by the Module 3 characterization tests; their `assessment_status` is `"legacy_unmeasured"` and coverage fields are `None`.
- [ ] A type with an incomplete contract is rejected at construction (`TypeError`); a legacy type without its prompts and a migrated type without a valid `slots_definition` fail at construction with a `ValueError` naming the migration runbook. There is no implicit runtime conversion and no hidden old-cycle switch.
- [ ] Handler response keeps `rendered_image_base64`, `content_type`, `overall_compliant`, `overall_compliance_score`, `shelf_results` and adds `assessment_status`, `coverage`, `errors`. The handler stays single-file.
- [ ] `ComplianceStatus` is unchanged; `ComplianceResult` only gains the optional `assessment` field.

**Cycle**
- [ ] `planogram_type="ink_wall"` constructs and runs end-to-end on the synthetic wall.
- [ ] `ProductOnShelves` runs the new cycle in both `perception_mode`s; its class default is `"llm_detector"` unless the spike report records passed gates.
- [ ] Migrated types perceive, OCR and crop from the **untouched full-resolution** image; `_enhance_image` runs only on the legacy adapter path.
- [ ] Usable on-fixture shapes below the type threshold trigger the LLM detector; `detection_source="llm"`; membership validation still applies; off-fixture counts cannot suppress the fallback; a failed fallback yields `not_assessed` facings and a populated `errors`, never an empty silent result.
- [ ] The identify strategy is declared by the type (`FULL_IMAGE` | `STRIPS`).
- [ ] LLM-added shapes are accepted only through validated `added_shapes`, get pipeline-owned ids and `source="llm_added"`; `raw_confidence` is never modified.
- [ ] Only `on_fixture` observations enter registration and scoring; expected-SKU agreement never establishes membership; missing anchors do not stop perception.
- [ ] `run(image=[...])` merges several photos per facing after registration; per-image `renders`; no box from one photo is drawn on another; all-failed ⇒ `rendered_image`/`overlay_path` are `None` and the assessment is inconclusive.
- [ ] One failed strip or photo is isolated and recorded in `errors`.

**Scoring**
- [ ] The seven pinned scoring fixtures pass with the exact values of §4.
- [ ] All expected facings stay in the denominators; `coverage` is global over facings; `overall_compliance_score` is the unweighted mean of per-shelf scores.
- [ ] `overall_compliant` is `True` only when `assessment_status == "complete"` and every shelf is `COMPLIANT`; an empty result list is never a pass.
- [ ] Evidence weights affect only `evidence_quality`; a full LLM fallback can reach compliance 1.0.
- [ ] Unseen products never appear in `missing_products`.

**Configuration & providers**
- [ ] `PlanogramConfig` accepts `slots_definition` (dict or path) and `llm_backend`; `roi_detection_prompt` / `object_identification_prompt` are optional.
- [ ] `table.sql` and the idempotent `alter_planograms_configurations_feat574.sql` add `slots_definition JSONB NULL`, `llm_backend TEXT NULL` and drop `NOT NULL` on both prompts; the ALTER script ships as package data.
- [ ] The full backend precedence matrix is tested; the resolved backend is recorded in the result; a provider switch without a model never inherits the other provider's model id.
- [ ] Zero matches under `packages/ai-parrot-pipelines/src/parrot_pipelines/` for `model="gemini`, `roi_client`, `GoogleGenAIClient`.
- [ ] `AnthropicClient.ask_to_image` accepts `no_memory`; its effective default model is `ClaudeModel.SONNET_5` and never overrides a caller's or client's selection; `AnthropicClient.detect_objects` exists with Google's positional signature and return-dict shape.
- [ ] A client without `ask_to_image` fails fast with a clear error.
- [ ] Slots definition validation rejects: non-`1..n` slot sequences, duplicate ids, conflicting descriptors for one SKU, zero described positions, shelves with neither facings nor zones, dangling/ambiguous rule bindings. Undescribed SKUs are listed, not fatal.

**Packaging & execution**
- [ ] `ai-parrot-pipelines[planogram]` installs RapidOCR; without it the pipeline runs and reports `ocr_available=False`; no module imports `rapidocr`/`onnxruntime` at import time.
- [ ] `numpy`, `pillow`, `rapidfuzz` are declared directly; OpenCV remains a hard dependency.
- [ ] No blocking CV/OCR/encoding call runs on the event loop (bounded process executor); blocking file I/O goes through `asyncio.to_thread`; executor and semaphore are released on success, failure and cancellation.
- [ ] No `requests` / `httpx` / `print`; `ruff check` passes (TID251); Google-style docstrings and type hints on all new code.

**Deliverables**
- [ ] Spike report committed at `docs/pipelines/planogram-perception-spike.md` with per-profile / per-photo precision and recall, tested conditions, off-fixture admissions, accepted profiles and the pass / fail / inconclusive outcome; no photo or manual annotation is committed.
- [ ] Migration utility emits candidate slots JSON + bindings + report without touching the DB or the original config; read-only preflight lists unresolved rows; runbook covers ALTER → backfill → preflight → deploy → rollback and the score-semantics change.
- [ ] Descriptor assistant works from the POG PDF only and never proposes `price`.
- [ ] Backend benchmark produces the pinned, unlabelled report for `gemini-3.5-flash` vs `claude-sonnet-5` and makes no accuracy/recall claim.
- [ ] `examples/planogram/plancheck/` is byte-identical to `dev` at branch point.
- [ ] `PIPELINE_REGISTRY` lists `InkWall` and the three previously missing types.
- [ ] All new and characterization tests pass offline:
  `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src:packages/ai-parrot-client-anthropic/src pytest packages/ai-parrot-pipelines/tests packages/ai-parrot-client-anthropic/tests/unit/test_vision_parity.py packages/ai-parrot/tests/handlers/test_planogram_compliance.py tests/pipelines -v`

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> Re-verified against `dev` @ `dfd1155bd` on 2026-09-18 (every brainstorm anchor
> re-read; deviations from the brainstorm are marked **Δ**).

Paths are relative to `packages/ai-parrot-pipelines/src/parrot_pipelines/`
unless they start with `packages/` or `examples/`.

### Verified Imports
```python
from parrot_pipelines.planogram import PlanogramCompliance, AbstractPlanogramType   # planogram/__init__.py:4-22 (lazy __getattr__ :12-22)
from parrot_pipelines.planogram.types import (AbstractPlanogramType, ProductOnShelves, GraphicPanelDisplay,
    ProductCounter, EndcapNoShelvesPromotional, EndcapBacklitMultitier)             # types/__init__.py:2-16 (eager)
from parrot_pipelines.models import PlanogramConfig, EndcapGeometry                 # models.py:29, :12
from parrot_pipelines.planogram.grid import (AbstractGridStrategy, CellResultMerger, DetectionGridConfig,
    GridCell, GridDetector, GridType, HorizontalBands, NoGrid, get_strategy)
from parrot.models.detections import (Detection, Detections, DetectionBox, IdentifiedProduct, ShelfRegion,
    ShelfProduct, ShelfConfig, PlanogramDescription, TextRequirement, AdvertisementEndcap)  # detections.py
from parrot.models.compliance import (ComplianceResult, ComplianceStatus, TextComplianceResult,
    BrandComplianceResult, TextMatcher)                                             # compliance.py:32,9,17,25,55
from parrot.clients.factory import LLMFactory                                       # packages/ai-parrot/src/parrot/clients/factory.py:163
from parrot.conf import PLANOGRAM_FOLDER, DEFAULT_LLM_MODEL                         # conf.py:116, :443 (fallback "gemini-flash-latest")
from parrot.pipelines.planogram.plan import PlanogramCompliance                     # core back-compat shim (star re-export)
from parrot.clients.anthropic.models import ClaudeModel                             # .../anthropic/models.py:4 (enum.Enum)
```

### Existing Class Signatures
```python
# planogram/plan.py  (485 lines)
class PlanogramCompliance(AbstractPipeline):                                   # :24-485
    _PLANOGRAM_TYPES = {...}                                                   # :37-43 (5 entries, no ink_wall)
    def __init__(self, planogram_config: PlanogramConfig, llm: Any = None, llm_provider: str = "google",
                 llm_model: Optional[str] = None, **kwargs: Any)               # :45-69; ValueError unknown type :66-68
    # sets: planogram_config :54, left/right_margin_ratio :57-58, reference_images :60, _type_handler :69
    async def run(self, image: Union[str, Path, Image.Image], output_dir: Optional[Union[str, Path]] = None,
                  image_id: Optional[str] = None, **kwargs) -> Dict[str, Any]  # :71-370
    def render_evaluated_image(self, image: Union[str, Path, Image.Image], *,
        shelf_regions: Optional[List[ShelfRegion]] = None, detections: Optional[List[DetectionBox]] = None,
        identified_products: Optional[List[IdentifiedProduct]] = None, mode: str = "identified",
        show_shelves: bool = True, save_to: Optional[Union[str, Path]] = None) -> Image.Image   # :376-485 (SYNC;
        #   `detections` and `mode` are accepted but unused; disk write :479-483)

# run() TODAY — the legacy sequence the adapter must preserve (Module 3 pins it, Module 14 moves it):
#  1 :82-83   _sfx = f"_{image_id}" if image_id else ""
#  2 :88      img = self.open_image(image)            (enhancement is INSIDE open_image, abstract.py:82)
#  3 :89      planogram_description = self.planogram_config.get_planogram_description()
#  5 :98-102  endcap, ad, brand, panel_text, raw_dets = await handler.compute_roi(img)   bare except → log only
#  6 :104-130 optional debug overlay debug_step1_roi{_sfx}.png
#  7 :132-138 identified_products, shelf_regions = await handler.detect_objects(img, roi=endcap, macro_objects=None)
#             Δ detect_objects_roi is NEVER called from run()
#  9 :145-157 _cfg_visuals_by_name from planogram_description.shelves[*].products[*].visual_features
# 10 :159-170 _cfg_text_reqs_by_name from RAW planogram_config["shelves"][*]["products"][*]["text_requirements"]
# 11 :172-264 promotional OCR loop: `async with self.roi_client as client` :210;
#             client.ask_to_image(image=p_img, prompt=ocr_prompt, model="gemini-3.5-flash", no_memory=True,
#             max_tokens=1024) :211-216; forces product_type="promotional_graphic" :250; brand check :252-262
# 12 :266-278 hasattr(handler, "_generate_virtual_shelves") → REPLACES shelf_regions :273
# 13 :281-283 planogram_config["use_fact_tag_boundaries"] → handler._refine_shelves_from_fact_tags(...)  (no hasattr guard)
# 14 :286-290 hasattr "_assign_products_to_shelves" (use_y1_assignment=use_fact_tag_boundaries)
# 15 :293-304 hasattr "_ocr_fact_tags" → hasattr "_corroborate_products_with_fact_tags"
# 16 :307-324 poster text injection: IdentifiedProduct(product_type="text_overlay", product_model="poster_text",
#             shelf_location="header", visual_features=[f"ocr:{content}"])
# 17 :326-343 brand logo injection: IdentifiedProduct(product_type="brand_logo", shelf_location="header")
# 18 :345-351 compliance_results = handler.check_planogram_compliance(...)   (SYNC, not awaited)
#             overall_score = mean(r.compliance_score)  :350
#             overall_compliant = all(status == COMPLIANT)  :351      Δ NO numeric global threshold exists;
#             empty results ⇒ score 0.0 but overall_compliant True  :347-348
# 19 :353-359 render → compliance_render{_sfx}.png
# 20 :361-370 return dict: step3_compliance_results, compliance_results (same list), overall_compliance_score,
#             overall_compliant, identified_products, shelf_regions, rendered_image, overlay_path

# planogram/types/abstract.py  (478 lines)
class AbstractPlanogramType(ABC):                                               # :30-478
    def __init__(self, pipeline: "PlanogramCompliance", config: "PlanogramConfig") -> None   # :48-55 (pipeline, config, logger)
    @abstractmethod async def compute_roi(self, img: Image.Image) -> Tuple[Optional[Tuple[int,int,int,int]],
        Optional[Any], Optional[Any], Optional[Any], List[Any]]                 # :58-76
    @abstractmethod async def detect_objects_roi(self, img: Image.Image, roi: Any) -> List[Detection]   # :79-95
    @abstractmethod async def detect_objects(self, img: Image.Image, roi: Any, macro_objects: Any
        ) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]                  # :98-113
    @abstractmethod def check_planogram_compliance(self, identified_products: List[IdentifiedProduct],
        planogram_description: Any) -> List[ComplianceResult]                   # :116-129  (SYNC)
    @staticmethod def _extract_illumination_state(features: List[str]) -> Optional[str]      # :132-149
    async def _check_illumination(self, img, zone_bbox=None, roi=None, planogram_description=None
        ) -> Optional[str]                                                      # :151-249; roi_client :234; model literal :238
    @staticmethod def _base_model_from_str(s: str, brand: str = None, patterns: Optional[List[str]] = None) -> str  # :252-324
    def _cluster_fact_tag_rows(self, fact_tags: List[Any], cluster_threshold: int = 50) -> List[int]   # :330-357
    def _refine_shelves_from_fact_tags(self, shelf_regions, identified_products) -> List[ShelfRegion]  # :359-446
    def get_render_colors(self) -> Dict[str, Tuple[int,int,int]]                # :448-462
    def get_grid_strategy(self) -> "AbstractGridStrategy"                       # :464-478 (NoGrid default)
# module constants: _ILLUMINATION_FEATURE_PREFIX :9 (re-declared :27), _DEFAULT_ILLUMINATION_PENALTY = 1.0 :10

# planogram/types/product_on_shelves.py  (1683 lines)
class ProductOnShelves(AbstractPlanogramType):                                  # :35-1683
    async def compute_roi(self, img)                                            # :58-82  (→ _find_poster :801-971)
    async def detect_objects_roi(self, img, roi) -> List[Detection]             # :84-103 (returns [])
    def get_grid_strategy(self)                                                 # :105-117
    async def detect_objects(self, img, roi, macro_objects)                     # :119-222 (grid :224-260 vs _detect_legacy :262-382)
    def check_planogram_compliance(self, identified_products, planogram_description)  # :384-795 (SYNC)
    def _canonical_expected_key(self, sp, brand, patterns=None) -> Tuple[str, str]          # :973-986
    def _canonical_found_key(self, p, brand, patterns=None) -> Tuple[str, str, float]       # :988-1021
    def _looks_like_box(self, visual_features) -> bool                          # :1023-1035
    def _calculate_visual_feature_match(self, expected_features, detected_features) -> float  # :1052-1119
    def _generate_virtual_shelves(self, roi_bbox: DetectionBox, image_size, planogram) -> List[ShelfRegion]  # :1132-1217
    async def _ocr_fact_tags(self, identified_products, img, planogram_description, shelf_regions=None
        ) -> Dict[str, List[str]]                                               # :1219-1383
    def _corroborate_products_with_fact_tags(self, identified_products, fact_tag_shelf_map,
        planogram_description) -> None                                          # :1385-1492 (in place)
    def _assign_products_to_shelves(self, products, shelves, use_y1_assignment: bool = False)   # :1494-1683
# LLM call sites: llm.detect_objects(image=, prompt=, reference_images=, output_dir=None) :330-335;
#   roi_client.ask_to_image(model="gemini-3.5-flash" :829, no_memory=True, structured_output=Detections, max_tokens=8192) :825-833;
#   roi_client.ask_to_image(model="gemini-3.5-flash" :1361, no_memory=True, max_tokens=128) :1357-1364

# check_planogram_compliance — TODAY's math (what Module 3 pins; §2 defines the migrated formula)
#   _PROMO_TYPES alias set :391-404; raw config read from self.config.planogram_config :411-418
#   brand check = string equality on IdentifiedProduct.brand, one shared result :506-518
#   expected = ShelfProduct entries (skip fact_tag|price_tag|slot) :538-551 — quantity_range/mandatory/position_preference NEVER read
#   matching = greedy 1:1, type-equivalence + substring; NO fuzzy product matching :438-503, :578-616
#   basic_score = n_matched / (n_expected or 1.0) :660      (zero expected ⇒ 0.0)
#   visual_feature_score = mean(matches) or 1.0 :662-664
#   text: only when endcap.enabled and endcap.position == shelf_level :668; score = Σconf(found)/len(all reqs) :711;
#         header with no promos ⇒ overall_text_ok False but text_score stays 1.0 :686-697
#   illumination: RAW dict, nested in shelves[].products[], keyed by (level, product name) :420-436; default penalty 0.5 :436
#   weights: visual_weight = getattr(description,"visual_features_weight",0.2) :745  → field does not exist ⇒ always 0.2
#     header+endcap: product·(endcap.product_weight·0.8) + text·endcap.text_weight + brand·getattr(endcap,"brand_weight",0.0)
#                    + visual·(endcap.product_weight·0.2) :746-753   → brand_weight does not exist ⇒ always 0.0
#     other: Wv = shelf.visual_weight or 0.2; Wt = shelf.text_weight or 0.1; Wp = shelf.product_weight or (1-Wv) :757-764 (sum 1.1)
#   penalty: combined *= max(0, 1 - Σpenalty/(len(expected) or 1)) :772-775;  compliance_score = clamp01 :777
#   status: threshold = shelf_cfg.compliance_threshold (0.8) :717-719, compared with basic_score (not combined) :731,:738;
#           header additionally needs brand_check_ok and overall_text_ok :735-743; MISPLACED never emitted
#   returns one ComplianceResult per planogram_description.shelves entry, config order :538, :780-795

# models.py  (108 lines)
class EndcapGeometry(BaseModel)                                                 # :12-27
class PlanogramConfig(BaseModel):                                               # :29-108 — NO validators today
    planogram_id: Optional[int] = None                                          # :34
    config_name: str = "default_planogram_config"                               # :39
    planogram_type: str = "product_on_shelves"                                  # :44-47
    planogram_config: Dict[str, Any]                                            # :50-52  REQUIRED
    roi_detection_prompt: str                                                   # :55-57  REQUIRED
    object_identification_prompt: str                                           # :60-62  REQUIRED
    reference_images: Dict[str, Union[str, Path, List[str], List[Path], Image.Image]]   # :65-71
    confidence_threshold: float = 0.25                                          # :74
    detection_model: str = "yolo11l.pt"                                         # :79
    endcap_geometry: EndcapGeometry                                             # :84
    detection_grid: Optional[DetectionGridConfig] = None                        # :90-96
    class Config: arbitrary_types_allowed = True                                # :98-100
    def get_planogram_description(self) -> PlanogramDescription                 # :102-108

# abstract.py  (172 lines)
class AbstractPipeline(ABC):                                                    # :13-172
    def __init__(self, llm: Any = None, llm_provider: str = "google", llm_model: Optional[str] = None, **kwargs)  # :16-40
    #   :33-34 llm given ⇒ self.llm_provider = llm.client_name.lower()
    #   :40 self.roi_client = GoogleGenAIClient(model="gemini-3-flash-preview", temperature=0.0, max_retries=2, timeout=20)  UNCONDITIONAL
    def _get_llm(self, provider: str, model: Optional[str] = None, **kwargs) -> Any   # :42-71 (LLMFactory.supported_clients(); ValueError unknown)
    def open_image(self, image_path: Union[Path, Image.Image]) -> Image.Image  # :73-87 (always _enhance_image :82)
    def _enhance_image(self, pil_img, brightness: float = 1.10, contrast: float = 1.20)   # :134-144
    def _downscale_image(self, img, max_side=1024, quality=82) -> Image.Image   # :146-158

# handlers/planogram_compliance.py  (362 lines)
class PlanogramComplianceHandler(BaseView):                                     # :28-362
    # :144-146 lazy import GoogleGenAIClient; llm = GoogleGenAIClient(model=DEFAULT_LLM_MODEL)
    # :147 pipeline = PlanogramCompliance(planogram_config=_config, llm=llm)
    # :148-151 result = await pipeline.run(image=_image_path, output_dir=str(_tmp_dir))
    # reads: overlay_path :156, overall_compliant :162, overall_compliance_score :163, compliance_results :168
    # response: overall_compliant, overall_compliance_score, rendered_image_base64, content_type :161-166; shelf_results :179
    # config: "SELECT * FROM troc.planograms_configurations WHERE config_name = $1 AND is_active = TRUE LIMIT 1" :289
    def _build_planogram_config(self, row: dict) -> PlanogramConfig             # :296-333 (detection_grid never hydrated)

# planogram/grid/merger.py
def _compute_iou(box_a: DetectionBox, box_b: DetectionBox) -> float             # :16   Δ MODULE-LEVEL, not a method
class CellResultMerger:                                                         # :49-177
    def _deduplicate(self, products: List[IdentifiedProduct], iou_threshold: float) -> List[IdentifiedProduct]  # :126-130
# planogram/grid/detector.py:130-135  raw = await self.llm.detect_objects(image=, prompt=, reference_images=, output_dir=None)
# planogram/legacy.py:1473  `async with self.llm as client:` (idiom);  :2282-2287 roi_client + model literal + no_memory

# packages/ai-parrot/src/parrot/models/detections.py   (no model_config anywhere ⇒ extra="ignore")
class DetectionBox(BaseModel)       # :37-60  x1,y1,x2,y2:int; confidence:float(0..1, coerced); class_id; class_name; area; label; ocr_text
class ShelfRegion(BaseModel)        # :62-68  shelf_id, bbox: DetectionBox, level, objects, is_background
class IdentifiedProduct(BaseModel)  # :71-206 detection_id, product_type (req), product_model, brand, confidence (req),
                                    #         visual_features, reference_match, shelf_location, position_on_shelf,
                                    #         advertisement_type, ocr_text, detection_box, extra: Dict[str,str], out_of_place
class ShelfProduct(BaseModel)       # :246-253 name, product_type, quantity_range=(1,1), position_preference, mandatory, visual_features
class ShelfConfig(BaseModel)        # :302-326 level, products, compliance_threshold=0.8 :307, allow_extra_products, position_strict,
                                    #          height_ratio, y_start_ratio, is_background, product_weight/text_weight/visual_weight=None :313-315
class TextRequirement(BaseModel)    # :328-334 required_text, match_type, case_sensitive, confidence_threshold=0.7, mandatory
class AdvertisementEndcap(BaseModel)  # :337-354 enabled, promotional_type, position="header", product_weight=0.8, text_weight=0.2, text_requirements …
class PlanogramDescription(BaseModel) # :364-407 brand, category, aisle, shelves, advertisement_endcap, global_compliance_threshold=0.8,
                                    #          weighted_scoring (DEAD — never read), model_normalization_patterns
# packages/ai-parrot/src/parrot/models/compliance.py   (208 lines, no model_config)
class ComplianceStatus(str, Enum)   # :9-14  COMPLIANT | NON_COMPLIANT | MISSING | MISPLACED
class ComplianceResult(BaseModel)   # :32-52 shelf_level, expected_products, found_products, missing_products, unexpected_products,
                                    #        compliance_status, compliance_score (ge=0, le=1), text_compliance_results,
                                    #        brand_compliance_result, text_compliance_score=1.0, overall_text_compliant=True
class TextMatcher                   # :55-208 check_text_match(required_text, visual_features, match_type="contains", case_sensitive=False,
                                    #         confidence_threshold=0.6, ngram_range=(1,3), min_token_len=2) :118-208

# Provider clients — ask_to_image is NOT on AbstractClient (duck-typed per satellite)
# packages/ai-parrot-client-google/src/parrot/clients/google/client.py:4999-5150
async def ask_to_image(self, prompt: str, image: Union[Path, bytes], reference_images=None,
    model: Union[str, GoogleModel] = None, max_tokens=None, temperature=None, structured_output=None,
    count_objects: bool = False, history=None, no_memory: bool = False) -> AIMessage
    # model None ⇒ self.model or GEMINI_2_5_FLASH :5015-5017; no_memory only gates history :5026
# packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py:1234-1378  (class GoogleAnalysis :54, mixin)
async def detect_objects(self, image: Union[str, Path, Image.Image], prompt: str,
    reference_images: Optional[List[...]] = None, output_dir: Optional[Union[str, Path]] = None) -> List[Dict[str, Any]]
    # model HARD-CODED GoogleModel.GEMINI_3_FLASH_PREVIEW ("gemini-3.5-flash", google/models.py:35) :1264,:1276 — no model kwarg
    # item: {"label", "box_2d": [x1,y1,x2,y2] ORIGINAL-image pixels (from 0-1000 [ymin,xmin,ymax,xmax]) :1319-1341,
    #        "confidence" (default 1.0), "mask_image", "overlay_image", **passthrough}; parse failure ⇒ []
# packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py:1307-1483   (class AnthropicClient(AbstractClient) :75)
async def ask_to_image(self, prompt: str, image: Union[Path, bytes, Image.Image], reference_images=None,
    model: Union[ClaudeModel, str] = ClaudeModel.SONNET_4, max_tokens=None, temperature=None, structured_output=None,
    count_objects: bool = False, history=None, system_prompt: Optional[str] = None, context_1m: bool = False) -> AIMessage
    # history: messages = self._format_history(history or ()) :1352; no memory read/write (FEAT-524 :1461)
    # structured output = JSON system prompt + _parse_structured_output (NOT tool-use) :1390-1456
    # images: _encode_image_for_claude :1262-1305 (Path | bytes | PIL.Image → base64 block)
def _resolve_model(self, model) -> str                                          # :256-273  model → self.model → self.default_model → backend.translate_model
# packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/models.py
class ClaudeModel(Enum):  SONNET_5 = "claude-sonnet-5"  # :15      SONNET_4 = "claude-sonnet-4-20250514"  # :33
# packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/claude_agent.py:1036-1040  ask_to_image → NotImplementedError
# packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:                                                               # :163
    @staticmethod def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]   # :174   ("provider:model" → split(":", 1))
    @staticmethod def supported_clients() -> Dict[str, Any]                     # :203   (a METHOD, not an attribute)
    @staticmethod def create(llm: str, model_args: Optional[Dict[str, Any]] = None,
                             tool_manager: Optional[Any] = None, **kwargs) -> AbstractClient   # :257; unknown provider ⇒ ImportError :296-299
```

```sql
-- table.sql (97 lines; shipped via pyproject.toml:46-47  "parrot_pipelines" = ["py.typed", "*.sql"])
-- CREATE TABLE troc.planograms_configurations (               -- :3
--     planogram_config JSONB NOT NULL,                        -- :13
--     roi_detection_prompt TEXT NOT NULL,                     -- :16
--     object_identification_prompt TEXT NOT NULL,             -- :17
--     reference_images JSONB DEFAULT '{}',                    -- :20
-- GIN index on planogram_config                               -- :56-57
-- Δ there is NO planogram_type column in table.sql, although the handler reads row.get("planogram_type") (:323).
--   Deployed databases evidently have it; this feature does not add it (see §8).
-- A stale duplicate lives at packages/ai-parrot/src/parrot/pipelines/table.sql — NOT touched by this feature.
```

Reference engine — `examples/planogram/plancheck/` (tracked; **algorithmic reference only, never imported**):

```python
# detection.py: _THRESHOLDS :19; find_candidates(image, min_width=0.025, max_width=0.09) :22; group_rows(...) :68; detect_tags(...) :136
# grid.py: build_slots(rows, image_size) :78; strip_box(slots, image_size, pad=0.04) :185; to_strip_norm(box, strip) :229
# prices.py: parse_price :36; TagOcr.__init__ :77, .read(crop) -> str :87 (lazy RapidOCR(); result.txts); read_prices :207
# vision.py: cache_key :45; VisionBackend.__init__ :105, .ask(prompt, images, schema, *, stage, prompt_version) :163;
#            Δ LLMFactory.create call at :138 (brainstorm said :131); Δ ask_to_image lane :220-228 (brainstorm said :213-228)
#            — the lane passes NO history and NO no_memory; capability guard hasattr(...) :148
# identify.py: SUBSTRIP_MAX_SLOTS=8 :29, CLOUD_SPLIT_ABOVE=20 :30; render_strip :73; identify_rows :252
# verify.py: pick_distractors :27; verify_rows :172
# reference.py: load_planogram :30; DESCRIPTOR_FIELDS :96; load_descriptors :142; resolve_identity :255
# registration.py: align_row :93; register_image :197 (strictly increasing shelves only)
# scoring.py: merge_positions :251; shelf_scores :356; summarize :473
# pipeline.py: run_check :159
# examples/planogram/tests/conftest.py: class FakeBackend :187 (queue-per-stage; model for M3's FakeVisionClient)
```

`planogram_page1.json` (git-ignored; structure only): top level
`{"planogram": {...}, "shelves": [...]}`; meta `product_count` (102),
`physical_facing_count` (104), `shelves` (6), `segments` (2); each shelf has
`shelf`, `shelf_number`, `product_count`, `facing_count`, `products` (dict keyed
`"pos <shelf>:<n>"`); each position has `position, segment, segment_number,
slot, segment_slot, product, brand, shelf, facings, confidence, read_method,
notes` + descriptors `display_name, family, xl, colors, pack, identifiers,
aliases, price`. **Only 2 of 102 positions are described today.**

Reference photo for the spike: `examples/planogram/photo_2026-09-18_20-36-30.jpg`
(git-ignored, 1280×955) — Epson EcoTank endcap: luminous backlit header; 3 white
printers on a white riser (low contrast); 3 electronic price tags (white, red
band) under them; 3×2 box stack below; distractor fixtures on both aisles.
Three shape profiles at very different scales; printers need an edge/structure
cue, not a brightness threshold.

**Provider-neutrality worklist** — lines matching
`model="gemini|roi_client|GoogleGenAIClient|llm\.detect_objects|no_memory`
(re-counted 2026-09-18; **Δ 63 lines in 11 files** — the brainstorm's 60/10
omitted `legacy.py`, which also uses `roi_client`):

| File | Lines |
|---|---|
| `planogram/types/endcap_backlit_multitier.py` | 18 |
| `planogram/types/graphic_panel_display.py` | 12 |
| `planogram/types/product_on_shelves.py` | 7 |
| `planogram/types/product_counter.py` | 6 |
| `planogram/types/endcap_no_shelves_promotional.py` | 6 |
| `planogram/types/abstract.py` | 3 |
| `planogram/plan.py` | 3 |
| `planogram/legacy.py` | 3 |
| `abstract.py` | 2 |
| `handlers/planogram_compliance.py` | 2 |
| `planogram/grid/detector.py` | 1 |

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `PlanogramCompliance.run` (new body) | `AbstractPlanogramType.perceive/identify/compare` | awaited hooks on `self._type_handler` | `plan.py:69` |
| `legacy_adapter.legacy_perceive` | `compute_roi`, `detect_objects`, private helpers | same calls / `hasattr` guards as today | `plan.py:98-343` |
| default `compare` | `check_planogram_compliance` | sync call | `plan.py:346` |
| `VisionAdapter.ask` | `client.ask_to_image(prompt, image=, reference_images=, structured_output=, temperature=, max_tokens=, model=, no_memory=)` | duck-typed | google `client.py:4999`; anthropic `client.py:1307` |
| `resolve_backend` | `LLMFactory.parse_llm_string`, `LLMFactory.create` | static calls | `factory.py:174`, `:257` |
| `AbstractPipeline.__init__` | `_get_llm(provider, model)` | existing | `abstract.py:42-71` |
| Module 6 call sites | `async with self.pipeline.llm as client:` | existing idiom | `legacy.py:1473` |
| `AnthropicClient.detect_objects` | `self.ask_to_image(..., structured_output=…, no_memory=True)` | method call | anthropic `client.py:1307` |
| cross-strip dedup | `_compute_iou` | module-level import | `grid/merger.py:16` |
| rule evaluation | `TextMatcher.check_text_match`, `_check_illumination`, `_calculate_visual_feature_match` | existing | `compliance.py:118`, `types/abstract.py:151`, `product_on_shelves.py:1052` |
| render | `render_evaluated_image(img, shelf_regions=, identified_products=, save_to=)` | existing, per image | `plan.py:376` |
| handler | `PlanogramCompliance(planogram_config=_config)` | constructor | `handlers/planogram_compliance.py:147` |

### Does NOT Exist (Anti-Hallucination)
- ~~`InkWall` / `ink_wall` class or module~~ — only docstrings and a config string; `planogram_type="ink_wall"` raises `ValueError` today.
- ~~`InkWallAnalysis`~~ — referenced in a docstring (`parrot/interfaces/images/plugins/analisys.py:65`), never defined.
- ~~`parrot_pipelines/planogram/perception/`, `identification/`, `comparison/`, `contracts.py`, `backend.py`, `migration.py`, `types/legacy_adapter.py`, `types/ink_wall.py`~~ — all new in this feature.
- ~~`AbstractClient.ask_to_image` / `AbstractClient.detect_objects`~~ — not declared in `parrot/clients/base.py`; per-provider convention only.
- ~~`no_memory` on Anthropic `ask_to_image`~~ — Google/OpenAI only **today; Module 4 adds it**.
- ~~`detect_objects` on Anthropic / OpenAI clients~~ — Google-only **today; Module 4 adds the Anthropic one** (OpenAI out of scope).
- ~~a `model` kwarg on Google `detect_objects`~~ — hard-coded model, not exposed.
- ~~a call to `detect_objects_roi` from `run()`~~ — declared abstract, never invoked.
- ~~a global / numeric compliance threshold in `plan.py` or on `PlanogramConfig`~~ — `overall_compliant` is `all(status == COMPLIANT)`; thresholds are per shelf (`ShelfConfig.compliance_threshold`).
- ~~`PlanogramDescription.visual_features_weight`, `AdvertisementEndcap.brand_weight`~~ — read via `getattr` with defaults; the fields do not exist.
- ~~`ShelfConfig.illumination_required` / `illumination_penalty`~~ — they live only in the raw dict, nested in `shelves[].products[]`.
- ~~validators on `PlanogramConfig`~~ — none today.
- ~~`CellResultMerger._compute_iou`~~ — `_compute_iou` is module-level.
- ~~`LLMFactory.supported_clients` as an attribute~~ — it is a static method.
- ~~A slots/facings or backend column on `troc.planograms_configurations`~~ — none; this feature adds them. ~~`planogram_type` column in `table.sql`~~ — absent from the DDL.
- ~~`ClaudeAgentClient.ask_to_image`~~ — raises `NotImplementedError`.
- ~~`[project.optional-dependencies]` in `ai-parrot-pipelines/pyproject.toml`~~ — section absent; no extras exist.
- ~~`rapidocr` in any workspace `pyproject.toml`~~ — installed in the venv, declared nowhere.
- ~~`numpy`, `pillow`, `rapidfuzz`, `onnxruntime` declared by `ai-parrot-pipelines`~~ — transitive only (deps today: `ai-parrot>=1.0.4`, `opencv-python-headless>=4.8`, `pytesseract>=0.3.13`).
- ~~A `PlanogramConfig` field that loads a JSON file~~ — none.
- ~~Generic shape detection (products, boxes, posters, backlits) in `examples/planogram/`~~ — `plancheck/detection.py` detects **only bright landscape price labels**; no Canny, adaptive threshold, morphology or Hough anywhere.
- ~~Shelf-edge detection~~ — rows come only from aligned price tags.
- ~~A separate catalog file / `load_catalog()` / `Settings.catalog`~~ — removed in `f39b69c026`; descriptors live in the planogram JSON.
- ~~Non-monotone row→shelf registration~~ — `register_image` only tries strictly increasing shelf combinations.
- ~~Tests for `ProductOnShelves.check_planogram_compliance`, `_ocr_fact_tags`, `_corroborate_products_with_fact_tags`, `_check_illumination`~~ — none.
- ~~`conftest.py` in `packages/ai-parrot-pipelines/tests/` or `tests/pipelines/`; any fake-LLM fixture~~ — none; fakes are inline `MagicMock`s (`tests/test_planogram_types.py:96-103`).
- ~~A test for `AnthropicClient.ask_to_image`~~ — none (`packages/ai-parrot-client-anthropic/tests/unit/` has two unrelated files).
- ~~Any ALTER / migration `.sql` in the pipelines package~~ — `table.sql` is the only one.
- ~~`docs/pipelines/`~~ — directory does not exist yet.
- ~~Any planogram tool in `ai-parrot-tools`~~ — zero references.
- ~~Packaging for `plancheck`~~ — bare directory on `sys.path`, not importable from the package.
- ~~Labelled ground truth for the example photos~~ — none.

### Configuration References
| Key | Where | Notes |
|---|---|---|
| `DEFAULT_LLM_MODEL` | `parrot/conf.py:443` (`LLM_MODEL`, fallback `"gemini-flash-latest"`) | model half of `DEFAULT_LLM_BACKEND` |
| `PLANOGRAM_FOLDER` | `parrot/conf.py:116-118` | reference-image root used by the handler |
| `planogram_config["perception_mode"]` | new | `"cv"` \| `"llm_detector"` (ProductOnShelves) |
| `planogram_config["rule_bindings"]` | new | list of `RuleBinding` dicts |
| `planogram_config["use_fact_tag_boundaries"]` | existing (`plan.py:282`) | legacy path only |
| DB access in `preflight` | `db.acquire()` / `conn.fetch_one` as in `handlers/planogram_compliance.py:286-287` | *(driver API unverified — check before use)* |

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks — it must never invent an API, choose a
> file, or resolve an open design question.

### Patterns to Follow
- Async-first; hooks are `async def`. CPU work goes through
  `CpuExecutor.run(module_level_fn, ...)` — pass `np.ndarray` / `bytes`, never
  PIL images, bound methods or clients, across the process boundary.
- Pydantic v2 for every structure; `self.logger` (types use `pipeline.logger`),
  never `print`; `aiohttp` only; Google-style docstrings + strict type hints.
- Lazy optional imports exactly like `plancheck/prices.py:77-87` (probe at
  construction, build on first use) — reference, re-implemented.
- New code is written against `DetectionBox` / `IdentifiedProduct` /
  `ComplianceResult`; no parallel box/product vocabulary.
- `identified_products` / `shelf_regions` result keys are produced for migrated
  types too (projected from identifications and definition shelves) so
  `render_evaluated_image` and existing consumers keep working.
- Tests import with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src:...`
  inside the worktree (the shared `.venv` is editable-installed against the main
  checkout). Never `uv sync` inside a worktree.
- The repository is public: no real store photo, no `planogram_page1.json`
  content, no manual annotation in any commit. New tracked files under
  `examples/planogram/` need an explicit `.gitignore` negation next to the
  FEAT-565 block (`.gitignore:413-425`).

### Known Risks / Gotchas
- **Generic shape detection is unproven** (main technical risk). Contained by:
  InkWall first; ProductOnShelves on `llm_detector` until the spike passes;
  LLM-added shapes; the explicit fallback; and the perception hook that lets an
  open-vocabulary detector be swapped in later.
- **`ProductOnShelves` is 1683 untested lines.** Module 3 precedes Modules 6, 14
  and 17. Pin the quirks as they are (weights sum 1.1, zone-only shelf 0.3,
  header text score not zeroed, order-dependent `globally_matched_keys`,
  `basic_score`-only threshold) — they are *legacy* behaviour; the migrated
  formula in §2 deliberately differs and the runbook explains it.
- **Transitional dual contract** until the other four types migrate;
  `validate_contract()` keeps half-implemented types out.
- **Moving orchestration out of `run()`** must not reorder steps 5-17 nor drop a
  `hasattr` guard; step 13 has no guard today because the method is on the base.
- **`legacy.py` also uses `roi_client`** (`:2282`) — removing the attribute
  without Module 6's edit breaks `PlanogramCompliancePipeline`.
- **Method defaults masking the caller's model**: Anthropic `ask_to_image`
  defaults to `SONNET_4` today and would override a client configured with
  another model. Module 4 fixes the resolution order; `VisionAdapter` also
  passes the resolved model explicitly.
- **Google `detect_objects` ignores the resolved model** (hard-coded). Legacy
  call sites on Google keep that behaviour; the new cycle's fallback does not
  use it (it goes through `VisionAdapter`). See §8.
- **Partial view** ⇒ uncovered facings are `not_visible`, never `missing`.
  **Disagreeing photos** ⇒ `conflict`. **OCR unavailable** ⇒ LLM reads text,
  `ocr_available=False`. **Invalid LLM structure** ⇒ one repair retry, then the
  strip's slots are uncertain. **No/too few shapes** ⇒ fallback; if it also
  fails ⇒ `not_assessed` + `errors`.
- **Process pools under gunicorn**: one bounded pool per pipeline instance,
  created lazily, closed in `finally`; `cpu_workers` is per gunicorn worker —
  the runbook states the memory arithmetic (RapidOCR/ONNX models load per
  process).
- **Photo resolution**: the reference photo is 1280×955 (messenger-compressed);
  tag text is a few pixels tall. OCR expectations for ProductOnShelves depend on
  the production resolution (§8).
- **Undescribed SKUs**: `planogram_page1.json` describes 2 of 102 positions;
  partial definitions are legal, a definition with zero described positions is
  rejected, and `definition_coverage` makes the gap explicit.
- **Parallel sessions** share this clone; push early, and re-check `dev` before
  editing `plan.py` / `types/abstract.py`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `opencv-python-headless` | `>=4.8` | shape proposals, strips, annotation — **already a hard dependency** |
| `numpy` | (declare, unpinned) | array ops — used today, only transitive |
| `pillow` | (declare, unpinned) | image load / overlay render — only transitive today |
| `rapidfuzz` | `>=3.0` | brand / alias fuzzy match in comparison — in core deps, declare directly |
| `rapidocr` | `>=3.9` | **optional extra `planogram`** — local OCR; API: `RapidOCR()(img).txts` |
| `onnxruntime` | `>=1.20` | RapidOCR backend (extra); never imported directly |
| `pydantic` v2 | existing | all contracts |

---

## Worktree Strategy

- **Isolation**: one feature worktree for this spec —
  `.claude/worktrees/feat-FEAT-574-new-planogram-pipeline`, created from
  `origin/dev` by `python -m scripts.sdd.ensure_worktree --slug new-planogram-pipeline --feature-id FEAT-574`.
  The `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (an edge means "imports a symbol of" or "edits
  the same file after"):
  - Roots — no edges between them, expected to run concurrently:
    **M1** (spike), **M2** (contracts), **M3** (characterization tests),
    **M4** (Anthropic parity, other distribution), **M5** (config/backend),
    **M8** (OCR + `pyproject.toml`).
  - **M6 → M3, M4, M5** (needs pinned behaviour, Anthropic kwargs, `resolved_backend`).
  - **M7 → M1, M2** (`ShapeCandidate`, `Slot`). **M9 → M2**. **M11 → M2**.
    **M10 → M2, M5** (`ResolvedBackend`). M7, M9, M10, M11 are mutually independent.
  - **M12 → M7, M9, M10, M11**. **M13 → M2, M9**. M12 ∥ M13.
  - **M14 → M2, M3, M6** (M6 and M14 both edit `types/abstract.py`).
  - **M15 → M5, M7, M8, M10, M12, M14** (and edits `plan.py` after M6).
  - **M16 → M7, M8, M9, M11, M12, M13, M14, M15**. **M17 → M1, M3, M6, M13, M14, M15**. M16 ∥ M17
    except for `plan.py`'s `_PLANOGRAM_TYPES` line (M16 only).
  - **M18 → M5, M15**. **M19 → M5, M9**. **M20 → M9, M10**. **M21 → M16, M17**. **M22 → M16**.
- **Shared files** (their tasks serialise): `types/abstract.py` (M6, M14);
  `plan.py` (M6, M15, M16); `types/product_on_shelves.py` (M6, M17);
  `abstract.py` (M5, M6); `handlers/planogram_compliance.py` (M6, M18);
  `.gitignore` (M1, M20, M21); `packages/ai-parrot/src/parrot/models/compliance.py` (M2 only);
  `pyproject.toml` (M8 only — single owner by design).
- **Exclusive resources**: none that mutate shared state outside a module's own
  files — no extension rebuild, no lockfile regeneration (M8 edits
  `pyproject.toml` declaratively; do **not** run `uv sync`/`uv lock` in the
  worktree), no migration is *applied*. M1's harness run reads private local
  photos and is the only step needing the primary checkout's git-ignored data.
- **Cross-feature dependencies**: none must merge first. No in-flight feature
  touches `parrot_pipelines/planogram/` (open indexes at brainstorm time:
  FEAT-481, 536, 539, 540, 569, 572 — other subsystems).

---

## 8. Open Questions

> Resolved items are carried from the brainstorm (decision trail); they are
> reflected in the body above and must not be re-opened during implementation.

- [x] Feature or hotfix, base branch — *Resolved in brainstorm*: feature, `dev`.
- [x] Fate of the pure-LLM ROI cycle — *Resolved in brainstorm*: total replacement; public signature kept.
- [x] Types in scope — *Resolved in brainstorm*: `InkWall` + `ProductOnShelves`; the other four later.
- [x] Unmigrated types — *Resolved in brainstorm*: adapter defaults in `AbstractPlanogramType` wrapping the legacy methods.
- [x] How `plancheck` code is reused — *Resolved in brainstorm*: re-written, inspired by it; not moved or imported.
- [x] Single or multiple images — *Resolved in brainstorm*: one or several, merged per facing.
- [x] LLM call granularity — *Resolved in brainstorm*: declared by the type (full image | strips).
- [x] CV finds too few shapes — *Resolved in brainstorm*: fall back to an LLM detector; mark `detection_source`.
- [x] Where the slot definition lives — *Resolved in brainstorm*: `PlanogramConfig` names the type; a JSON defines shelves/slots/products; a ProductOnShelves JSON must be created.
- [x] Output contract — *Resolved in brainstorm*: same keys + new additive keys.
- [x] Dependencies — *Resolved in brainstorm*: local OCR is an optional extra with lazy imports; OpenCV remains a hard dependency. Declare directly used dependencies explicitly.
- [x] Model benchmark — *Resolved in brainstorm*: unlabelled descriptive deliverable; the user selects the default. It makes no accuracy or recall claim.
- [x] How does the slots JSON reach a DB-driven config? — *Resolved in brainstorm*: both sources are valid and equivalent — a new JSONB column on `troc.planograms_configurations` or a JSON file. `table.sql` needs the new nullable column.
- [x] Name and nullability of the new column / field — *Resolved in brainstorm*: `slots_definition` — `JSONB NULL`, same name on `PlanogramConfig`; idempotent ALTER script (`ADD COLUMN IF NOT EXISTS`, `DROP NOT NULL` on both prompts) next to `table.sql`; the user applies it.
- [x] Generic shape detection is unproven — *Resolved in brainstorm*: the first task is the perception spike with a manually checked sample, per-profile precision/recall and fixture-membership tests. Failed or inconclusive gates select the LLM-detector fallback. The hook remains ready for another detector (Option C).
- [x] May the LLM add shapes the CV missed? — *Resolved in brainstorm*: yes, through validated `added_shapes` with pipeline-owned IDs and `source="llm_added"`. Raw confidence intact; only the separate evidence-quality weight is lower; no detector-source cap on compliance.
- [x] Hard-coded models / Google client — *Resolved in brainstorm*: eliminate them; either client must be able to drive the whole run. (Re-counted: 63 lines in 11 files.)
- [x] Client homologation — *Resolved in brainstorm*: in scope — `no_memory` on `AnthropicClient.ask_to_image` and `detect_objects` on `AnthropicClient`, matching the Google client.
- [x] `ProductOnShelves` tests — *Resolved in brainstorm*: must be built in this feature.
- [x] Benchmark ground truth — *Resolved in brainstorm*: none; reports confidence, scoring, number of objects detected and duration per backend; no automated pass bar.
- [x] Which model ids does the benchmark compare? — *Resolved in brainstorm*: `gemini-3.5-flash` vs `claude-sonnet-5` (`ClaudeModel.SONNET_5`).
- [x] Where does the default provider/model live once literals are gone? — *Resolved in brainstorm*: a field on `PlanogramConfig`; explicit `llm=` / `llm_provider=` / `llm_model=` still win.
- [x] `AnthropicClient.ask_to_image` default model — *Resolved in brainstorm*: bump to `ClaudeModel.SONNET_5`, same default for the new `detect_objects`.
- [x] `planogram_page1.json` has 2/102 positions described — *Resolved in brainstorm*: the descriptor utility proposes descriptors and readable identifiers/aliases from the POG PDF only, with page evidence for human review. No catalog lookup or generated price. Partial definitions remain legal, with definition coverage and unresolved identities explicit.
- [x] ProductOnShelves slots JSON: replace or complement? — *Resolved in brainstorm*: `slots_definition` **replaces** `planogram_config.shelves[].products` for migrated types; non-product expectations stay in `planogram_config`.
- [x] Prompts required? — *Resolved in brainstorm*: no longer mandatory; `table.sql` relaxes too; unmigrated types that need them fail with a clear message when absent.
- [x] `AbstractPipeline.roi_client` is always Google — *Resolved in brainstorm*: remove the hard-coding; auxiliary calls go through the pipeline's own client.
- [x] Multi-image API shape — *Resolved in brainstorm*: `run(image=…)` accepts one image or a list; the handler keeps single-file upload.
- [x] Registration assumes strictly increasing shelves — *Resolved in brainstorm*: header/backlit/poster are zones detected apart; product rows register in increasing order.
- [x] What happens to `examples/planogram/plancheck/` — *Resolved in brainstorm*: stays as it is. Not moved, not deleted, not rewired.
- [x] `open_image` always enhances — *Resolved in brainstorm*: perception, OCR and LLM crops use the untouched full-resolution image; enhancement only on the legacy adapter path.
- [x] Which real ProductOnShelves photo feeds the spike? — *Resolved in brainstorm*: `examples/planogram/photo_2026-09-18_20-36-30.jpg` (git-ignored, 1280×955).
- [x] Which catalog backs the descriptor utility's SKU lookup? — *Resolved in brainstorm*: none — discarded. POG PDF only; `price` never proposed.
- [x] Backend field and precedence — *Resolved in brainstorm*: nullable `llm_backend` (`provider:model`) on config and DB, same ALTER script. Explicit `llm` wins, then explicit provider/model overrides, then config, then documented defaults. Sentinel for omitted arguments; a provider change cannot inherit another provider's model.
- [x] Evidence weight of `llm_added` shapes — *Resolved in brainstorm*: provisional `0.5`, configurable, applied only to evidence quality. Supersedes the earlier strict-zero/lenient-50% fallback rule.
- [x] Fixture scoping without an ROI gate — *Resolved in brainstorm*: full-image proposals followed by evidence-based on/off/uncertain membership before registration. Expected SKU agreement cannot establish membership.
- [x] Configuration compatibility — *Resolved in brainstorm*: reviewed ProductOnShelves slots backfill and non-product rule bindings are required before deployment. Ship candidate conversion and read-only preflight.
- [x] Unknown states and public scores — *Resolved in brainstorm*: all expected facings in denominators, coverage separate, unweighted shelf mean, complete assessment required for `overall_compliant=True`, assessment metadata in handler responses, existing enum kept.
- [x] Observation conflicts — *Resolved in brainstorm*: merge agreeing evidence with provenance; incompatible admissible identities become `conflict`, independent of source.
- [x] CPU work — *Resolved in brainstorm*: bounded process executor for CV/OCR/encoding; thread offload limited to blocking I/O.
- [x] **Scoring examples for the spec** (brainstorm owner: *specification task*) — *Resolved in this spec*: the shelf-local combination formula, status projection and the seven pinned fixtures are fixed in §2 *Scoring contract* and §4 *Pinned scoring fixtures*. Two spec-level decisions the reviewer should confirm: (a) migrated types **normalise** the product/text/visual weights (legacy defaults sum to 1.1 and are clamped); (b) shelf `COMPLIANT` compares `facing_lenient` — not the combined score — with `compliance_threshold`, mirroring today's use of `basic_score`.
- [ ] **Spike validation**: confirm or revise the provisional two-day time box, 0.5 IoU, and 90 % precision/recall gates using the available private sample. Record tested conditions, failures, and whether membership exclusion is reliable. — *Owner: implementation spike (Module 1) / Jesus Lara*
- [ ] **Photo resolution.** The reference photo is 1280×955 (messenger-compressed); price-tag text is a few pixels tall. Is this the resolution production will receive, or will originals be available? OCR expectations for ProductOnShelves depend on it. — *Owner: Jesus Lara*
- [ ] **Google `detect_objects` hard-codes its model** (`analysis.py:1264,1276`) and exposes no `model` kwarg, so legacy call sites on Google cannot honour the resolved backend. This spec leaves the Google client untouched and gives only the new Anthropic method a keyword-only `model`. Add an optional `model` to Google's too? — *Owner: Jesus Lara* (non-blocking)
- [ ] **`planogram_type` is not a column of `table.sql`** although the handler reads it. Should the ALTER script also add `planogram_type VARCHAR NULL` so `ink_wall` rows are expressible on a database built from this DDL? — *Owner: Jesus Lara* (non-blocking; default: not added)

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: skipped (exploration
> doc status is `exploration`, not `accepted` — precondition of `/sdd-spec` §3b not met)
> · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-18 | Jesus Lara (with Claude) | Initial draft from `new-planogram-pipeline.brainstorm.md` (Option A); codebase contract re-verified against `dev` @ `dfd1155bd` |
| 0.2 | 2026-09-18 | Jesus Lara (with Claude) | /sdd-task: spike report moved to `docs/pipelines/planogram-perception-spike.md` (sdd-coder tasks never write under `sdd/`); M22 registry/exports/doc folded into the InkWall task; `roi_client` removal deferred from M5 to the last M6 task so intermediate merges stay green |


