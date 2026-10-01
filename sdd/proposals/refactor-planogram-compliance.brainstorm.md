---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot-pipelines, ai-parrot, docs]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [planogram, compliance, refactor, opencv, ocr, e2e]
---

# Brainstorm: Refactor `PlanogramCompliance` — every type on the three-step cycle, legacy removed

**Date**: 2026-09-30
**Author**: Jesus Lara (with Claude)
**Status**: exploration
**Recommended Option**: A

**Related**: FEAT-574 `new-planogram-pipeline` (merged — introduced the cycle), FEAT-592
`nova-image-planogram` (merged — OCR-anchored Nova example), FEAT-565
`new-planogram-compliance-algo` (merged — `examples/planogram/plancheck/`), FEAT-048
`planogram-compliance-modular` (`AbstractPlanogramType`), FEAT-047 `planogram-compliance-handler`.

---

## Problem Statement

The planogram workstream wants one compliance pipeline that works in three steps:

1. **Perceive** — OpenCV finds shapes and areas: regions of interest, shelves, slots, zones.
2. **Identify** — local OCR reads the words inside the detected areas; the detections plus the
   OCR text go to an LLM that detects products, identifies them (using reference images where a
   configuration has them) and decides whether each slot is occupied or empty.
3. **Compare** — detections, product identifications, endcap and advertisement checks are compared
   with the planogram definition; compliance is computed overall and per shelf.

### What the code does today (verified 2026-09-30)

The request describes `PlanogramCompliance` as a pure-LLM pipeline. That was true before
FEAT-574; the class docstring (`plan.py:49`) still says so, but `run()` (`plan.py:134`) already
executes `perceive → identify → compare`. The migration stopped halfway:

| `planogram_type` | Path today | Evidence |
|---|---|---|
| `ink_wall` | full cycle: OpenCV price tags → rows → slots → optional tag OCR → strip LLM → deterministic compare | `types/ink_wall.py:160-298` |
| `product_on_shelves` | cycle hooks **and** ~1,500 lines of the old legacy contract in the same class; default `perception_mode` is `"llm_detector"` because the perception spike accepted no OpenCV profile | `types/product_on_shelves.py:80, 93-262, 378-862, 864-2320` |
| `endcap_backlit_multitier` | pure LLM through the legacy adapter | `types/endcap_backlit_multitier.py:162, 467, 760` |
| `endcap_no_shelves_promotional` | pure LLM through the legacy adapter | `types/endcap_no_shelves_promotional.py:61, 299, 441` |
| `graphic_panel_display` | pure LLM through the legacy adapter | `types/graphic_panel_display.py:65, 175, 411` |
| `product_counter` | pure LLM through the legacy adapter | `types/product_counter.py:66, 271, 343` |

Four concrete problems follow from that:

1. **Four of six types never run steps 1 and 2.** `AbstractPlanogramType.perceive` defaults to
   `legacy_perceive` (`types/abstract.py:497-510`), which runs `compute_roi → detect_objects` on
   the LLM and returns `detection_source="legacy_llm"`; `compare` defaults to
   `check_planogram_compliance` with `assessment_status=LEGACY_UNMEASURED`
   (`types/abstract.py:527-567`). Those types get no coverage, no strict score, no evidence
   quality, and a failed ROI still degrades the whole run silently.
2. **Layout is hardcoded in the type classes.** `ProductOnShelves.get_shape_profiles()` returns
   four literal `ShapeProfile`s (`product_on_shelves.py:277-338`); `InkWall.perceive` fixes
   `PRICE_TAG_PROFILE`, `AnchorRule.TAG_BELOW_PRODUCT`, `fill_gaps=True`,
   `untagged_bottom_row=True` (`ink_wall.py:182-185`); the descriptor vocabulary
   `("family", "colors", "pack", "xl")` is ink-specific yet hardcoded in both migrated types
   (`ink_wall.py:46`, `product_on_shelves.py:549`) and baked into the `Descriptors` model
   (`comparison/definition.py:33-44`). The number of shelves and slots already comes from
   `slots_definition`, but how to *find* them does not.
3. **The best Stage-2 recipe lives outside the package.** `examples/planogram/aws/` reads OCR
   inside every **slot** box (the product front, where the retail code is printed) and anchors the
   prompt on it (`nova-ocr-v3`). The package prompt (`identify-v1`,
   `identification/identify.py:148`) only carries the OCR of the price tag, local OCR is off by
   default (`enabled_ocr=False`, `plan.py:81`), and the cycle never sends reference images:
   `_run_call` passes `[png]` alone (`identify.py:364-365`) although `VisionAdapter.ask` already
   forwards `images[1:]` as `reference_images` (`identification/vision.py:185, 260`).
4. **Dead code that still ships.** `planogram/legacy.py` (2,905 lines:
   `PlanogramCompliancePipeline`, `RetailDetector`) imports `torch`, `pytesseract` and
   `google.genai` at module top, is imported by no tracked code, and is only reachable through
   lazy re-exports (`planogram/__init__.py:15-17`, `parrot_pipelines/__init__.py:11-12`, the core
   proxy `packages/ai-parrot/src/parrot/pipelines/planogram/legacy.py`).

**Who is affected**: the retail-compliance workstream (results for endcaps, panels and counters
are unmeasured and not comparable with ink wall / shelves), whoever onboards a new retailer
fixture (today that means editing a type class), and maintainers (two contracts, one adapter and
a 2,905-line dead module to keep alive).

## Constraints & Requirements

Decisions taken in discovery (three rounds) are binding for the spec:

- **Flow**: `type: feature`, `base_branch: dev`.
- **Finish the FEAT-574 migration, do not rewrite it.** `PlanogramCompliance.run()`, `contracts.py`
  and the perception / identification / comparison building blocks stay.
- **All six types run the three-step cycle.** The legacy contract
  (`compute_roi` / `detect_objects_roi` / `detect_objects` / `check_planogram_compliance`),
  `types/legacy_adapter.py` and `planogram/legacy.py` are removed.
- **Backward compatible means**: `PlanogramComplianceHandler` keeps calling
  `PlanogramCompliance(planogram_config=config)` and `run(image)` (`handlers/planogram_compliance.py:153`);
  the eight legacy result keys stay (`step3_compliance_results`, `compliance_results`,
  `overall_compliance_score`, `overall_compliant`, `identified_products`, `shelf_regions`,
  `rendered_image`, `overlay_path` — `plan.py:365-373`).
- **Not preserved**: stored DB configs running unedited (they are migrated instead), and the
  `PlanogramCompliancePipeline` / `RetailDetector` names.
- **Thin type classes, layout in configuration.** Shape profiles, anchor rule, identify strategy,
  thresholds, descriptor vocabulary and shelf/slot counts come from `planogram_config` /
  `slots_definition`; a class only supplies defaults and genuinely type-specific rules.
- **Stage 1**: OpenCV first; when usable on-fixture shapes fall under the type threshold the LLM
  detector takes over and `detection_source` says so (the mechanism exists:
  `plan.py:253-281`).
- **Stage 2**: local OCR runs automatically when the `planogram` extra is installed, otherwise
  the run continues with `ocr_available=False`; the OCR-anchored prompt becomes the package
  default; reference images travel to the LLM in the same call as the marked strip / crop.
- **Backend-neutral.** Everything goes through `VisionAdapter`; the default backend is unchanged.
  Nova 2 Lite as a real backend (image support in `ai-parrot-client-amazon`) is **out of scope**.
- **DB migration**: a converter + read-only dry run for all six types; a human reviews and applies
  the SQL. Nothing in this feature writes to `troc.planograms_configurations`.
- **E2E** under `examples/planogram/e2e/`: live LLM calls on local photos, skipped when photos or
  credentials are missing, vision cache for free re-runs, asserting against a hand-labelled
  ground truth with tolerances. Covers product on shelves, ink wall and endcap backlit. Not a CI gate.
- **Repository is public**: photos, planogram extractions, generated definitions, renders and the
  vision cache are retailer data and stay git-ignored (`.gitignore:421-450`).
- Codebase rules: async-first, Pydantic v2, `aiohttp` only, LLM calls through `AbstractClient`
  (here via `VisionAdapter`), `self.logger`, CPU work through the process pool (`CpuExecutor`).

---

## Options Explored

### Option A: Finish the migration in place — shared stage toolkit, declarative layout profile, thin types

Keep the orchestrator and the contracts. Give every type the three cycle hooks by composing the
same building blocks the two migrated types already use, and move everything that describes the
*fixture layout* out of the classes into a validated configuration section.

- **Layout profile** — a Pydantic model read from `planogram_config` (shape profiles, anchor
  rule, gap filling, identify strategy, minimum usable shapes, perception mode, descriptor
  vocabulary, OCR targets, reference-image policy). Each type class contributes a default profile;
  a stored config overrides any field. Counts of shelves, slots and zones keep coming from
  `slots_definition`.
- **Shared stage toolkit** — the perceive / identify / compare sequences now duplicated between
  `InkWall` and `ProductOnShelves` become reusable helpers parameterised by the profile; a type
  hook is a short composition plus its own rules (illumination, sections, fact tags, counting).
- **Identify v2** — per-slot and per-zone OCR feeds an OCR-anchored prompt (the `nova-ocr-v3`
  recipe, provider-neutral); a labelled reference-image bank rides in the same vision call.
- **Four type migrations** — `endcap_backlit_multitier`, `endcap_no_shelves_promotional`,
  `graphic_panel_display`, `product_counter` get hooks; their zone-centric checks map onto
  `ZoneDefinition` + `RuleBinding` (illumination, text, visual, zone present).
- **Removal** — legacy contract methods, `legacy_adapter.py`, `LegacyPayload` plumbing,
  `legacy.py`, its lazy re-exports and the code only it uses.
- **Converter for six types** and the **E2E suite**.

✅ **Pros:**
- Smallest conceptual change: one contract, one orchestrator, one result shape for every type.
- Reuses what FEAT-574 already tested (rows, slots, membership, registration, scoring, projection).
- Matches all discovery decisions directly.
- Deletes about 4,700 lines outright (`legacy.py` 2,905, the legacy half of
  `product_on_shelves.py` ~1,500, `legacy_adapter.py` 325) and replaces the four legacy type
  files (3,710 lines of pure-LLM code) with hooks built on the shared toolkit.
- New retailer fixture = a configuration, not a code change, for the common cases.

❌ **Cons:**
- Scores of the four migrated types change meaning (every expected facing stays in the
  denominator, strict/lenient credits, coverage separate) — not comparable with today's numbers.
- All six types will require a `slots_definition`: every stored row must be migrated **before**
  the release is deployed, or the handler fails at construction for that config.
- No accepted OpenCV profile exists for shelves / endcaps (perception spike: inconclusive), so
  these types will often land on the LLM-detector fallback until profiles are tuned.
- Large diff in `product_on_shelves.py` and `abstract.py`, the two most shared files.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `opencv-python-headless>=4.8` | shape proposal, shelf edges, Set-of-Marks rendering | already a dependency |
| `rapidocr>=3.9` + `onnxruntime>=1.20` | local OCR of slots, tags and zones | optional `planogram` extra, already declared |
| `rapidfuzz>=3.0` | alias / descriptor identity resolution | already a dependency |
| `pydantic` v2 | layout profile model, contracts | already used |
| `pytest` + `pytest-asyncio` | E2E suite | already the test stack |
| `pytesseract>=0.3.13` | — | candidate for **removal**: the only import found is `legacy.py`; confirm in the spec |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py` — orchestrator, multi-photo loop, LLM-detector fallback, result assembly.
- `.../planogram/contracts.py` — `Shape`, `Slot`, `PerceptionResult`, `Identification`, `ComparisonResult`, `CycleContext`.
- `.../planogram/perception/` — `propose_shapes`, `group_rows`, `detect_shelf_edges`, `build_slots`, `assign_membership`, `OcrReader` / `read_crop`, `CpuExecutor`.
- `.../planogram/identification/` — `identify_strips`, `identify_full_image`, `render_marked_strip`, `validate_response`, `llm_detect_shapes`, `verify_unresolved`, `VisionAdapter`.
- `.../planogram/comparison/` — `SlotsDefinition`, `register_image`, `merge_positions`, `score_shelves`, `summarize`, `project_compliance`, `finalize_comparison`.
- `.../planogram/migration.py` — `convert_config`, `check_row`, `preflight` (extend beyond `product_on_shelves`).
- `examples/planogram/aws/prompt.py`, `identify.py`, `nova2.py` — the OCR-anchored prompt and per-slot OCR to promote.
- `examples/planogram/pipelines/run_ink_wall.py`, `ink_wall_definition.py` — starting point for the ink-wall E2E case.

---

### Option B: One generic configurable type, six presets

Replace the six classes with a single configuration-driven type. `planogram_type` becomes the
name of a preset (a data document) that fills the layout profile; type-specific behaviour is
expressed only through rule bindings and profile switches.

✅ **Pros:**
- The least code; "nothing hardcoded in a class" is true by construction.
- A new fixture kind never needs a Python change.

❌ **Cons:**
- The behaviours that differ are not all declarative: parallel per-section detection of the
  multi-tier endcap, fact-tag corroboration, counting on a counter, illumination via an auxiliary
  vision call. They would need escape hatches that re-create type classes under another name.
- The configuration surface becomes large and hard to validate; mistakes move from code review
  to stored JSON.
- Rejected in discovery (thin classes were chosen).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` v2 | preset + profile schema | already used |
| `opencv-python-headless>=4.8` | perception | already a dependency |

🔗 **Existing Code to Reuse:**
- Same building blocks as Option A; `types/` would shrink to one module plus preset data.

---

### Option C: Strangler with a shadow run per configuration

Keep the legacy adapter alive during the transition. Add cycle hooks type by type, and for each
stored configuration run **both** paths on the same photos, record the two results side by side,
and flip the configuration to the cycle once a reviewer accepts the comparison. Delete the legacy
contract only when no configuration still uses it.

✅ **Pros:**
- Safest for production: no configuration changes behaviour until someone has looked at it.
- Produces a per-config before/after record, useful to explain score changes to the business.

❌ **Cons:**
- Double LLM cost and latency for the whole transition.
- The two scores are not comparable by design (see `docs/pipelines/planogram-cycle-migration.md`),
  so "parity" cannot be automated — every flip is a manual judgement.
- Keeps `legacy_adapter.py`, both contracts and `LegacyPayload` alive for an open-ended period;
  contradicts the decision to remove them in this feature.
- Extra state: a per-config switch and a place to store shadow results.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | reuses the current stack |

🔗 **Existing Code to Reuse:**
- `types/legacy_adapter.py` — kept as the shadow path.
- `examples/planogram/backend_benchmark.py` — existing harness for side-by-side runs.

---

### Option D (unconventional): Plan-first perception — project the definition onto the photo

Instead of discovering shapes bottom-up per type, treat `slots_definition` as a geometric
template. Stage 1 finds only the fixture frame and its shelf lines (OpenCV, LLM fallback),
estimates the transform from the definition's grid to the photo, and projects every expected
slot and zone as a box. Stage 2 then asks, per projected box, "occupied? what is printed here?"
with OCR and the LLM. One perception routine serves every type, and the slot count is whatever
the configuration says by construction.

✅ **Pros:**
- A single perceive implementation; type differences shrink to the template and the rules.
- Empty slots are first-class: every expected position gets a box even with nothing in it.
- No per-type shape profiles to tune.

❌ **Cons:**
- Needs a reliable fixture frame and real-world slot geometry in the definition — today
  `FacingDefinition` carries order (`slot`, `facing_index`), not widths.
- Partial and multi-photo views break a single transform; FEAT-574's row registration exists
  precisely because half-fixture photos are the norm.
- Sits close to the line FEAT-574 drew: geometry would come from the plan, so the rule "identity
  never comes from what the plan expects" has to be re-argued and re-tested.
- Research-grade: no evidence yet that it beats tag-anchored slots on the ink wall.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `opencv-python-headless>=4.8` | frame detection, `findHomography` / perspective warp | already a dependency |
| `numpy` | transform estimation | already a dependency |

🔗 **Existing Code to Reuse:**
- `perception/rows.py` (`detect_shelf_edges`), `comparison/definition.py` (template source), `identification/identify.py` (per-box calls).

---

## Recommendation

**Option A** is recommended because:

- It is the only option consistent with every decision taken in discovery: finish the migration,
  all six types, thin classes with layout in configuration, CV first with LLM fallback, remove the
  legacy code in the same feature.
- The risky parts of a three-step pipeline — registration of partial photos, merge across
  photos, credit policy, projection to `ComplianceResult` — already exist and are covered by
  `packages/ai-parrot-pipelines/tests/planogram_cycle/`. Option A spends its effort on the four
  unmigrated types and on configuration, not on re-deriving that core.
- Option B's saving is real only if type behaviour were fully declarative, and it is not
  (sections, fact tags, counting, illumination). Thin classes keep those as code while still
  moving every number and profile into configuration.
- Option C buys safety that the converter + dry run + human-applied SQL already provide, at the
  price of keeping exactly the code this feature is meant to delete.
- Option D is worth a spike later (it could replace per-type shape profiles), but it needs
  definition geometry that does not exist and conflicts with how partial photos are handled.

**What is traded off**: scores for the four newly migrated types stop being comparable with
history, and deployment becomes order-dependent (rows migrated first). Both are accepted: the
first is the point of measuring coverage and strict compliance, the second is handled by the
preflight report and a fail-fast `ValueError` naming the config.

---

## Feature Description

### User-Facing Behavior

**HTTP / handler users** see no contract change. `POST /api/v1/planogram/compliance` still takes
a config name and an image; the handler still builds `PlanogramCompliance(planogram_config=config)`
and returns the same result. What changes is the content:

- The eight legacy keys are always present. `shelf_regions` is populated for every type (today
  it is `[]` for migrated types — `plan.py:350`), and `identified_products` carries a meaningful
  `product_type` (today always `"product"` — `plan.py:340-342`) so overlay colours and downstream
  consumers keep working.
- Every type now returns the additive keys with real values: `position_results`, `shelf_scores`,
  `coverage`, `strict_compliance_score`, `evidence_quality`, `definition_coverage`,
  `assessment_status` (`complete` or `inconclusive` — never `legacy_unmeasured`),
  `detection_source` (`cv`, `llm` or `mixed`), `ocr_available`, `renders`, `errors`.
- An incomplete assessment is never reported as compliant; a facing not seen in any photo is
  `not_visible`, not missing.

**Configuration authors** describe a fixture entirely in data:

- `planogram_type` selects a thin class (defaults + type rules).
- `slots_definition` lists shelves, facings (with descriptors) and zones — this is where the
  number of shelves, slots and products lives.
- `planogram_config` carries rule bindings, weights/thresholds and the optional **layout
  profile** overrides: which shapes to look for, how slots relate to their anchors, strip vs
  full-image vs per-slot identification, the fallback threshold, the descriptor vocabulary, and
  how reference images are used.
- `reference_images` (unchanged field) is the image bank used for identification.
- An "Ink Wall" configuration declares slots that are expected to be empty or full; a "Product on
  Shelves" configuration declares facings plus a reference bank; an endcap declares zones
  (backlit header, poster, graphic) plus any product tiers.

**Operators migrating stored rows** run the converter in dry-run mode against
`troc.planograms_configurations`. For each row it prints the candidate `slots_definition`, the
rule bindings, and an `unresolved` list of everything a human must decide. They review, then
apply SQL themselves. A row that was not migrated fails at pipeline construction with a message
naming the config and pointing at the runbook.

**Developers** run the E2E with `pytest examples/planogram/e2e`. Cases whose photos, ground truth
or credentials are missing are skipped with the reason. A run writes renders, `compliance.json`
and a report per case; re-runs hit the vision cache and cost nothing.

### Internal Behavior

1. **Construction.** The pipeline resolves the type class from `planogram_type`, merges the
   class default layout profile with the config overrides, validates it, and loads and validates
   `slots_definition` and rule bindings. Every type requires a definition.
2. **Stage 1 — perceive (no LLM unless the fallback triggers).** For each photo, on the
   untouched full-resolution image: OpenCV proposes shapes for the profile's shape kinds, zones
   are split from product shapes, rows are found (shelf edges, then row consensus), slots are
   built from anchors with the profile's anchor rule and gap filling, and fixture membership is
   assigned. If usable on-fixture shapes are under the profile threshold, the LLM detector
   proposes boxes instead and the perception is marked `llm`.
3. **Stage 2 — identify.** Local OCR reads inside each identification target (slot box, tag,
   zone) through the CPU pool when available. One structured vision call per strip, full image or
   slot — per the profile — receives the marked image, the area list with each area's OCR text
   and confidence, and, when configured, the labelled reference bank. The model answers per
   area: occupancy, brand, product text, descriptors, confidence, evidence. The prompt never
   names expected products. Responses are validated, ids reconciled, missing ids repaired once.
   Zone-level questions (illumination, advertisement text, visual features) are answered here or
   as bound rules in stage 3, per type.
4. **Stage 3 — compare (deterministic).** Identity is resolved from evidence read in the photo
   against the definition's descriptors; each photo is registered against the plan; photos are
   merged per expected facing; rule bindings (zone present, illumination, text, visual) are
   evaluated; shelves are scored with strict and lenient credit; the summary computes overall
   compliance, coverage and evidence quality; the projection produces `ComplianceResult` per
   shelf for the legacy keys.
5. **Assembly and render.** One render per photo with its own boxes; the result dict is built
   with the eight legacy keys plus the additive keys.

Responsibilities after the refactor:

| Piece | Owns |
|---|---|
| `PlanogramCompliance` | input normalisation, per-run context, photo isolation, fallback, render, assembly |
| layout profile | everything that describes how to find and read the fixture |
| shared stage toolkit | the common perceive / identify / compare sequences |
| type class | default profile, type-specific rules (sections, fact tags, counting, illumination), description for weights |
| `slots_definition` | what is expected: shelves, facings, zones |
| `migration.py` | candidate definitions and bindings from legacy configs; read-only preflight |

### Edge Cases & Error Handling

- **OCR not installed** — run continues, `ocr_available=False`, areas are sent with empty OCR
  text; identification relies on the model reading the image.
- **OpenCV finds too little** — LLM-detector fallback; if that also returns nothing the original
  perception is kept and an error is recorded (never a silent empty result).
- **One photo fails** — isolated; its error is listed; the run continues with the others.
- **All photos fail / nothing perceived** — `assessment_status="inconclusive"`,
  `overall_compliant=False`.
- **Zone-only fixture** (graphic panel, promotional endcap with no shelves) — a definition with
  zones and no facings must be valid and must score from rule outcomes alone; an empty facing
  list must not divide by zero or read as a pass.
- **Reference bank too large for one call** — the profile caps references per call; selection
  policy (by shelf, by brand, all) is declared, and the cap is reported.
- **Reference image missing on disk** — recorded as an error for the run; identification proceeds
  without it.
- **Unmigrated stored row** — `ValueError` at construction naming the config and the runbook.
- **Invalid layout profile** — validation error at construction naming the field.
- **Partial view** — unseen facings stay `not_visible` and remain in the denominator.
- **Vision call failure / timeout / malformed answer** — targets of that call become uncertain,
  the error is listed, other calls are unaffected.
- **Removed names** — importing `PlanogramCompliancePipeline` or `RetailDetector` fails with a
  plain `AttributeError` / `ImportError`; release notes call it out.

---

## Capabilities

### New Capabilities
- `planogram-layout-profile`: validated, config-declared description of how a fixture is perceived and read (shape profiles, anchor rule, identify strategy, thresholds, vocabulary), with per-type defaults.
- `planogram-stage-toolkit`: shared perceive / identify / compare sequences that every type composes.
- `planogram-ocr-anchored-identification`: per-slot and per-zone local OCR feeding an OCR-anchored, provider-neutral identification prompt; OCR on when installed.
- `planogram-reference-image-identification`: labelled reference-image bank sent with the identification call, with a declared selection policy and cap.
- `planogram-cycle-endcap-backlit-multitier`: cycle hooks for `endcap_backlit_multitier`.
- `planogram-cycle-endcap-no-shelves-promotional`: cycle hooks for `endcap_no_shelves_promotional`.
- `planogram-cycle-graphic-panel-display`: cycle hooks for `graphic_panel_display`.
- `planogram-cycle-product-counter`: cycle hooks for `product_counter`.
- `planogram-config-converter-all-types`: candidate `slots_definition` + rule bindings and read-only preflight for all six types.
- `planogram-e2e-suite`: `examples/planogram/e2e/` — live, skip-when-missing, ground truth with tolerances, for product on shelves, ink wall and endcap backlit.
- `planogram-legacy-removal`: delete `legacy.py`, `legacy_adapter.py`, the legacy contract and the code only they use.

### Modified Capabilities
- `new-planogram-pipeline` (FEAT-574): the legacy adapter path and `LEGACY_UNMEASURED` disappear; every type requires a slots definition.
- `planogram-compliance-modular` (FEAT-048): the type contract becomes the three cycle hooks only.
- `planogram-compliance-handler` (FEAT-047): unchanged call, result content changes; `roi_detection_prompt` / `object_identification_prompt` no longer used.
- `endcap-backlit-multitier`, `endcap-no-shelves-promotional-fix`, `planogram-new-types`: their types move to the cycle.
- `nova-image-planogram` (FEAT-592): its prompt recipe is promoted into the package; the Nova transport shim stays an example.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot_pipelines/planogram/plan.py` | modifies | docstring; OCR default; legacy branches (`perception.legacy`, unsuffixed debug name) removed; `shelf_regions` / `product_type` populated |
| `parrot_pipelines/planogram/types/abstract.py` | modifies | legacy contract and default legacy hooks removed; layout-profile hook added; `validate_contract` simplified |
| `parrot_pipelines/planogram/types/product_on_shelves.py` | modifies | legacy half deleted (~1,500 lines); profiles move to config defaults |
| `parrot_pipelines/planogram/types/ink_wall.py` | modifies | hardcoded profile / anchor rule / vocabulary read from the layout profile |
| `.../types/endcap_backlit_multitier.py`, `endcap_no_shelves_promotional.py`, `graphic_panel_display.py`, `product_counter.py` | modifies (rewrite) | legacy contract replaced by cycle hooks |
| `parrot_pipelines/planogram/types/legacy_adapter.py` | removes | |
| `parrot_pipelines/planogram/legacy.py` | removes | 2,905 lines |
| `parrot_pipelines/detector.py` (`AbstractDetector`) | removes (confirm) | only user is `legacy.py`; pulls `ultralytics` / `torch` |
| `parrot_pipelines/planogram/grid/` | reduces (confirm) | `GridDetector` / `HorizontalBands` used only by the legacy half; `merger._compute_iou` is used by `identify.py:26` |
| `parrot_pipelines/planogram/contracts.py` | modifies | `LegacyPayload`, `PerceptionResult.legacy`; enum members `LEGACY_LLM` / `LEGACY_UNMEASURED` (see Open Questions) |
| `parrot_pipelines/planogram/identification/identify.py` | extends | OCR-anchored prompt v2, reference images, possibly a per-slot strategy |
| `parrot_pipelines/planogram/comparison/definition.py` | extends | zone-only definitions; zone/rule kinds; generic descriptor vocabulary |
| `parrot_pipelines/planogram/migration.py` | extends | `MIGRATED_TYPES` → all six; `convert_config` per type |
| `parrot_pipelines/models.py` (`PlanogramConfig`) | modifies | legacy prompts, `detection_model`, `confidence_threshold`, `detection_grid` become unused (see Open Questions) |
| `parrot_pipelines/planogram/__init__.py`, `parrot_pipelines/__init__.py` | modifies | drop `PlanogramCompliancePipeline` / `RetailDetector` exports and registry entries |
| `packages/ai-parrot/src/parrot/pipelines/` (core proxy) | modifies | drop `planogram/legacy.py` proxy and the two names from `__all__` |
| `parrot_pipelines/handlers/planogram_compliance.py` | depends on | call unchanged; row hydration of removed fields reviewed |
| `troc.planograms_configurations` (DB) | data migration | human-applied; **must precede deployment** |
| `packages/ai-parrot-pipelines/pyproject.toml` | modifies | drop `pytesseract` if confirmed unused; version bump |
| `packages/ai-parrot-pipelines/tests/` | modifies | legacy-path tests removed or rewritten: `planogram_cycle/test_legacy_run_orchestration.py`, `test_type_hooks.py`, `test_pos_compliance_characterization.py`, `test_pos_fact_tags_illumination_characterization.py`, `test_neutral_panel_types.py`, `test_neutral_shelf_types.py`, `test_config_migration.py`, `tests/test_planogram_types.py`, `tests/test_endcap_no_shelves_promotional.py` |
| `packages/ai-parrot/tests/` | modifies | `test_graphic_panel_display.py`, `handlers/test_planogram_compliance.py`, `test_monorepo_imports.py` |
| `docs/pipelines/planogram-compliance-cycle.md`, `planogram-cycle-migration.md` | modifies | "unmigrated types" section goes away; layout profile documented |
| `examples/planogram/e2e/` + `.gitignore` | new | negation rules so only `*.py` and `README.md` are tracked |
| `examples/planogram/aws/` | depends on | keeps working; its prompt becomes a thin wrapper or is superseded |

**Breaking changes**: removal of `PlanogramCompliancePipeline` / `RetailDetector`; score semantics
for four types; every stored config needs a `slots_definition`. **New dependencies**: none.

---

## Code Context

### User-Provided Code

```python
# Source: user-provided (request text)
from parrot_pipelines.planogram.perception.ocr import OcrReader, read_crop
```

### Verified Codebase References

All paths below are relative to `packages/ai-parrot-pipelines/src/parrot_pipelines/` unless they
start with `packages/` or `examples/`. Verified on `dev` at `dc3e3a548`.

#### Classes & Signatures

```python
# planogram/plan.py
class PlanogramCompliance(AbstractPipeline):                       # line 48
    _PLANOGRAM_TYPES = {                                           # lines 61-68
        "product_on_shelves": ProductOnShelves, "graphic_panel_display": GraphicPanelDisplay,
        "product_counter": ProductCounter, "endcap_no_shelves_promotional": EndcapNoShelvesPromotional,
        "endcap_backlit_multitier": EndcapBacklitMultitier, "ink_wall": InkWall,
    }
    def __init__(self, planogram_config: PlanogramConfig, llm: Any = None,
                 llm_provider: Union[str, _Unset] = UNSET, llm_model: Union[str, None, _Unset] = UNSET,
                 *, cpu_workers: int = 2, llm_concurrency: int = 4, llm_timeout: float = 120.0,
                 vision_cache_dir: Optional[Path] = None, enabled_ocr: bool = False, **kwargs: Any): ...  # line 70
    async def run(self, image: Union[ImageInput, Sequence[ImageInput]],
                  output_dir: Optional[Union[str, Path]] = None,
                  image_id: Optional[Union[str, Sequence[str]]] = None, **kwargs: Any) -> Dict[str, Any]: ...  # line 134
    async def _build_context(self, output_dir: Optional[Path]) -> CycleContext: ...          # line 217
    async def _perceive_one(self, source, image_id: str, ctx) -> Tuple[Image.Image, PerceptionResult]: ...  # line 243
    async def _fallback_if_needed(self, img, perception, ctx) -> PerceptionResult: ...       # line 253
    async def _compare(self, perceptions, identifications, ctx) -> ComparisonResult: ...     # line 283
    def _render_inputs(self, perception, identification) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]: ...  # line 326
    def _assemble(self, perceptions, identifications, comparison, renders, ctx) -> Dict[str, Any]: ...  # line 352
    def render_evaluated_image(self, image, *, shelf_regions=None, detections=None,
                               identified_products=None, mode="identified", show_shelves=True,
                               save_to=None) -> Image.Image: ...                             # line 396

# planogram/types/abstract.py
class AbstractPlanogramType(ABC):                                  # line 36
    identify_strategy: ClassVar[IdentifyStrategy] = IdentifyStrategy.FULL_IMAGE
    requires_slots_definition: ClassVar[bool] = False
    min_usable_shapes: ClassVar[int] = 0
    uses_enhanced_image: ClassVar[bool] = True
    _LEGACY_CONTRACT = ("compute_roi", "detect_objects", "check_planogram_compliance")
    _CYCLE_HOOKS = ("perceive", "identify", "compare")
    _LEGACY_PROMPTS = ("roi_detection_prompt", "object_identification_prompt")
    def __init__(self, pipeline: "PlanogramCompliance", config: "PlanogramConfig") -> None: ...  # line 63
    async def compute_roi(self, img) -> Tuple[...]: ...                                      # line 73  (legacy)
    async def detect_objects_roi(self, img, roi) -> List[Detection]: ...                     # line 94  (legacy)
    async def detect_objects(self, img, roi, macro_objects) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]: ...  # line 113 (legacy)
    def check_planogram_compliance(self, identified_products, planogram_description) -> List[ComplianceResult]: ...  # line 131 (legacy)
    async def _check_illumination(self, img, zone_bbox=None, roi=None, planogram_description=None) -> Optional[str]: ...  # line 167
    def _implements(self, name: str) -> bool: ...                                            # line 463
    def validate_contract(self) -> None: ...                                                 # line 467
    async def perceive(self, image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult: ...  # line 497 (default → legacy_perceive)
    async def identify(self, image, perception: PerceptionResult, ctx: CycleContext) -> IdentificationResult: ...  # line 512 (default pass-through)
    async def compare(self, perceptions: Sequence[PerceptionResult],
                      identifications: Sequence[IdentificationResult], ctx: CycleContext) -> ComparisonResult: ...  # line 527 (default legacy)
    def fallback_detection_prompt(self) -> Optional[str]: ...                                # line 569
    def _vision_kwargs(self, **extra: Any) -> Dict[str, Any]: ...                            # line 573
    def get_render_colors(self) -> Dict[str, Tuple[int, int, int]]: ...                      # line 591
    def get_grid_strategy(self) -> "AbstractGridStrategy": ...                               # line 607

# planogram/types/ink_wall.py
def resolve_identity(identification: Identification, definition: SlotsDefinition) -> Tuple[Optional[str], List[str]]: ...  # line 74
class InkWall(AbstractPlanogramType):                              # line 160
    identify_strategy = IdentifyStrategy.STRIPS; requires_slots_definition = True
    min_usable_shapes = 8; uses_enhanced_image = False
    async def perceive(...) -> PerceptionResult: ...               # line 168
    async def identify(...) -> IdentificationResult: ...           # line 241
    async def compare(...) -> ComparisonResult: ...                # line 263

# planogram/types/product_on_shelves.py
class ProductOnShelves(AbstractPlanogramType):                     # line 64
    identify_strategy = IdentifyStrategy.FULL_IMAGE; requires_slots_definition = True
    min_usable_shapes = 3; uses_enhanced_image = False
    DEFAULT_PERCEPTION_MODE: ClassVar[Literal["cv", "llm_detector"]] = "llm_detector"   # line 80
    def _perception_mode(self) -> str: ...                         # line 263 (reads planogram_config["perception_mode"])
    def get_shape_profiles(self) -> List[ShapeProfile]: ...        # line 277 (four hardcoded profiles)
    def fallback_detection_prompt(self) -> Optional[str]: ...      # line 340
    async def perceive(...) -> PerceptionResult: ...               # line 378
    async def identify(...) -> IdentificationResult: ...           # line 528
    async def _evaluate_rules(...): ...                            # line 623
    async def compare(...) -> ComparisonResult: ...                # line 799
    # legacy half still present: compute_roi 93, detect_objects_roi 119, detect_objects 154,
    # _detect_with_grid 864, _detect_legacy 902, check_planogram_compliance 1024, … to line 2320

# planogram/types/legacy_adapter.py
async def legacy_perceive(handler: "AbstractPlanogramType", image: Image.Image, image_id: str,
                          ctx: CycleContext) -> PerceptionResult: ...                       # line 21

# planogram/contracts.py
class ShapeKind(str, Enum): PRICE_TAG, PRODUCT, BOX, FACT_TAG, ZONE, UNKNOWN                # line 15
class ObservationSource(str, Enum): CV, LLM_ADDED, LLM, LEGACY_LLM                          # line 26
class FixtureMembership(str, Enum): ON_FIXTURE, OFF_FIXTURE, UNCERTAIN                      # line 35
class IdentifyStrategy(str, Enum): FULL_IMAGE, STRIPS                                       # line 43
class Shape(BaseModel): shape_id, image_id, kind, box, profile, row_index, slot_index,
                        ocr_text, ocr_confidence, source, membership, membership_evidence   # line 50
class Slot(BaseModel): slot_id, image_id, row_index, slot_index, box, anchor_shape_id, inferred  # line 67
class LegacyPayload(BaseModel): identified_products, shelf_regions                          # line 79
class PerceptionResult(BaseModel): image_id, image_size, shapes, slots, zones, row_count,
                                   detection_source, ocr_available, legacy, errors          # line 86
class Identification(BaseModel): shape_id, image_id, product, brand, text, descriptors,
                                 occupancy, raw_confidence, evidence, source, uncertain     # line 101
class IdentificationResponse(BaseModel): existing_identifications, added_shapes             # line 130
class IdentificationResult(BaseModel): image_id, identifications, added, errors             # line 137
class FacingStatus(str, Enum): MATCH … NOT_VISIBLE                                          # line 146
class AssessmentStatus(str, Enum): COMPLETE, INCONCLUSIVE, LEGACY_UNMEASURED                # line 161
class RuleOutcome(BaseModel): ...                                                           # line 180
class PositionResult(BaseModel): ...                                                        # line 191
class ShelfScore(BaseModel): ...                                                            # line 204
class CreditPolicy(BaseModel): ...; @classmethod default()                                  # line 221
class EvidenceWeights(BaseModel): cv, llm_added, llm, legacy_llm                            # line 282
class ComparisonResult(BaseModel): ...                                                      # line 295
class RenderRecord(BaseModel): ...                                                          # line 312
class CycleContext(BaseModel): vision, executor, ocr, definition, bindings, credit_policy,
                               evidence_weights, output_dir, errors                         # line 322

# planogram/perception/
class ShapeProfile(BaseModel): name, kind, min/max_width, min/max_height, min/max_aspect,
      polarity: Literal["bright","dark","edge"], min_rectangularity, min_contrast_std,
      thresholds, dedup_overlap                                                # profiles.py:10
class ShapeCandidate(BaseModel): profile, kind, x1, y1, x2, y2, score          # profiles.py:53
PRICE_TAG_PROFILE = ShapeProfile(name="price_tag", …)                          # profiles.py:64
def propose_shapes(image: np.ndarray, profiles: Sequence[ShapeProfile], *, work_width: int = 2048) -> List[ShapeCandidate]: ...  # shapes.py:128
def group_rows(candidates, image_width: int, *, min_row_items: int = 4, max_slope: float = 0.12) -> List[List[ShapeCandidate]]: ...  # rows.py:20
def detect_shelf_edges(image: np.ndarray, *, min_length: float = 0.35) -> List[int]: ...   # rows.py:88
class AnchorRule(str, Enum): ...                                               # slots.py:27
def build_slots(rows, image_size, *, image_id: str, rule: AnchorRule, fill_gaps: bool = True,
                untagged_bottom_row: bool = False) -> List[Slot]: ...          # slots.py:115
def strip_box(slots, image_size, pad: float = 0.04) -> DetectionBox: ...       # slots.py:214
def assign_membership(shapes, zones, image_size, *, llm_hints=None) -> List[Shape]: ...    # membership.py:192
def usable_shapes(shapes) -> List[Shape]: ...                                  # membership.py:249
class OcrReader: available: bool; def read(self, crop: np.ndarray) -> Tuple[str, float]    # ocr.py:16, 39
def read_crop(crop: np.ndarray) -> Tuple[str, float]: ...                      # ocr.py:73 (picklable, per-process singleton)
class CpuExecutor: async def run(self, fn, *args) -> T; async def aclose(self)             # executor.py:17, 62, 94

# planogram/identification/
IDENTIFY_PROMPT_VERSION: str = "identify-v1"; IDENTIFY_STAGE: str = "identify"             # identify.py:33-34
def render_marked_strip(image, strip, marks) -> bytes: ...                                 # identify.py:115
def build_identify_prompt(targets: Sequence[Dict[str, Any]], vocabulary: Sequence[str]) -> str: ...  # identify.py:148
def validate_response(...): ...                                                            # identify.py:241
async def _run_call(image, targets, strip, perception, ctx, *, vocabulary, marks,
                    next_shape_id, full_image=False) -> _CallResult: ...                   # identify.py:345 (sends [png] only: 364-365)
async def identify_full_image(image, perception, ctx, *, vocabulary) -> IdentificationResult: ...  # identify.py:461
async def identify_strips(image, perception, ctx, *, vocabulary, marks: bool = True,
                          substrip_max_slots: int = 8) -> IdentificationResult: ...        # identify.py:493
DETECT_STAGE = "detect"; MAX_SIDE = 2048; GENERIC_DETECTION_PROMPT                          # detector.py:19-22
async def llm_detect_shapes(image, image_id: str, ctx: CycleContext, *, prompt: str) -> List[Shape]: ...  # detector.py:85
async def verify_unresolved(image, identifications, definition, ctx, *, n_distractors: int = 3,
                            boxes=None) -> List[Identification]: ...                       # verify.py:205
class VisionAdapter:                                                                       # vision.py:131
    def __init__(self, client, backend: ResolvedBackend, *, semaphore, cache_dir=None,
                 max_tokens: int = 8192, timeout: float = 120.0, repair_retries: int = 1)
    async def ask(self, prompt: str, images: Sequence[bytes], schema: Type[T], *, stage: str,
                  prompt_version: str, system_prompt: Optional[str] = None) -> T           # vision.py:173
    # images[0] is the main image; images[1:] are forwarded as reference_images (vision.py:185, 260)

# planogram/comparison/
RuleKind = Literal["illumination", "text_requirements", "visual_features", "zone_present"]  # definition.py:14
ZoneKind = Literal["header", "backlit", "poster", "box_stack"]                              # definition.py:15
class Descriptors(BaseModel): display_name, family, xl, colors, pack, identifiers, aliases, price  # definition.py:33
class FacingDefinition(BaseModel): facing_id, shelf_id, slot, product, brand, facings,
                                   facing_index, position, descriptors                      # definition.py:56
class ShelfDefinition(BaseModel): shelf_id, shelf_number, level, facings                    # definition.py:70
class ZoneDefinition(BaseModel): zone_id, kind: ZoneKind, shelf_id, required                # definition.py:79
class RuleBinding(BaseModel): rule_id, kind: RuleKind, target_id, params, mandatory         # definition.py:88
class SlotsDefinition(BaseModel): version, meta, shelves, zones; all_facings()              # definition.py:98
def load_slots_definition(source: Union[Dict[str, Any], str, Path]) -> SlotsDefinition: ... # definition.py:218
def definition_coverage(definition) -> Tuple[float, List[str]]: ...                         # definition.py:267
def validate_bindings(definition, planogram_config: Dict[str, Any]) -> List[RuleBinding]: ...  # definition.py:285 (reads planogram_config["rule_bindings"])
def register_image(image_id, slots, identifications, definition) -> ImageRegistration: ...  # registration.py:172
def merge_positions(definition, registrations, identifications, policy) -> List[PositionResult]: ...  # scoring.py:147
def score_shelves(positions, definition, bindings, rule_outcomes, description, policy) -> List[ShelfScore]: ...  # scoring.py:297
def summarize(shelf_scores, positions, definition, weights) -> ComparisonResult: ...        # scoring.py:399
def project_compliance(...); def finalize_comparison(...)                                   # projection.py:53, 137

# planogram/migration.py
MIGRATED_TYPES = frozenset({"product_on_shelves", "ink_wall"})                              # line 28
def convert_config(planogram_config: Dict[str, Any], *, planogram_type: str) -> ConversionReport: ...  # line 229 (ValueError unless product_on_shelves)
def check_row(row: Dict[str, Any]) -> PreflightRow: ...                                     # line 269
async def preflight(dsn: str) -> List[PreflightRow]: ...                                    # line 308 (read-only)

# models.py
class PlanogramConfig(BaseModel):                                                           # line 32
    planogram_id, config_name, planogram_type (default "product_on_shelves"), planogram_config,
    roi_detection_prompt, object_identification_prompt, reference_images, confidence_threshold,
    detection_model, endcap_geometry, detection_grid, slots_definition, llm_backend
    def get_planogram_description(self) -> PlanogramDescription: ...                        # line 131

# handlers/planogram_compliance.py
pipeline = PlanogramCompliance(planogram_config=_config)                                    # line 153
async def _fetch_planogram_config(self, config_name: str) -> Optional[dict]: ...            # line 295 (troc.planograms_configurations)
def _build_planogram_config(self, row: dict) -> PlanogramConfig: ...                        # line 307

# planogram/legacy.py  (to be removed)
class RetailDetector: ...                                                                   # lines 54-1250
class PlanogramCompliancePipeline: ...                                                      # lines 1253-2905

# examples/planogram/aws/  (tracked; recipe to promote)
def build_nova_identify_prompt(areas, vocabulary: PlanogramVocabulary, schema_instruction: str) -> str: ...  # prompt.py:66
async def identify_strips_closed_set(image, perception, vision, vocabulary, *, executor,
        schema_instruction, marks=True, substrip_max_slots=SUBSTRIP_MAX_SLOTS, ocr=None)
        -> Tuple[IdentificationResult, RunStats]: ...                                       # identify.py:237
async def read_slot_text(image_bgr, perception, executor) -> Dict[str, Tuple[str, float]]: ...  # nova2.py:103 (OCR inside SLOT boxes)
```

#### Verified Imports

```python
from parrot_pipelines.planogram.plan import PlanogramCompliance            # handlers/planogram_compliance.py:19
from parrot_pipelines.models import PlanogramConfig, EndcapGeometry        # models.py:13, 32
from parrot_pipelines.planogram.perception import PRICE_TAG_PROFILE, ShapeCandidate, ShapeProfile, propose_shapes  # perception/__init__.py
from parrot_pipelines.planogram.perception.ocr import OcrReader, read_crop
from parrot_pipelines.planogram.perception.executor import CpuExecutor
from parrot_pipelines.planogram.perception.membership import assign_membership, usable_shapes
from parrot_pipelines.planogram.perception.rows import group_rows, detect_shelf_edges
from parrot_pipelines.planogram.perception.slots import AnchorRule, build_slots, candidate_shape_id, strip_box, to_strip_norm
from parrot_pipelines.planogram.identification.identify import identify_strips, identify_full_image, render_marked_strip, validate_response
from parrot_pipelines.planogram.identification.detector import GENERIC_DETECTION_PROMPT, llm_detect_shapes
from parrot_pipelines.planogram.identification.vision import VisionAdapter, VisionError
from parrot_pipelines.planogram.comparison import (Descriptors, FacingDefinition, RuleBinding, ShelfDefinition,
    SlotsDefinition, SlotsDefinitionError, ZoneDefinition, definition_coverage, load_slots_definition, validate_bindings)
from parrot_pipelines.planogram.backend import ResolvedBackend, UNSET
from parrot_pipelines.planogram.contracts import (CycleContext, PerceptionResult, IdentificationResult,
    ComparisonResult, Shape, Slot, ShapeKind, ObservationSource, IdentifyStrategy, AssessmentStatus)
from parrot.models.detections import DetectionBox, ShelfRegion, IdentifiedProduct
from parrot.models.compliance import ComplianceResult
```

#### Key Attributes & Constants

- `PlanogramCompliance.enabled_ocr` default `False` (`planogram/plan.py:81`); OCR reader created only when set (`plan.py:234`).
- `PlanogramCompliance.reference_images` (`plan.py:124`) — read only by the legacy half (`product_on_shelves.py:897, 954`) and `grid/detector.py`.
- Eight legacy result keys + additive keys assembled at `plan.py:365-389`.
- `_render_inputs` returns `shelf_regions=[]` and `product_type="product"` for cycle types (`plan.py:332-350`).
- Descriptor vocabulary hardcoded: `_VOCABULARY_FIELDS = ("family", "colors", "pack", "xl")` (`ink_wall.py:46`), literal tuple (`product_on_shelves.py:549`).
- `planogram_config["perception_mode"]` ∈ `{"cv", "llm_detector"}` (`product_on_shelves.py:272-275`); `planogram_config["verify_pass"]` (`ink_wall.py:256`); `planogram_config["rule_bindings"]` (`definition.py:300`).
- Optional extra `planogram = ["rapidocr>=3.9", "onnxruntime>=1.20"]` (`packages/ai-parrot-pipelines/pyproject.toml:40-43`); package version `1.0.6` (`version.py`).
- Lazy exports of the legacy names: `planogram/__init__.py:6-7, 15-17`; `parrot_pipelines/__init__.py:11-12`; core proxy files `packages/ai-parrot/src/parrot/pipelines/planogram/{__init__,legacy,plan}.py`.
- `legacy.py` top-level imports: `pytesseract`, `torch`, `cv2`, `google.genai.errors`, `..detector.AbstractDetector`.
- `.gitignore:424` ignores `examples/planogram/*`; tracked sub-folders are re-included one by one (`.gitignore:425-450`).
- Local, untracked fixture material found (git-ignored retailer data): ink wall — `examples/planogram/images/*.jpeg`, `examples/planogram/planogram_page1.json`; shelves with a reference bank — `examples/pipelines/test_pure_planogram.py` (Epson EcoTank, five reference images, photo `250714 BBY 501 Kennesaw GA.jpg`); backlit endcaps — `examples/pipelines/epson/planogram.py` (Epson Scanners), `examples/pipelines/bose/planogram.py` (Bose S1 Pro+).
- Ledger: `wikitoolkit ledger context` reports no open issues for `plan.py`, `legacy.py`, `types/abstract.py`, `product_on_shelves.py`, `endcap_backlit_multitier.py`.

### Does NOT Exist (Anti-Hallucination)

- ~~`examples/planogram/e2e/`~~ — does not exist yet; this feature creates it (and its `.gitignore` negation rules).
- ~~`ask_to_image` on the Bedrock / Nova client~~ — implemented only on the Anthropic, Google and OpenAI clients; `BedrockConverseBase` drops image attachments (`packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py:736-742`). Nova works only through the example shim `examples/planogram/aws/nova_vision.py`.
- ~~`"tv_wall"` planogram type~~ — mentioned in the `PlanogramConfig.planogram_type` description and old examples/tests, not registered in `_PLANOGRAM_TYPES`.
- ~~A layout-profile / layout section in `PlanogramConfig`~~ — not a field today; only `perception_mode`, `verify_pass` and `rule_bindings` are read from `planogram_config`.
- ~~`IdentifyStrategy.SLOTS` / per-slot crop strategy~~ — only `FULL_IMAGE` and `STRIPS` exist.
- ~~Reference images in the cycle identify path~~ — `_run_call` sends one image; nothing passes `images[1:]` today.
- ~~Per-slot OCR in the package~~ — the package OCRs price tags (`InkWall._read_tags`) and fact tags / zones (`ProductOnShelves._ocr_tags_and_zones`); OCR of slot boxes exists only in `examples/planogram/aws/nova2.py:103`.
- ~~`convert_config` for types other than `product_on_shelves`~~ — raises `ValueError`.
- ~~A DB-writing migration~~ — `migration.py` never writes; `preflight` is read-only.
- ~~`parrot/pipelines/planogram/` with real code in core~~ — it is a proxy that re-exports `parrot_pipelines.planogram`.
- ~~Tracked scripts under `examples/pipelines/`~~ — that tree is git-ignored and untracked; the scripts importing `PlanogramCompliancePipeline` exist only in the local checkout.
- ~~`examples/planogram/pipelines/` in git~~ — `run_ink_wall.py`, `ink_wall_definition.py` and `README.md` are currently **untracked** in the main checkout; a worktree cut from `origin/dev` will not contain them.

---

## Parallelism Assessment

- **Internal parallelism**: good in the middle, serial at the ends.
  1. *Foundation* (serial): layout profile model + shared stage toolkit + identify v2 (OCR-anchored
     prompt, per-slot OCR, reference bank). Touches `abstract.py`, `contracts.py`, `identify.py`,
     `plan.py`.
  2. *Independent from the start*: removal of `legacy.py` and its exports/proxy (touches
     `planogram/__init__.py`, `parrot_pipelines/__init__.py`, core proxy, `detector.py`) — no
     overlap with the foundation files.
  3. *Parallel wave*: one task per type — `endcap_backlit_multitier`,
     `endcap_no_shelves_promotional`, `graphic_panel_display`, `product_counter` — each owns its
     type file and its test file; plus `ink_wall` and `product_on_shelves` moving their constants
     into the profile (the latter also deletes its legacy half).
  4. *Serial tail*: remove the legacy contract, `legacy_adapter.py` and `LegacyPayload` (needs
     every type migrated) → converter for six types → docs → E2E suite.
- **Cross-feature independence**: no in-flight spec touches `parrot_pipelines/planogram/`. Live
  worktrees are FEAT-584 (`sdd-execution-optimization`) and two `fix/*` branches, none in this
  area. The only collision risk is the untracked `examples/planogram/pipelines/` folder in the
  main checkout.
- **Recommended isolation**: `mixed`.
- **Rationale**: the four type migrations are file-disjoint and the largest share of the work,
  so sub-worktrees pay off there; the foundation and the contract removal rewrite the shared
  files (`abstract.py`, `plan.py`, `contracts.py`) and must run alone, in order.

---

## Open Questions

- [x] Flow type and base branch — *Owner: Jesus Lara*: feature → `dev`.
- [x] What "complete replacement" means given FEAT-574 already landed the cycle — *Owner: Jesus Lara*: finish the migration; keep `run()` and `contracts.py`, delete the legacy contract, `legacy_adapter.py` and `legacy.py`.
- [x] Which types must run on the three-step path — *Owner: Jesus Lara*: all six migrate.
- [x] What "backward-compatible" covers — *Owner: Jesus Lara*: handler call + HTTP contract and the eight legacy result keys; stored DB configs are migrated to the new design; old import names are not preserved.
- [x] How flexible the types must be — *Owner: Jesus Lara*: thin classes, layout in configuration.
- [x] Stage 1 for fixtures without a price-tag grid — *Owner: Jesus Lara*: OpenCV first, LLM-detector fallback.
- [x] How reference images are used — *Owner: Jesus Lara*: sent to the LLM in the same call as the strip / crop and the OCR text.
- [x] How the E2E runs — *Owner: Jesus Lara*: live, local assets, skipped when photos or credentials are missing; not a CI gate.
- [x] Nova 2 Lite as a real backend — *Owner: Jesus Lara*: out of scope; the pipeline stays backend-neutral.
- [x] Local OCR default — *Owner: Jesus Lara*: on when the `planogram` extra is installed; the OCR-anchored prompt becomes the package default.
- [x] DB migration deliverable — *Owner: Jesus Lara*: converter + dry run for six types; a human applies the SQL.
- [x] E2E pass bar — *Owner: Jesus Lara*: hand-labelled ground truth with tolerances.
- [ ] Which concrete fixtures does the E2E use for product on shelves and endcap backlit? Candidates found locally: Epson EcoTank (`examples/pipelines/test_pure_planogram.py`, five reference images) for shelves; Epson Scanners or Bose S1 Pro+ for the backlit endcap — and is the endcap case `endcap_backlit_multitier` or a `product_on_shelves` config with a backlit header? — *Owner: Jesus Lara*
- [ ] May ground-truth files be committed? They describe retailer fixtures. Default assumed: git-ignored like the photos, with a committed schema and template, so the E2E skips when they are absent. — *Owner: Jesus Lara*
- [ ] `examples/planogram/pipelines/` is untracked in the main checkout. Commit it to `dev` before `/sdd-task` so the feature worktree can build the ink-wall E2E on it, or re-create that case inside `e2e/`? — *Owner: Jesus Lara*
- [ ] What happens to `PlanogramConfig` fields and DB columns that become unused (`roi_detection_prompt`, `object_identification_prompt`, `detection_model`, `confidence_threshold`, `detection_grid`)? Default assumed: keep them accepted and ignored for one release, drop later. — *Owner: Jesus Lara*
- [ ] Remove `ObservationSource.LEGACY_LLM`, `AssessmentStatus.LEGACY_UNMEASURED` and `EvidenceWeights.legacy_llm`, or keep the enum members so stored historical results still deserialise? — *Owner: Jesus Lara*
- [ ] Does the whole `parrot.pipelines` core proxy stay (minus the two legacy names), or is it removed too? `packages/ai-parrot/tests/test_monorepo_imports.py` exercises it. — *Owner: Jesus Lara*
- [ ] `parrot_pipelines/detector.py` (`AbstractDetector`, `ultralytics` / `torch`) and the `grid/` strategy + detector are used only by legacy code: remove with it? (`grid/merger._compute_iou` must survive — `identify.py:26` uses it.) — *Owner: spec author, to verify*
- [ ] Is a per-slot crop identification strategy needed in this feature? The Nova run showed end-of-strip misses that strips do not fix (`examples/planogram/aws/README.md`, limitation 5). — *Owner: Jesus Lara*
- [ ] Reference bank policy: maximum references per call and how they are selected (all, per shelf, per brand) — needs a measurement on the shelves fixture. — *Owner: spec author*
- [ ] Zone-centric types need more than the four `ZoneKind` values and four `RuleKind` values? (e.g. advertisement / graphic panel / counter, a counting rule for `product_counter`.) — *Owner: spec author*
- [ ] Is the ink-specific `Descriptors` model (`family`, `xl`, `colors`, `pack`) generalised into a free descriptor map, or kept with a configurable vocabulary on top? — *Owner: spec author*
- [ ] Deployment order: who migrates the production rows of `troc.planograms_configurations`, and when, relative to the release that makes `slots_definition` mandatory for every type? — *Owner: Jesus Lara*
