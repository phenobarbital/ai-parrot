---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: New Planogram Compliance Algorithm (label-anchored, autonomous)

**Feature ID**: FEAT-565
**Date**: 2026-09-17
**Author**: Jesus Lara
**Status**: draft
**Target version**: next

---

## 1. Motivation & Business Requirements

> Input: `sdd/proposals/new-planogram-compliance-algo.brainstorm.md` (Status: accepted, Option D).

### Problem Statement

We need an **autonomous** script — `examples/planogram/planogram_check.py` — that
takes the photos of one store fixture plus a planogram definition and returns a
structured JSON with detected products, names, prices, empty slots, occupancy by
brand, and a planogram-compliance score (overall and per shelf). No human review
step, no model training.

The requested procedure has five steps:

1. Detect prominent, easy-to-find shapes that are later confirmed as **price tags**.
2. Use the tags as **anchors** to derive product areas and occupancy; OCR the tag
   for price.
3. **Compare** every detected product with the planogram definition; when a
   product cannot be read, **infer** it from the planogram reference.
4. Compute occupancy, empty areas and **share of occupation by brand**; brand +
   product identification is done by a vision LLM constrained to the detected
   areas (photo + JSON of areas), so it cannot report products outside them.
5. Compare the composed ("as-observed") planogram with the definition and **score** it.

Two assets exist and both stop short:

- `white_label_detector/detect_price_labels.py` solves step 1 (on `image_01`:
  56 tag candidates in 5 consistent rows + 6 unassigned) but does no OCR, no
  product recognition, no scoring.
- `inkcheck/` implements steps 1, 2 and 5, but **its autonomous mode yields 0 %**
  (`results/auto-run2/report.json`: 117 regions, `unmapped_regions: 117`,
  `status_counts: {"unknown": 104}`, `occupancy_coverage: 0.0`) because
  (a) there is **no registration** — `Region.facing_id` is only set by the manual
  `review.html`, and `compare()` ignores observations without it; and
  (b) **per-crop identification with a 1.6 B model is too weak** (94/117 graded
  `low`) while `catalog.resolve()` refuses to use shelf expectations, so nothing
  is ever inferred.

The gap this feature closes: **automatic registration + planogram-aware
identification + inference + scoring**, on top of the tag detector that works.

Facts that constrain the design (established in the brainstorm):

- Tags sit on the shelf edge **below** their products. `image_01` (4032×3024)
  shows 5 tag rows; the 6th (bottom) shelf is visible but **its tags are out of
  frame**. The planogram has 6 shelves.
- Tag crops are ~200×110 px: the dollar price is legible, the product-name line
  and QR are not. **Tag OCR yields price only**; identity comes from the package.
- RapidOCR probe (4× upscale, 56 crops): digits in 40/56 (71 %); whole dollars
  correct, superscript **cents garbled** (`45%` for `$45.99`).
- The planogram identifies products by **manufacturer part number**
  (`C2P04AN#140`); packages show consumer names ("HP 62"). It has no consumer
  name, no price, no physical width. 40/102 positions are `read_method: inferred`.
- **Brand sequences cannot register a photo**: shelves 1–5 all start with 9 HP
  positions. Registration needs vertical order, product-family evidence and the
  HP→Epson/Canon segment boundary.
- The two photos overlap; neither covers the whole 8 ft gondola.

### Goals

- G1. A CLI `examples/planogram/planogram_check.py` (thin entry point) backed by
  a sibling helper package `examples/planogram/plancheck/` — one module per stage.
- G2. **Fully autonomous** run: no review page, no manifest editing, no CLI hints.
- G3. Tag-anchored **slot grid** including gap-filled slots and a synthesized
  untagged bottom row.
- G4. **Local-first price OCR** with vision-LLM fallback; raw + normalised price
  on every slot that has a tag.
- G5. **Area-constrained vision identification**: one full-resolution row strip +
  JSON of slot boxes per call; answers keyed by supplied slot id only.
- G6. **Deterministic registration**: monotone 2-D alignment (rows→shelves,
  slots→facings); the LLM never assigns planogram positions.
- G7. **Closed-set verification pass** (expected product + distractors, evidence
  mandatory) for registered, occupied, unresolved slots; switchable off.
- G8. **N photos of one fixture** merged per planogram facing.
- G9. **Tiered scoring**: strict % and lenient % side by side, per shelf and
  overall, plus coverage, occupancy and brand share (facings and linear).
- G10. Optional `--prices` file adds a **separate** price-compliance metric.
- G11. Vision LLM reached **only through ai-parrot client methods** — no script code
  ever touches a provider SDK handle: Gemini Flash (default `google:gemini-3.8-flash`),
  any other `provider:model` whose client has `ask_to_image()`, and local llama.cpp
  (`llamacpp:<alias>` + `--base-url`) **once the prerequisite feature
  `localllm-ask-to-image` lands** (§ Worktree Strategy, §8 Q7).
- G12. Code, tests and the detector script are **tracked in git** (the directory is
  ignored today). `planogram_page1.json` (retailer-derived; the repo is PUBLIC),
  store photos and results stay **untracked** and are read from the primary checkout.

### Non-Goals (explicitly out of scope)

- No LLM-generated catalog: the part-number ↔ consumer-descriptor **catalog is
  supplied by the user** (`--catalog`, required). No enrichment module in v1.
- No per-crop LLM mode (brainstorm Option A) and no "LLM does the mapping" mode
  (Option C) — rejected in the brainstorm.
- No change to `parrot_pipelines.planogram`, to `inkcheck/`, or to any core
  client **within this feature**. `parrot/clients/base.py` is not modified. The
  script-local adapter only reconciles two existing method signatures; it never
  calls `chat.completions` or any SDK object. Vision for `LocalLLMClient` is delivered
  by the separate prerequisite feature `localllm-ask-to-image`, not here.
- No perspective rectification of shelf planes; axis-aligned boxes only.
- No price database, currency conversion or sale-price interpretation.
- No identification-accuracy claim: there is no ground truth for the two photos.
- No tracking of store photos, videos, PDFs or result artefacts.

---

## 2. Architectural Design

### Overview

Option D — **two-pass hybrid**: an unbiased open-set pass produces identity
anchors; a deterministic alignment registers every slot to a planogram facing;
a bounded closed-set pass visually verifies what the planogram expects where
pass 1 could not read the product; anything still unread but occupied is
flagged `inferred`. Strict and lenient scores are reported side by side so the
expectation-assisted number never masquerades as the unbiased one.

Eight stages. Stages 1, 2, 4, 6, 8 are deterministic Python; 3, 5, 7 call OCR/LLM.

1. **Tag detection** — multi-threshold contour candidates + row-consensus
   grouping, adapted verbatim from `detect_price_labels.py`, at a 2048-px working
   width with coordinates kept in original pixels; optional normalised ROI.
2. **Slot grid** — (a) *tag-anchored* slots: horizontal bounds from neighbouring
   tag centres clamped to ±0.85 median tag width (±0.65 at row ends); top = the
   previous row's fitted line + 0.7 tag height (first row: tag top − 0.7 row gap);
   bottom = tag top. (b) *gap-filled* slots: where the centre-to-centre distance
   between consecutive tags is within ±25 % of `k ×` the row's median pitch
   (k ≥ 2), synthesize k−1 slots; otherwise none. (c) *untagged row*: if at least
   0.6 × median row pitch of image remains below the last tag row, synthesize one
   row using the column boundaries of the row above. Origins are recorded.
3. **Tag price reading** — 4× bicubic upscale; RapidOCR; a price grammar accepts
   only *dollars + two-digit cents*. Everything else goes to the vision LLM as
   **one numbered contact sheet per row**. Dollars-only reads that the LLM cannot
   complete are kept as `partial` (raw text, `amount = null`). Digits are never guessed.
4. **Reference load** — planogram JSON → facings ordered by the physical axis
   **`slot`** (validated contiguous `1..n` per shelf; `position` is *not* monotone —
   shelf 1 reads 1,2,3,4,5,8,6,7 — and must never be used for ordering), multi-facing
   positions expanded, `CLOSEOUT` → occupancy-only; **required** catalog file; optional
   prices file. `--emit-catalog-template` writes a skeleton with every planogram
   SKU for the user to fill, then exits.
5. **Pass 1 — open-set identification** — per visible row: full-resolution strip
   with thin numbered slot outlines (Set-of-Marks, **on by default**; the first real run A/Bs it with
   `--no-marks`, the README records the result, and the default is flipped if marks hurt) + JSON of slot boxes normalised
   to the strip (0–1000, `[ymin, xmin, ymax, xmax]`). Structured response keyed by
   slot id; unknown ids are dropped and counted as errors. The model is **not**
   told what is expected. Readings are resolved against the catalog.
6. **Registration** — per photo: enumerate order-preserving row→shelf
   assignments; each (row, shelf) pair is scored by a semi-global, gap-tolerant
   sequence alignment of observed slots against the shelf's facings. Best total
   wins; runner-up and margin are recorded and drive a registration grade.
7. **Pass 2 — closed-set verification** (skippable) — per row, only for slots that
   are registered, occupied and unresolved: expected product + 2–3 distractors +
   `other` + `cannot_tell`, deterministic option order, evidence mandatory.
   Choosing the expected product → `verified_by_expectation`; without evidence it
   is downgraded to `inferred`.
8. **Merge, score, report** — observations from all photos merged per facing;
   tiered statuses; strict/lenient/coverage/occupancy/brand/price metrics;
   `compliance.json`, annotated images, crops, run snapshot.

**User-facing behaviour.** CLI options: `--images-dir` (default
`examples/planogram/images/`) | `--images f1 f2 …` (mutually exclusive);
`--planogram` (default `planogram_page1.json` next to the script); `--catalog`
(required); `--output <new dir>` (must not exist); `--llm provider:model`
(default `google:gemini-3.8-flash`); `--ocr-llm` (default = `--llm`);
`--base-url`; `--prices`; `--roi L T R B`; `--verify-pass` / `--no-verify-pass`
(default: **on for cloud backends, off for local backends** — the local model is
LFM2.5-VL-1.6B, too weak for the discrimination task); `--no-marks`
(A/B switch for the Set-of-Marks overlay); `--concurrency`
(default 4; 1 when the provider is a local server); `--cache-dir` (default
`examples/planogram/results/.plancheck_cache`); `--visit-id`;
`--emit-catalog-template <path>`. Exit codes: `0` complete, `2` complete with
recorded model/OCR errors (results still written), `1` invalid input.

Artefacts in `--output`: `compliance.json` (primary), `annotated_<image_id>.jpg`,
`slots/`, `tags/`, `run.snapshot.json` (settings, model ids, prompt versions,
input hashes). LLM/OCR-fallback responses are cached in `--cache-dir`, keyed by
(llm string, base URL, generation params, stage, prompt version, **full prompt
text** — which embeds slot JSON, options and distractors — schema, and the hashes
of the **rendered** images, overlays included); entries are written atomically
(temp file + rename); failed calls are never cached.

### Component Diagram
```
planogram_check.py (CLI) ──→ plancheck.pipeline.run_check()
                                   │
   ┌───────────────────────────────┼────────────────────────────────────────┐
   ▼                               ▼                                        ▼
detection.detect_tags      reference.load_planogram               vision.VisionBackend
   │                       reference.load_catalog (required)        │  (LLMFactory → parrot client,
   ▼                       reference.load_prices (optional)         │   disk cache, schema validation)
grid.build_slots ──────────────────┐                                │
   │                               │                                │
   ├──→ prices.read_prices ────────┼──── OCR first ── fallback ─────┤
   │                               │                                │
   └──→ identify.identify_rows ────┼──── pass 1 (open-set) ─────────┤
              │  reference.resolve_identity                         │
              ▼                                                     │
        registration.register_image   (deterministic, no LLM)       │
              │                                                     │
              ▼                                                     │
        verify.verify_rows ──────────── pass 2 (closed-set) ────────┘
              │
              ▼
        scoring.merge_and_score ──→ report.write_report
        (models.py is imported by every module)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.clients.factory.LLMFactory` | uses | `create("provider:model", model_args=…, **kwargs)`; `base_url`/`api_key` pass through `**kwargs` |
| `GoogleGenAIClient.image_understanding()` | uses | multi-image + `structured_output`; result on `AIMessage.structured_output` |
| `OpenAIClient` / `AnthropicClient` `.ask_to_image()` | uses (generic lane) | first image → `image`, rest → `reference_images`, `structured_output=schema` |
| `LocalLLMClient` | uses (generic lane) — **after prerequisite** | has no vision method today; gains `ask_to_image()` from feature `localllm-ask-to-image`. Until then `--llm llamacpp:…` exits 1 with a message naming that feature |
| `parrot/clients/base.py` | none | **not modified** |
| `examples/planogram/white_label_detector/detect_price_labels.py` | adapted copy | `candidates()`, `group_rows()`; original untouched, becomes tracked |
| `examples/planogram/inkcheck/` | reference only | not imported |
| `.gitignore` | modifies | line 5 `examples/planogram/` replaced by a fine-grained block placed after the `examples/**` rules; `planogram_page1.json` stays ignored |
| `packages/ai-parrot-pipelines/.../planogram/` | none | untouched |

### Data Models

All in `plancheck/models.py`, Pydantic v2, `extra="forbid"`. Field lists are
normative; see the Module 1 skeleton for exact types.

- **Reference**: `PlanogramFacing`, `PlanogramRef`, `CatalogItem`, `Catalog`.
- **Geometry**: `Box` (`tuple[int,int,int,int]`, x1,y1,x2,y2, original pixels),
  `Tag`, `TagRow`, `Slot` (`origin`: `tag_anchored | gap_filled | untagged_row`).
- **Perception**: `PriceReading`, `SlotReading` / `RowReading` (pass 1 contract),
  `VerificationReading` / `RowVerification` (pass 2 contract),
  `TagPriceReading` / `RowPriceReading` (price fallback contract).
- **Fusion**: `SlotObservation` (`resolution`: `direct | verified_by_expectation |
  inferred | ambiguous | unresolved`), `RowRegistration`, `ImageRegistration`.
- **Result**: `PositionResult` (`status`: `match | misplaced | variant_unresolved |
  mismatch | empty | inferred_present | occupied_unassigned | conflict |
  not_assessed | not_visible`), `ShelfScore`, `BrandShare`, `PriceCompliance`,
  `ComplianceSummary`, `RunInfo`, `ComplianceReport`.
- **Config**: `ScoringWeights`, `Settings`.

`compliance.json` = `ComplianceReport.model_dump(mode="json")`:
`run`, `images[]` (detected rows, registration with score/runner-up/margin/grade),
`slots[]` (one `SlotObservation` per slot per photo), `positions[]` (one
`PositionResult` per expected facing), `shelves[]`, `brands[]`, `compliance`, `notes`.

### New Public Interfaces

```python
# examples/planogram/planogram_check.py
def main(argv: Sequence[str] | None = None) -> int: ...

# examples/planogram/plancheck/pipeline.py
async def run_check(settings: Settings) -> ComplianceReport: ...
```

### Decided semantics (normative — tasks must not re-decide these)

**Catalog resolution** (`reference.resolve_identity`), in order, always within
the reading's normalised brand:
1. *Identifier*: a normalised token of `visible_text` equals a catalog
   `identifiers` entry → that SKU.
2. *Descriptor signature*: `family` equal AND `xl` equal (reading `xl` not null)
   AND colour set equal (when the item lists colours) AND `pack` equal (when the
   reading has one). Exactly one item → that SKU.
3. *Alias*: `rapidfuzz.fuzz.token_set_ratio(alias, line) ≥ 92` for exactly one item.
- One SKU → `direct`. Several → `ambiguous` with `candidate_skus`. None → `unresolved`.
- XL vs standard, colour and pack variants are **never** fuzzy-merged. `rapidfuzz`
  is used only for brand-name normalisation (≥ 90) and rule 3.

**Alignment scores** (per observed slot vs expected facing): same SKU (`direct`)
+4 · expected SKU ∈ `candidate_skus` +3 · same brand and family +2 · same brand
+1 · occupied with no brand 0 · empty 0 · CLOSEOUT facing vs any occupied 0 ·
different brand −2. Gaps: interior gap −1.5 on either sequence; leading/trailing
gaps on the **planogram** side 0 (partial view); leading/trailing gaps on the
**observed** side −0.5 (neighbouring-fixture slots → `unregistered`).
Pitch check: an alignment step that skips `k` facings must span `k+1` median
pitches ±35 %, else −1 per violation. Vertical prior: +1 per pair of adjacent
rows mapped to consecutive shelves; +2 when row count equals shelf count.
Ties → lowest shelf numbers. Grade: `high` if margin ≥ 3 and ≥ 2 direct anchors
in the row; `low` if margin < 1 or 0 anchors; else `medium`. `low` rows are
capped at lenient-only credit.

**Position status** for facing F expecting SKU S (after multi-photo merge):
- `not_visible` — no registered slot maps to F in any photo (**unseen** fixture area).
- `not_assessed` — a slot maps to F but every view is `uncertain`/`unusable` or its
  row call failed (**seen but unknown**). Unseen and unknown are never reported as `empty`.
- `conflict` — reliable views disagree (occupied vs empty, or two different
  `direct` SKUs). An `uncertain`/unresolved view never erases a positive one;
  agreeing views count once.
- `empty` — slot empty with `visibility = full` (an `empty` claim with partial
  visibility is downgraded to `uncertain` → treated as not assessed).
- `match` — slot resolved to S (`direct` or `verified_by_expectation`).
- `misplaced` — F's own slot is not a match, but S is observed `direct` in
  another registered slot of the **same shelf** whose own facing it does not match.
- `variant_unresolved` — occupied, `ambiguous` with S ∈ candidates, or brand +
  family equal to S's catalog entry with the variant unread.
- `mismatch` — occupied and resolved to a different SKU, or observed brand
  differs from the expected brand.
- `inferred_present` — occupied, registered, unresolved, brand absent or equal.
- `occupied_unassigned` — occupied facing with `identity_required = false` (CLOSEOUT).

**Credits.** Strict: `match` via `direct` = 1, everything else 0. Lenient:
`match` (`direct`) 1 · `match` (`verified_by_expectation`) `w.verified_by_expectation`
(default 1.0) · `misplaced` `w.misplaced` (0.5) · `variant_unresolved` (0.5) ·
`inferred_present` (0.5) · others 0. Rows graded `low` contribute 0 to strict.
Weights live in `ScoringWeights` and are overridable from the CLI settings.

**Metrics.** `coverage` = facings not in {`not_visible`, `not_assessed`, `conflict`} / all
facings. `strict_pct`, `lenient_pct` = Σ credits / decided SKU-specific facings
(decided = `identity_required` and covered). `occupancy_pct` = occupied /
(occupied + empty). Undefined ratios are `null`. Brand share: expected facings
share vs observed facings share (observed brand; unknown bucket kept) vs
**linear share** (slot widths normalised by their row's total slot width).
Price compliance (only with `--prices`): over facings with `match` and a `read`
price — equal `Decimal` amounts = match; SKUs missing from either side are listed.
Cross-photo price agreement compares **normalised amounts**, never raw strings;
different amounts → price `conflict` with every raw reading retained.
**Reference confidence** is a separate dimension: `strict_pct_direct_reference` /
`lenient_pct_direct_reference` repeat the two scores over facings whose planogram
entry was read `direct` (58 of 102 today); `run.reference_provisional` stays `true`
while any entry is `inferred`/`partial`, and the report says so in `notes`.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M0: repo-tracking | no | exact ignore block given in §7 | must run in the primary checkout (inputs are untracked there) and is gated on §8 Q1 |
| M1: models | yes | every model + field fixed in the skeleton | — |
| M2: reference | yes | loaders, template emitter, 3-rule resolution fixed in §2 | — |
| M3: detection | yes | verbatim adaptation of two verified functions | — |
| M4: grid | yes | clamps, gap tolerance (±25 %), untagged-row threshold (0.6 pitch) fixed | — |
| M5: prices | yes | grammar, contact-sheet contract, `partial` rule fixed | — |
| M6: vision | yes | two duck-typed lanes, no-vision-method error, cache key recipe, one repair retry fixed | — |
| M7: identify | yes | strip/SoM/JSON contract, id filtering fixed | prompt wording is the implementer's; the *schema* is not |
| M8: registration | yes | score table, gap costs, prior, grade thresholds fixed in §2 | — |
| M9: verify | yes | distractor policy, option order, downgrade rule fixed | — |
| M10: scoring | yes | status decision list, credits, metrics fixed in §2 | — |
| M11: report | yes | artefact list and colour legend fixed | — |
| M12: pipeline-cli | yes | stage order, concurrency, exit codes fixed | — |

### Module 0: repo-tracking
- **Path**: `.gitignore`; adopts `examples/planogram/white_label_detector/detect_price_labels.py`
- **Responsibility**: make the feature's code and small inputs trackable; keep photos/results/PDFs/videos ignored. Replace `.gitignore:5` with the block in §7. Commit the existing detector script. `planogram_page1.json` is deliberately NOT adopted (§8 Q1).
- **Depends on**: nothing. **Every other module depends on it** (without it `git add` silently drops their files).
- **Execution constraint**: performed in the **primary checkout** directly on `dev` (single commit) *before* the feature worktree is created — the adopted detector script exists only there.
- **Interface Skeleton**: none (configuration + file adoption). Verification commands:
  ```bash
  git check-ignore -q examples/planogram/plancheck/models.py;        test $? -eq 1   # not ignored
  git check-ignore -q examples/planogram/tests/test_plancheck_grid.py; test $? -eq 1
  git check-ignore -q examples/planogram/planogram_check.py;         test $? -eq 1
  git check-ignore -q "examples/planogram/images/a.jpeg";            test $? -eq 0   # still ignored
  git check-ignore -q examples/planogram/results/x/compliance.json;  test $? -eq 0
  git check-ignore -q examples/planogram/inkcheck/README.md;         test $? -eq 0
  git check-ignore -q examples/planogram/planogram_page1.json;       test $? -eq 0   # retailer data stays local
  ```

### Module 1: models
- **Path**: `examples/planogram/plancheck/__init__.py`, `examples/planogram/plancheck/models.py`
- **Responsibility**: every shared data structure and the LLM response contracts.
- **Depends on**: M0
- **Interface Skeleton**:
  ```python
  # examples/planogram/plancheck/models.py  (new)
  """Shared Pydantic v2 models for the planogram compliance check (FEAT-565)."""
  from decimal import Decimal
  from typing import Literal
  from pydantic import BaseModel, ConfigDict, Field

  Box = tuple[int, int, int, int]  # x1, y1, x2, y2 — ORIGINAL image pixels
  SlotOrigin = Literal["tag_anchored", "gap_filled", "untagged_row"]
  OccupancyState = Literal["occupied", "empty", "uncertain"]
  Visibility = Literal["full", "partial", "unusable"]
  Resolution = Literal["direct", "verified_by_expectation", "inferred", "ambiguous", "unresolved"]
  Grade = Literal["high", "medium", "low"]
  PriceStatus = Literal["read", "partial", "unreadable", "not_assessed", "conflict"]
  PositionStatus = Literal["match", "misplaced", "variant_unresolved", "mismatch", "empty",
                           "inferred_present", "occupied_unassigned", "conflict", "not_assessed", "not_visible"]

  class StrictModel(BaseModel):
      """Base: unknown fields are rejected."""
      model_config = ConfigDict(extra="forbid")

  class PlanogramFacing(StrictModel):
      """One expected physical facing. ``facing_id`` = f"p{position:03d}_f{facing}"."""
      facing_id: str; position: int; shelf: int; segment: str
      slot: int; segment_slot: int; facing: int   # ``slot`` is the physical left→right axis (NOT ``position``)
      sku: str; brand: str | None; identity_required: bool
      source_confidence: str = "unknown"; reference_read_method: str = "unknown"   # direct | inferred | partial
      notes: str | None = None

  class PlanogramRef(StrictModel):
      planogram_id: str; source: str; shelf_count: int; facings: list[PlanogramFacing]
      def shelf(self, number: int) -> list[PlanogramFacing]:
          """Facings of one shelf ordered by (slot, facing)."""

  class CatalogItem(StrictModel):
      sku: str; brand: str; display_name: str
      family: str | None = None; xl: bool = False
      colors: list[str] = Field(default_factory=list); pack: int = 1
      identifiers: list[str] = Field(default_factory=list)
      aliases: list[str] = Field(default_factory=list)
      provenance: str | None = None          # where this mapping came from (file, person, date)

  class Catalog(StrictModel):
      items: list[CatalogItem]
      def by_sku(self, sku: str) -> CatalogItem | None: ...

  class Tag(StrictModel):
      tag_id: str; image_id: str; row: int; position: int
      box: Box; crop_box: Box; rectangularity: float

  class TagRow(StrictModel):
      image_id: str; row: int; slope: float; intercept: float   # line in ORIGINAL pixels
      tags: list[Tag]; synthesized: bool = False

  class Slot(StrictModel):
      slot_id: str            # f"{image_id}_r{row:02d}_s{index:02d}"
      image_id: str; row: int; index: int; box: Box
      tag_id: str | None = None; tag_box: Box | None = None; origin: SlotOrigin

  class PriceReading(StrictModel):
      raw: str | None = None; amount: Decimal | None = None; currency: str | None = None
      source: Literal["ocr", "llm", "none"] = "none"; status: PriceStatus = "not_assessed"

  class SlotReading(StrictModel):            # pass-1 LLM contract, one per slot
      slot_id: str; occupancy: OccupancyState; visibility: Visibility
      brand: str | None = None; family: str | None = None; xl: bool | None = None
      colors: list[str] = Field(default_factory=list, max_length=8)
      pack: int | None = None
      visible_text: list[str] = Field(default_factory=list, max_length=20)
      evidence: str = Field(default="", max_length=400)

  class RowReading(StrictModel):
      slots: list[SlotReading]

  class VerificationReading(StrictModel):    # pass-2 LLM contract
      slot_id: str; choice: str              # a SKU from the offered options | "other" | "cannot_tell"
      evidence: str = Field(default="", max_length=400)

  class RowVerification(StrictModel):
      slots: list[VerificationReading]

  class TagPriceReading(StrictModel):        # price-fallback LLM contract
      cell: int; price_text: str | None

  class RowPriceReading(StrictModel):
      tags: list[TagPriceReading]

  class SlotObservation(StrictModel):
      slot: Slot; reading: SlotReading | None = None
      resolved_sku: str | None = None; candidate_skus: list[str] = Field(default_factory=list)
      resolution: Resolution = "unresolved"
      price: PriceReading = Field(default_factory=PriceReading)
      facing_id: str | None = None           # None = unregistered
      registration_grade: Grade | None = None
      issues: list[str] = Field(default_factory=list)

  class RowRegistration(StrictModel):
      image_id: str; row: int; shelf: int | None; score: float
      anchors: int; grade: Grade; assignments: dict[str, str]   # slot_id -> facing_id

  class ImageRegistration(StrictModel):
      image_id: str; rows: list[RowRegistration]; total_score: float
      runner_up_shelves: list[int | None] | None = None; margin: float | None = None

  class ScoringWeights(StrictModel):
      misplaced: float = 0.5; variant_unresolved: float = 0.5
      inferred_present: float = 0.5; verified_by_expectation: float = 1.0

  class PositionResult(StrictModel):
      facing: PlanogramFacing; status: PositionStatus; resolution: Resolution | None = None
      strict_credit: float; lenient_credit: float
      observed_sku: str | None = None; observed_brand: str | None = None
      price: PriceReading | None = None
      price_expected: Decimal | None = None; price_match: bool | None = None
      slot_ids: list[str] = Field(default_factory=list)

  class ShelfScore(StrictModel):
      shelf: int; expected: int; covered: int; decided: int
      strict_pct: float | None; lenient_pct: float | None; occupancy_pct: float | None
      empty_facing_ids: list[str]

  class BrandShare(StrictModel):
      brand: str; expected_facings: int; expected_share: float
      observed_facings: int; observed_share: float | None; linear_share: float | None
      occupancy_pct: float | None

  class PriceCompliance(StrictModel):
      compared: int; matched: int; match_pct: float | None
      mismatches: list[str]; skus_missing_from_prices: list[str]; unknown_price_skus: list[str]

  class ComplianceSummary(StrictModel):
      strict_pct: float | None; lenient_pct: float | None; coverage: float
      occupancy_pct: float | None; products_expected: int; products_present: int
      unexpected_skus: list[str]; price: PriceCompliance | None = None
      # Reference-confidence dimension (S7): same metrics restricted to facings whose
      # planogram entry is ``reference_read_method == "direct"``.
      reference_direct_facings: int; strict_pct_direct_reference: float | None
      lenient_pct_direct_reference: float | None

  class ImageInfo(StrictModel):
      image_id: str; path: str; sha256: str; width: int; height: int
      tag_rows: int; tags: int; slots: int
      registration: ImageRegistration | None = None

  class RunInfo(StrictModel):
      visit_id: str; planogram_id: str; llm: str; ocr_llm: str; verify_pass: bool
      started_at: str; finished_at: str; errors: list[str]
      catalog_missing_skus: list[str]
      registration_method: Literal["auto_alignment"] = "auto_alignment"   # never human-reviewed
      reference_provisional: bool = True      # True while any facing is not ``direct``-read
      local_ocr_available: bool = True

  class ComplianceReport(StrictModel):
      run: RunInfo; images: list[ImageInfo]; slots: list[SlotObservation]
      positions: list[PositionResult]; shelves: list[ShelfScore]; brands: list[BrandShare]
      compliance: ComplianceSummary; notes: list[str]

  class Settings(StrictModel):
      images: list[str]; planogram: str; catalog: str; output: str
      prices: str | None = None; llm: str = "google:gemini-3.8-flash"; ocr_llm: str | None = None
      base_url: str | None = None; roi: tuple[float, float, float, float] | None = None
      verify_pass: bool | None = None         # None = auto: True for cloud, False when backend.is_local
      marks: bool = True; concurrency: int = Field(default=4, ge=1, le=16)
      cache_dir: str; visit_id: str = "visit"; work_width: int = Field(default=2048, ge=256)
      weights: ScoringWeights = Field(default_factory=ScoringWeights)
  ```

### Module 2: reference
- **Path**: `examples/planogram/plancheck/reference.py`
- **Responsibility**: load planogram / catalog / prices; emit a catalog template; resolve a `SlotReading` to a SKU.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # examples/planogram/plancheck/reference.py  (new; facing expansion adapted from
  #   examples/planogram/inkcheck/inkcheck/catalog.py:5-20 — verified)
  def load_planogram(path: Path) -> PlanogramRef:
      """Parse ``{"planogram": {...}, "shelves": [...]}``; order each shelf by ``slot`` (never by
      ``position`` or dict order); expand ``facings``; CLOSEOUT → ``identity_required=False``;
      carry ``read_method`` → ``reference_read_method``. Raises ``ValueError`` on duplicate facing
      ids, empty input, or a shelf whose ``slot`` values are not exactly ``1..n``."""
  def load_catalog(path: Path, planogram: PlanogramRef) -> tuple[Catalog, list[str]]:
      """Return the catalog and the identity-required planogram SKUs it does not cover."""
  def load_prices(path: Path) -> dict[str, Decimal]:
      """``{"<sku>": "29.99"}`` → Decimals. Raises ``ValueError`` on a non-numeric value."""
  def emit_catalog_template(planogram: PlanogramRef, path: Path) -> None:
      """Write one ``CatalogItem`` skeleton per distinct identity-required SKU (brand + sku +
      identifiers=[sku] pre-filled). Refuses to overwrite an existing file."""
  def normalize_brand(text: str | None, catalog: Catalog) -> str | None:
      """Map free text to a catalog brand (exact casefold, then rapidfuzz ratio >= 90)."""
  def resolve_identity(reading: SlotReading, catalog: Catalog) -> tuple[str | None, list[str], Resolution]:
      """Apply the three §2 rules. Returns (sku, candidate_skus, 'direct'|'ambiguous'|'unresolved').
      Never uses planogram expectations."""
  ```

### Module 3: detection
- **Path**: `examples/planogram/plancheck/detection.py`
- **Responsibility**: price-tag candidates and row grouping for one image.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # examples/planogram/plancheck/detection.py  (new; adapts
  #   examples/planogram/white_label_detector/detect_price_labels.py:15-52 candidates(),
  #   :55-107 group_rows(), :123-126 ROI filter, :146-147 crop padding — verified)
  def find_candidates(image: np.ndarray, min_width: float = 0.025, max_width: float = 0.09) -> list[dict[str, Any]]:
      """Same thresholds/filters/NMS as the source function; boxes in ``image`` pixels."""
  def group_rows(items: list[dict[str, Any]], image_width: int, min_row_labels: int = 4,
                 max_slope: float = 0.12) -> tuple[list[dict[str, Any]], list[int]]:
      """Same line-consensus algorithm as the source function."""
  def detect_tags(image: np.ndarray, image_id: str, *, work_width: int = 2048,
                  roi: tuple[float, float, float, float] | None = None) -> tuple[list[TagRow], list[Box]]:
      """Downscale to ``work_width``, detect, rescale to original pixels.
      Returns (rows top→bottom with tags left→right, unassigned candidate boxes)."""
  ```

### Module 4: grid
- **Path**: `examples/planogram/plancheck/grid.py`
- **Responsibility**: slot boxes from tag rows (anchored, gap-filled, untagged row); strip cropping helpers.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # examples/planogram/plancheck/grid.py  (new; anchored-slot geometry adapted from
  #   examples/planogram/inkcheck/inkcheck/prepare.py:37-60 — verified)
  def row_pitch(row: TagRow) -> float:
      """Median centre-to-centre distance of consecutive tags (original pixels)."""
  def build_slots(rows: list[TagRow], image_size: tuple[int, int]) -> list[Slot]:
      """All slots of one image: tag-anchored, then gap-filled, then the untagged bottom row.
      ``image_size`` is (width, height). Degenerate boxes are skipped. Slot ``index`` is
      left→right within the row after gap filling; synthesized row number = last row + 1."""
  def strip_box(slots: list[Slot], image_size: tuple[int, int], pad: float = 0.04) -> Box:
      """Bounding box of one row's slots (+ their tags) padded, clipped to the image."""
  def to_strip_norm(box: Box, strip: Box) -> list[int]:
      """``[ymin, xmin, ymax, xmax]`` in 0–1000 relative to ``strip`` (Gemini convention)."""
  ```

### Module 5: prices
- **Path**: `examples/planogram/plancheck/prices.py`
- **Responsibility**: price grammar, local OCR, LLM contact-sheet fallback.
- **Depends on**: M1, M6
- **Interface Skeleton**:
  ```python
  # examples/planogram/plancheck/prices.py  (new)
  PRICE_PROMPT_VERSION: str
  def parse_price(text: str) -> PriceReading:
      """'$45.99' | '45 99' | "45⁹⁹" → read; dollars only → partial (amount None); else unreadable.
      Only whitespace and the cents superscript are normalised; digits are never inferred."""
  class TagOcr:
      """Lazy RapidOCR wrapper (``from rapidocr import RapidOCR``). ``available`` is False when
      the import fails — then every tag goes to the LLM fallback and the run logs one warning."""
      available: bool
      def read(self, crop: np.ndarray) -> str:
          """4× bicubic upscale → OCR → texts joined with ' | '. Synchronous/CPU-bound."""
  def contact_sheet(crops: list[np.ndarray], cell_height: int = 240) -> bytes:
      """One PNG with numbered cells (1-based) for the LLM fallback."""
  async def read_prices(image: np.ndarray, slots: list[Slot], ocr: TagOcr,
                        backend: "VisionBackend | None") -> dict[str, PriceReading]:
      """slot_id → PriceReading. OCR runs via ``asyncio.to_thread``; per row, tags that are not
      ``read`` go to ONE contact-sheet LLM call (schema ``RowPriceReading``). Slots without a
      tag → ``not_assessed``. LLM failure keeps the OCR result and records an issue upstream."""
  ```

### Module 6: vision
- **Path**: `examples/planogram/plancheck/vision.py`
- **Responsibility**: one vision + structured-output call over any ai-parrot client; disk cache.
- **Depends on**: M1 (none of its models — generic over the schema type)
- **Interface Skeleton**:
  ```python
  # examples/planogram/plancheck/vision.py  (new)
  T = TypeVar("T", bound=BaseModel)
  class VisionError(RuntimeError):
      """Provider, transport or schema failure after the repair retry."""
  class VisionBackend:
      """Adapter: prompt + images + Pydantic schema → validated instance."""
      def __init__(self, llm: str, *, cache_dir: Path, base_url: str | None = None,
                   api_key: str | None = None, max_tokens: int = 8192) -> None:
          """``LLMFactory.create(llm, model_args={"temperature": 0.0, "max_tokens": …}, **kw)``
          # verified: packages/ai-parrot/src/parrot/clients/factory.py:257 (kwargs merged at :334)"""
      async def __aenter__(self) -> "VisionBackend": ...   # enters the client (base.py:1155 — verified)
      async def __aexit__(self, *exc: object) -> None: ...
      @property
      def is_local(self) -> bool:
          """True for provider keys local/localllm/ollama/llamacpp/vllm."""
      async def ask(self, prompt: str, images: Sequence[bytes], schema: type[T], *, stage: str,
                    prompt_version: str) -> T:
          """Cache lookup → lane dispatch → validate → one repair retry → cache store.
          Lanes (duck-typed, in this order):
            1. ``hasattr(client, "image_understanding")`` → Google
               # verified: packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py:438
            2. ``hasattr(client, "ask_to_image")`` → generic (OpenAI :1468, Anthropic :1307 — verified;
               ``LocalLLMClient`` once feature ``localllm-ask-to-image`` lands): first image →
               ``image``, rest → ``reference_images``, ``structured_output=schema``
            3. neither → ``VisionError("client <name> has no vision method …")`` raised at
               ``__aenter__`` time so the CLI exits 1 before any work. NEVER reach into
               ``client.client`` / ``chat.completions`` / any SDK handle from this module.
          Raises ``VisionError``; failed calls are never cached."""
  def cache_key(llm: str, base_url: str | None, max_tokens: int, stage: str, prompt_version: str,
                prompt: str, schema: type[BaseModel], images: Sequence[bytes]) -> str:
      """sha256 over a canonical JSON of ALL arguments (images by their sha256)."""
  def cache_store(path: Path, payload: dict[str, Any]) -> None:
      """Atomic write: temp file in the same directory + ``os.replace``."""
  ```

### Module 7: identify
- **Path**: `examples/planogram/plancheck/identify.py`
- **Responsibility**: pass 1 — strips, Set-of-Marks, prompt, response filtering, catalog resolution.
- **Depends on**: M1, M2, M4, M6
- **Interface Skeleton**:
  ```python
  # examples/planogram/plancheck/identify.py  (new)
  IDENTIFY_PROMPT_VERSION: str
  def render_strip(image: np.ndarray, slots: list[Slot], *, marks: bool = True) -> tuple[bytes, Box]:
      """PNG of one row at native resolution with 2-px numbered outlines; returns (png, strip box).
      The mark number is the slot ``index``; labels are drawn over the TAG area, never the product."""
  def build_identify_prompt(slots: list[Slot], strip: Box) -> str:
      """Instructions + JSON list ``[{"slot_id","mark","box_2d"}]``; forbids reporting anything
      outside the listed areas; does NOT mention the planogram or expected products."""
  async def identify_rows(image: np.ndarray, slots: list[Slot], backend: VisionBackend,
                          catalog: Catalog, semaphore: asyncio.Semaphore, *, marks: bool = True
                          ) -> tuple[list[SlotObservation], list[str]]:
      """One call per row on cloud backends. On local backends (LFM2.5-VL-1.6B) EVERY row is split
      into sub-strips of ≤ 8 slots, one call each; cloud rows are split the same way only above
      20 slots. Unknown slot ids dropped + reported; missing ids → ``uncertain``/``unusable``.
      An ``empty`` with visibility != full is downgraded to ``uncertain``. A failed row → all its
      slots ``uncertain`` + one error string. Returns (observations, errors)."""
  ```

### Module 8: registration
- **Path**: `examples/planogram/plancheck/registration.py`
- **Responsibility**: deterministic row→shelf and slot→facing alignment for one image.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # examples/planogram/plancheck/registration.py  (new — pure functions, no I/O, no LLM)
  def pair_score(obs: SlotObservation, facing: PlanogramFacing, catalog: Catalog) -> float:
      """The §2 score table."""
  def align_row(row_obs: list[SlotObservation], facings: list[PlanogramFacing], catalog: Catalog,
                pitch: float) -> tuple[float, dict[str, str], int]:
      """Semi-global alignment with the §2 gap costs and pitch check.
      Returns (score, slot_id→facing_id, direct-anchor count)."""
  def register_image(image_id: str, observations: list[SlotObservation], planogram: PlanogramRef,
                     catalog: Catalog, pitches: dict[int, float]) -> ImageRegistration:
      """Enumerate order-preserving injective row→shelf maps (rows beyond ``shelf_count`` are left
      unregistered), apply the vertical prior, pick the best, record runner-up + margin, grade rows."""
  def apply_registration(observations: list[SlotObservation], registration: ImageRegistration) -> None:
      """Set ``facing_id`` and ``registration_grade`` in place."""
  ```

### Module 9: verify
- **Path**: `examples/planogram/plancheck/verify.py`
- **Responsibility**: pass 2 — closed-set verification with distractors.
- **Depends on**: M1, M6, M7 (`render_strip`)
- **Interface Skeleton**:
  ```python
  # examples/planogram/plancheck/verify.py  (new)
  VERIFY_PROMPT_VERSION: str
  def pick_distractors(facing: PlanogramFacing, planogram: PlanogramRef, catalog: Catalog, n: int = 3) -> list[str]:
      """Same brand; prefer same family/other variant, then shelf neighbours within ±2 slots.
      Never returns the expected SKU; may return fewer than ``n``."""
  def option_order(slot_id: str, skus: list[str]) -> list[str]:
      """Deterministic shuffle seeded by sha256(slot_id) — the expected SKU is not always first."""
  async def verify_rows(image: np.ndarray, observations: list[SlotObservation], planogram: PlanogramRef,
                        catalog: Catalog, backend: VisionBackend, semaphore: asyncio.Semaphore) -> list[str]:
      """Targets: registered, occupied, resolution in {unresolved, ambiguous}, identity_required,
      expected SKU present in the catalog. Options are shown by catalog ``display_name``.
      expected + evidence → ``verified_by_expectation``; expected without evidence → ``inferred``;
      a distractor → resolved_sku = that SKU, ``verified_by_expectation``; other/cannot_tell →
      unchanged. Mutates observations; returns error strings."""
  ```

### Module 10: scoring
- **Path**: `examples/planogram/plancheck/scoring.py`
- **Responsibility**: multi-photo merge, position statuses, credits, shelf/brand/price metrics.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # examples/planogram/plancheck/scoring.py  (new — pure functions; merge rules adapted from
  #   examples/planogram/inkcheck/inkcheck/compare.py:24-47 — verified)
  def merge_positions(planogram: PlanogramRef, observations: list[SlotObservation], catalog: Catalog,
                      weights: ScoringWeights, prices: dict[str, Decimal] | None) -> list[PositionResult]:
      """One result per expected facing using the §2 status decision list and credits."""
  def shelf_scores(positions: list[PositionResult]) -> list[ShelfScore]: ...
  def brand_shares(planogram: PlanogramRef, positions: list[PositionResult],
                   observations: list[SlotObservation]) -> list[BrandShare]: ...
  def summarize(positions: list[PositionResult], observations: list[SlotObservation], planogram: PlanogramRef,
                prices: dict[str, Decimal] | None) -> ComplianceSummary: ...
  ```

### Module 11: report
- **Path**: `examples/planogram/plancheck/report.py`
- **Responsibility**: write `compliance.json`, annotated images, crops, run snapshot.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # examples/planogram/plancheck/report.py  (new; cv2 drawing only — no matplotlib)
  STATUS_COLORS: dict[str, tuple[int, int, int]]   # BGR per PositionStatus + "unregistered"
  def annotate(image: np.ndarray, observations: list[SlotObservation], positions: list[PositionResult]) -> np.ndarray: ...
  def write_report(report: ComplianceReport, images: dict[str, np.ndarray], settings: Settings,
                   prompt_versions: dict[str, str]) -> Path:
      """Creates ``settings.output`` (must not exist → ``FileExistsError``); returns compliance.json path."""
  ```

### Module 12: pipeline-cli
- **Path**: `examples/planogram/plancheck/pipeline.py`, `examples/planogram/planogram_check.py`, `examples/planogram/README.md`, `examples/planogram/catalog.example.json`
- **Responsibility**: orchestration, concurrency, argument parsing, logging setup, exit codes, usage doc.
- **Depends on**: M1–M11
- **Interface Skeleton**:
  ```python
  # examples/planogram/plancheck/pipeline.py  (new)
  async def run_check(settings: Settings) -> ComplianceReport:
      """Stages 1→8. Images are decoded with cv2 in ``asyncio.to_thread``; per image:
      detect → grid → (prices ‖ identify) → register → verify; then merge/score/report.
      A photo with no tag rows is reported unregistered and the run continues."""
  # examples/planogram/planogram_check.py  (new)
  def build_parser() -> argparse.ArgumentParser: ...
  def main(argv: Sequence[str] | None = None) -> int:
      """0 ok · 2 completed with recorded errors · 1 invalid input. ``--emit-catalog-template``
      short-circuits. Uses ``logging`` (no print)."""
  ```

---

## 4. Test Specification

All tests live in `examples/planogram/tests/` (run explicitly — root `testpaths`
is `["tests"]`). File names are `test_plancheck_<module>.py` to avoid basename
clashes with `inkcheck/tests/`. **No network, no real photos**: images are
synthesised with numpy/cv2; LLM clients are duck-typed fakes.

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_gitignore_tracks_code_not_photos` | M0 | the seven `git check-ignore` assertions of Module 0 |
| `test_models_forbid_extra` / `test_report_roundtrip_json` | M1 | strictness; `ComplianceReport` dumps/loads with Decimals |
| `test_load_planogram_expands_facings` | M2 | 3-facing CLOSEOUT → 3 occupancy-only facings, ids `pNNN_fK` |
| `test_load_planogram_orders_by_slot_not_position` | M2 | shelf with positions 1,2,8,6,7 and slots 1..5 → facings in slot order |
| `test_load_planogram_rejects_noncontiguous_slots` | M2 | slots 1,2,4 → `ValueError` |
| `test_load_catalog_reports_missing_skus` | M2 | missing identity-required SKUs returned, not raised |
| `test_resolve_identifier_signature_alias` | M2 | each of the three rules yields `direct` |
| `test_resolve_never_merges_xl` | M2 | `xl=None` with XL and standard items → `ambiguous`, both candidates |
| `test_emit_catalog_template_refuses_overwrite` | M2 | `FileExistsError` |
| `test_detect_synthetic_rows` | M3 | 3 rows × 6 white rectangles on dark ground → 3 rows, 18 tags, ordered |
| `test_detect_roi_filters` | M3 | tags outside ROI dropped |
| `test_detect_matches_reference_script` | M3 | same candidates/rows as the original script on the synthetic image |
| `test_anchored_slot_geometry` | M4 | clamps and top/bottom rules |
| `test_gap_fill_integer_pitch` / `test_gap_fill_rejects_ambiguous` | M4 | 2×pitch gap → 1 slot; 1.5×pitch → none |
| `test_untagged_bottom_row` | M4 | synthesized only when ≥ 0.6 pitch remains |
| `test_to_strip_norm` | M4 | 0–1000 `[ymin,xmin,ymax,xmax]` |
| `test_parse_price_cases` | M5 | `$45.99`, `45 99`, `'59"` → partial, `45%` → partial, `口` → unreadable |
| `test_read_prices_without_rapidocr` | M5 | `TagOcr.available = False` → all tags routed to the LLM, no exception |
| `test_read_prices_llm_only_for_unread` | M5 | fake backend called once per row with only unread cells |
| `test_cache_key_stable_and_sensitive` | M6 | same inputs same key; image / prompt (slot JSON, options) / schema / base_url / max_tokens change → new key |
| `test_cache_store_atomic` | M6 | no partial file is left when serialisation raises |
| `test_lane_dispatch` | M6 | two fake clients hit the two lanes (images split into `image` + `reference_images` on the generic lane) |
| `test_no_vision_method_is_clear_error` | M6 | a client with neither method → `VisionError` naming `localllm-ask-to-image`; CLI exit 1 |
| `test_vision_module_never_touches_sdk_handle` | M6 | source of `plancheck/vision.py` contains no `chat.completions`, `.client.` SDK access, `openai`, `google.genai` or `anthropic` import |
| `test_repair_retry_then_error_not_cached` | M6 | invalid JSON twice → `VisionError`, no cache file |
| `test_identify_substrips_on_local` | M7 | `backend.is_local` + 12-slot row → 2 calls of ≤ 8 slots; cloud → 1 call |
| `test_identify_marks_flag` | M7 | `marks=False` renders a strip with no outlines and yields a different cache key |
| `test_identify_drops_unknown_ids` | M7 | foreign slot id dropped + error recorded |
| `test_identify_downgrades_partial_empty` | M7 | empty+partial → uncertain |
| `test_prompt_has_no_expectations` | M7 | prompt contains no planogram SKU/display name |
| `test_align_row_partial_view` | M8 | 6 observed slots align inside a 17-facing shelf with free end gaps |
| `test_register_rows_monotone` | M8 | rows never map to decreasing shelves |
| `test_register_disambiguates_by_family` | M8 | identical brand sequences resolved by family anchors |
| `test_register_grade_low_without_anchors` | M8 | zero anchors → `low` |
| `test_registration_injective_per_image` | M8 | no two slots of one photo map to the same facing |
| `test_distractors_exclude_expected` / `test_option_order_deterministic` | M9 | policy + determinism |
| `test_verify_without_evidence_is_inferred` | M9 | downgrade rule |
| `test_status_decision_table` | M10 | one case per `PositionStatus` |
| `test_merge_conflict_and_agreeing_views` | M10 | conflicting identity / occupancy → `conflict`; agreeing views counted once; every contributing `slot_id` retained |
| `test_merge_price_conflict_uses_amounts` | M10 | `$45.99` vs `45.99` agree; `45.99` vs `46.99` → price `conflict`, both raws kept |
| `test_not_assessed_vs_not_visible_vs_empty` | M10 | failed row → `not_assessed`; unregistered facing → `not_visible`; neither is `empty` nor in denominators |
| `test_direct_reference_metrics` | M10 | scores restricted to `reference_read_method == "direct"` facings |
| `test_strict_vs_lenient_credits` | M10 | `verified_by_expectation` counts only in lenient; `low` rows 0 strict |
| `test_coverage_excludes_not_visible` | M10 | metric denominators |
| `test_price_compliance_optional` | M10 | `None` without `--prices`; Decimal equality with it |
| `test_write_report_refuses_existing_dir` | M11 | `FileExistsError` |
| `test_cli_requires_catalog` / `test_cli_exit_codes` | M12 | exit 1 without `--catalog`; 2 when errors recorded |
| `test_verify_pass_auto_default` | M12 | unset → on for a cloud fake, off for a local fake; explicit flags win |

### Integration Tests
| Test | Description |
|---|---|
| `test_run_check_synthetic_end_to_end` | synthetic 3-shelf fixture image + fake backend with canned `RowReading`s → registered rows, expected statuses, exit 0, all artefacts written |
| `test_run_check_two_overlapping_photos` | two synthetic views of the same shelves → facings merged once, no double counting |
| `test_run_check_backend_failure_row` | fake backend raises for one row → slots uncertain, run completes, exit 2 |

Manual (not automated, primary checkout only, needs photos + a catalog + API key):
`python examples/planogram/planogram_check.py --catalog <file> --output examples/planogram/results/feat565-run1`.

### Test Data / Fixtures
```python
# examples/planogram/tests/conftest.py
# sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  → ``import plancheck``
@pytest.fixture
def shelf_image() -> np.ndarray: ...        # dark canvas, N rows of white tag rectangles, coloured product blocks
@pytest.fixture
def mini_planogram() -> PlanogramRef: ...   # 3 shelves × 6 facings, 2 brands, one CLOSEOUT ×2
@pytest.fixture
def mini_catalog() -> Catalog: ...          # includes an XL/standard pair and a colour pair
class FakeBackend:                           # .ask(prompt, images, schema, *, stage, prompt_version) → canned model
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `pytest examples/planogram/tests -v` passes (in a worktree: prefixed with
      `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-client-google/src:packages/ai-parrot-client-local/src`).
- [ ] `ruff check examples/planogram/planogram_check.py examples/planogram/plancheck examples/planogram/tests` is clean (TID251: no `requests`/`httpx`).
- [ ] No `print(` in `plancheck/` or `planogram_check.py`; no `matplotlib`/`seaborn` import.
- [ ] Module 0's seven `git check-ignore` assertions hold; `git ls-files examples/planogram` lists only code, tests, README, `catalog.example.json` and the detector script — **no** `planogram_page1.json`, image, video, PDF, xlsx, zip or result file. `catalog.example.json`, README and test fixtures contain only synthetic SKUs.
- [ ] `planogram_check.py` / `plancheck/` do **not** import `inkcheck`, do not import a provider SDK (`google.genai`, `openai`, `anthropic`) and never access a client's SDK handle (`client.client`, `chat.completions`); every LLM call is a parrot client *method* reached through `VisionBackend` → `LLMFactory`.
- [ ] `packages/ai-parrot/src/parrot/clients/base.py` is unchanged (`git diff origin/dev -- packages/` is empty).
- [ ] Running without `--catalog` exits 1 with a message naming `--emit-catalog-template`; the template lists every identity-required planogram SKU exactly once.
- [ ] A run needs no interactive step and no positional hints; `--output` that already exists exits 1 and writes nothing.
- [ ] `--llm google:gemini-3.8-flash` reaches the Google lane and `--llm openai:<model>` / `--llm llamacpp:<alias> --base-url http://127.0.0.1:8089/v1` reach the generic `ask_to_image` lane (`test_lane_dispatch`, with fakes). A client lacking both methods exits 1 naming the prerequisite feature — this is today's behaviour for `llamacpp:` until `localllm-ask-to-image` is merged; **no FEAT-565 code changes are needed when it lands**.
- [ ] Pass-1 prompt contains no planogram expectation (`test_prompt_has_no_expectations`); responses for unknown slot ids are dropped and logged.
- [ ] The LLM never sets `facing_id`: registration is produced only by `registration.py`, and it is deterministic (same observations → byte-identical `ImageRegistration`).
- [ ] Synthesized slots carry `origin` `gap_filled` / `untagged_row`; `untagged_row` slots have price `not_assessed`.
- [ ] Price: OCR first; only non-`read` tags reach the LLM, one call per row; digits are never invented (`partial` keeps `amount = null`).
- [ ] `compliance.json` validates as `ComplianceReport` and contains strict % **and** lenient % overall and per shelf, coverage, occupancy %, per-brand expected/observed/linear share, empty facings, and — only with `--prices` — a price-compliance block. Price never changes a position status.
- [ ] `verified_by_expectation` and `inferred` contribute 0 to strict; every such position is identifiable by its `resolution` field.
- [ ] Two overlapping photos of the same facings count each facing once; disagreeing reliable views yield `conflict`.
- [ ] Pass 2 defaults to on for cloud and off for local backends; `--no-verify-pass` runs without any pass-2 call; `--no-marks` sends unmarked strips (both exist so pass-2 bias and Set-of-Marks can be ablated on cached images).
- [ ] Planogram facings are ordered by `slot`; a non-contiguous shelf is rejected at load time.
- [ ] Unseen (`not_visible`) and seen-but-unknown (`not_assessed`) facings are distinct statuses, never `empty`, and excluded from occupancy/compliance denominators.
- [ ] The report exposes reference confidence separately: `strict_pct_direct_reference`, `lenient_pct_direct_reference`, `run.reference_provisional`.
- [ ] With `rapidocr` absent the run still completes (LLM-only price reading, one warning).
- [ ] A second run with the same inputs and `--cache-dir` performs zero LLM calls.
- [ ] A row-level provider failure ends with exit code 2 and a complete report; failed calls are absent from the cache.
- [ ] `examples/planogram/README.md` documents install, catalog format, CLI, outputs, scoring semantics, the local-server recipe (incl. the `localllm-ask-to-image` prerequisite) and has a "Set-of-Marks A/B" section to be filled from the first real run.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified 2026-09-17 on `dev` @ `a9135fd78`.

### Verified Imports
```python
from parrot.clients.factory import LLMFactory                 # verified: packages/ai-parrot/src/parrot/clients/factory.py:257 (create)
from parrot.clients.google import GoogleGenAIClient           # verified by execution; same object as parrot.clients.google.client.GoogleGenAIClient
from parrot.clients.google.models import GoogleModel          # verified: packages/ai-parrot-client-google/src/parrot/clients/google/models.py:11 ; GEMINI_3_8_FLASH = "gemini-3.8-flash" :19
from parrot.clients.local.client import LocalLLMClient        # verified: packages/ai-parrot-client-local/src/parrot/clients/local/client.py:27
from parrot.models.responses import AIMessage                 # verified: packages/ai-parrot/src/parrot/models/responses.py:75
from parrot.models.outputs import StructuredOutputConfig      # verified: packages/ai-parrot/src/parrot/models/outputs.py:59
from rapidocr import RapidOCR                                 # verified by execution (rapidocr 3.9.2); engine(img).txts
import cv2, numpy, rapidfuzz                                  # installed: opencv 4.10.0.84, numpy 2.4.6, rapidfuzz 3.11.0
```
`plancheck/vision.py` must import parrot **lazily inside** `VisionBackend.__init__`
(importing `parrot` runs navconfig and `chdir`s to the repo root) so the pure
modules and their tests never import it.

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]:  # :174
    @staticmethod
    def create(llm: str, model_args: Optional[Dict[str, Any]] = None,
               tool_manager: Optional[Any] = None, **kwargs) -> AbstractClient:  # :257
    # model_args keys honoured: temperature, top_k, top_p, max_tokens (:313-322); **kwargs merged last (:334)
    # providers include: google, openai, anthropic, local, localllm, llamacpp, ollama, vllm, groq, …

# packages/ai-parrot/src/parrot/clients/base.py   (READ-ONLY — do not modify)
class AbstractClient:
    async def __aenter__(self):   # :1155  creates aiohttp session if use_session, awaits _ensure_client()
    async def __aexit__(self, exc_type, exc_val, exc_tb):  # :1167
    async def close(self) -> None:  # :1274
    async def ask(self, prompt: str, model: str, max_tokens: Optional[int] = None, temperature: float = 0.7,
                  files: Optional[List[Union[str, Path]]] = None, …,
                  structured_output: Union[type, StructuredOutputConfig, None] = None, …) -> MessageResponse:  # :1796

# packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py  (mixin of GoogleGenAIClient)
async def image_understanding(self, prompt: str,
    images: Union[str, Path, bytes, Image.Image, List[Union[str, Path, bytes, Image.Image]]],
    model: Union[str, GoogleModel] = GoogleModel.GEMINI_3_FLASH_PREVIEW,
    prompt_instruction: Optional[str] = None, user_id: Optional[str] = None, session_id: Optional[str] = None,
    stateless: bool = True, timeout: Optional[int] = 600, temperature: Optional[float] = None,
    detect_objects: bool = False, response_schema: Optional[Any] = None,
    structured_output: Union[type, StructuredOutputConfig, None] = None) -> AIMessage:  # :438
    # NOTE the default model is NOT the client's model → always pass model= explicitly.
    # structured_output applied at :512-514; parsed result passed to AIMessageFactory.from_gemini(structured_output=…) :605-612
    # path inputs > 5 MB are uploaded through the File API (:470-486) → pass bytes/PIL for strips.

# packages/ai-parrot-client-google/src/parrot/clients/google/client.py
class GoogleGenAIClient:  # :101 ; provider_keys = ("google",) :120
    async def ask_to_image(self, prompt: str, image: Union[Path, bytes], reference_images=None,
                           model: Union[str, GoogleModel] = None, max_tokens=None, temperature=None,
                           structured_output: Union[type, StructuredOutputConfig] = None,
                           count_objects: bool = False, history=None, no_memory: bool = False) -> AIMessage:  # :4999

# packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py
class OpenAIClient(OpenAIBaseClient):  # :87
    async def ask_to_image(self, prompt: str, image: Union[Path, bytes, Image.Image], reference_images=None,
                           model: str = OpenAIModel.GPT5_MINI.value, max_tokens: int = None, temperature: float = None,
                           structured_output: Optional[type] = None, history=None, no_memory: bool = False,
                           low_quality: bool = False) -> AIMessage:  # :1468
# packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py
#   AnthropicClient.ask_to_image(prompt, image, reference_images=None, model=…, …) -> AIMessage  # :1307

# packages/ai-parrot/src/parrot/clients/openai_base.py
# REFERENCE ONLY (context for the prerequisite feature `localllm-ask-to-image`) — FEAT-565 code must NOT call
# `_encode_image_for_openai`, `get_client()` or `self.client.chat.completions` (§8 Q7).
class OpenAIBaseClient(AbstractClient):  # :73
    def _encode_image_for_openai(self, image: Path | bytes | Image.Image, low_quality: bool = False) -> dict[str, Any]:  # :1137
        # → {"type": "image_url", "image_url": {"url": "data:<mime>;base64,…", "detail": "low"|"auto"}}; bytes are tagged image/jpeg (:1164-1166)

# packages/ai-parrot-client-local/src/parrot/clients/local/client.py
class LocalLLMClient(OpenAIBaseClient):  # :27 ; provider_keys = ("local", "localllm", "ollama", "llamacpp")
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None, **kwargs):  # :79
        # env fallbacks: LOCAL_LLM_API_KEY, LOCAL_LLM_BASE_URL (default http://localhost:8000/v1), LOCAL_LLM_MODEL
    async def get_client(self) -> "AsyncOpenAI":  # :91  (timeout = LOCAL_LLM_TIMEOUT or 120)
    async def invoke(self, prompt: str, *, output_type=None, structured_output=None, model=None, …) -> InvokeResult:  # :186 — TEXT ONLY, no images
    # self.client.chat.completions.create(**kwargs) :268 ; json_schema response_format :259-261 ; schema-in-prompt fallback :290-303

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):  # :75
    output: Any; response: Optional[str]; structured_output: Optional[Any]  # :148 ; is_structured: bool  # :151

# examples/planogram/white_label_detector/detect_price_labels.py
def candidates(image, min_width, max_width):  # :15-52
def group_rows(items, image_width, min_row_labels=4, max_slope=.12):  # :55-107 → (rows, unassigned_indexes)
#   ROI filter :123-126 ; crop padding px=12 % width, py=18 % height :146-147 ; CLI defaults work-width 2048, .025/.09, 4
# examples/planogram/inkcheck/inkcheck/prepare.py  slot geometry :37-60
# examples/planogram/inkcheck/inkcheck/catalog.py  normalize_planogram :5-20 (facing id f"p{position:03d}_f{index}", CLOSEOUT rule :16)
# examples/planogram/inkcheck/inkcheck/compare.py  merge rules :24-47 ; metric definitions :64-69
# examples/planogram/inkcheck/inkcheck/vision.py   cache-key recipe :25-40
```

Planogram JSON (`examples/planogram/planogram_page1.json`): top level
`{"planogram": {product_count, physical_facing_count, source, shelves, segments, planogram, fixture, option}, "shelves": [6]}`;
shelf → `shelf`, `shelf_number`, `product_count`, `facing_count`, `products: {"pos <shelf>:<slot>": {...}}`;
product → `position`, `segment` (`left`|`right`), `segment_number`, `slot`, `segment_slot`, `product`, `brand`, `shelf`,
`facings`, `confidence`, `read_method`, `notes`. 102 positions / 104 facings; shelf sizes 17/18/18/18/16/15;
brands HP, Epson, Canon, Brother, Paris Corp, Paris Business, one `None` (`CLOSEOUT`, `facings: 3`, shelf 5); no duplicate SKUs.

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `VisionBackend.__init__` | `LLMFactory.create()` | call with `model_args` + `base_url`/`api_key` kwargs | `clients/factory.py:257,334` |
| `VisionBackend.__aenter__` | `AbstractClient.__aenter__` | `async with client` | `clients/base.py:1155` |
| `VisionBackend.ask` lane 1 | `image_understanding()` | `images=[PIL…]`, `model=<parsed model>`, `structured_output=schema`, `temperature=0` | `google/analysis.py:438` |
| `VisionBackend.ask` lane 2 | `ask_to_image()` | `image=first`, `reference_images=rest`, `structured_output=schema` | `openai/client.py:1468`, `anthropic/client.py:1307` |
| result extraction | `AIMessage.structured_output` / `.output` | instance of schema, else `schema.model_validate(...)` | `models/responses.py:148` |
| `detection.py` | `candidates()` / `group_rows()` | adapted copy | `detect_price_labels.py:15,55` |

### Does NOT Exist (Anti-Hallucination)
- ~~`AbstractClient.ask_to_image`~~ / ~~`AbstractClient.image_understanding`~~ — no vision method on the base client.
- ~~`LocalLLMClient.ask_to_image`~~ / ~~`OpenAIBaseClient.ask_to_image`~~ — not defined **today**; `LocalLLMClient.invoke()` is text-only. `LocalLLMClient.ask_to_image` is what the prerequisite feature `localllm-ask-to-image` will add (expected to mirror `OpenAIClient.ask_to_image`, `openai/client.py:1468`: `prompt, image, reference_images=None, model=None, max_tokens=None, temperature=None, structured_output=None, …) -> AIMessage`). FEAT-565 code must only *duck-type* it, never assume it exists.
- ~~`client.ask(prompt, files=[image])` as a vision path~~ — `AbstractClient._encode_file` emits a `"type": "document"` block (`clients/base.py:1392-1401`) and `OpenAIBaseClient.ask` uploads `files` through `files.create` (`openai_base.py:807,1128-1135`); neither sends an inline image.
- ~~`from parrot.models.google import GoogleModel`~~ — ImportError; use `parrot.clients.google.models`.
- ~~`tesseract` binary~~ — not installed; do not use `pytesseract`.
- ~~prices / product names / widths in `planogram_page1.json`~~ — absent.
- ~~any registration/alignment code in inkcheck~~ — `facing_id` is only set by its manual `review.html`.
- ~~`import detect_price_labels`~~ / ~~`import inkcheck`~~ — not packages on the path; adapt, never import.
- ~~LLM catalog enrichment~~ — explicitly out of scope (user supplies `--catalog`).
- ~~`asyncio_mode = "auto"`~~ — not configured; async tests need `@pytest.mark.asyncio`.
- ~~`parrot_pipelines.planogram` reuse~~ — different pure-LLM pipeline; not used.
- ~~`examples/planogram/**` currently in git~~ — the directory is ignored (`.gitignore:5`) until Module 0 lands.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first: LLM calls awaited under one `asyncio.Semaphore`; cv2 decode/encode and OCR via `asyncio.to_thread` (both release the GIL) — never inline in a coroutine.
- Pydantic v2 for every structure crossing a module boundary; Google-style docstrings + strict type hints; `logging.getLogger(__name__)`, never `print`; `black` line length 120.
- Pure modules (`models`, `reference`, `detection`, `grid`, `registration`, `scoring`) import neither `parrot` nor any network library.
- LLM output is parsed with Pydantic only — never `eval`; invalid → one repair retry (validation error appended to the prompt) → `VisionError`.
- Coordinates are always ORIGINAL-image pixels in models; normalisation to strip space happens only when building prompts.
- **`.gitignore` block (Module 0)** — delete line 5 (`examples/planogram/`) and append, after the last `examples/` rule, so these negations outrank `examples/**/*.py`:
  ```gitignore
  # FEAT-565: planogram compliance example — track code + small inputs only.
  examples/planogram/*
  !examples/planogram/planogram_check.py
  !examples/planogram/README.md
  !examples/planogram/catalog.example.json
  !examples/planogram/plancheck/
  !examples/planogram/plancheck/**/*.py
  !examples/planogram/tests/
  !examples/planogram/tests/**/*.py
  !examples/planogram/white_label_detector/
  examples/planogram/white_label_detector/*
  !examples/planogram/white_label_detector/detect_price_labels.py
  ```
  `planogram_page1.json` is intentionally absent from the block (§8 Q1).

### Known Risks / Gotchas
- **Public repository.** `phenobarbital/ai-parrot` is PUBLIC. `planogram_page1.json` (extraction of a retailer planogram PDF) and the store photos are **never tracked**; nothing committed by this feature (fixtures, README, `catalog.example.json`, test data) may copy real part numbers or layout from it — synthetic data only.
- **Worktree blindness.** A worktree never contains the planogram file or the photos (and, until Module 0 lands, not even the detector script) — real end-to-end runs happen only in the primary checkout; everything automated runs on synthetic fixtures.
- **Worktree imports.** The shared venv is editable-installed against the primary checkout; tests touching `vision.py` need the `PYTHONPATH` prefix from §5. Never `uv sync` in the worktree.
- **`import parrot` side effect**: navconfig `chdir`s to the repo root — resolve all CLI paths to absolute **before** the first parrot import.
- **`image_understanding` default model** is `GEMINI_3_FLASH_PREVIEW`, not the client's model — always pass `model=`.
- **Few anchors on a row** → registration relies on vertical order, pitch and the segment landmark; row graded `low`, positions capped at lenient credit.
- **Ambiguous registration** → best kept, runner-up + margin recorded, graded `low`.
- **Neighbouring-fixture tags** (left edge of `image_01`) → `--roi`, or they end `unregistered` via observed-side end gaps; never mis-scored.
- **Missed tag mid-row** → `gap_filled` slot only when the pitch multiple is unambiguous (±25 %).
- **Bottom shelf without tags** → `untagged_row`, price `not_assessed`.
- **Multi-facing CLOSEOUT** → occupancy-only, excluded from SKU denominators.
- **Glare / partial visibility** → `empty` + non-full visibility is downgraded to `uncertain`.
- **Confirmation bias of pass 2** → contained by distractors, mandatory evidence, deterministic option order, and by excluding `verified_by_expectation` from the strict score.
- **Local model is LFM2.5-VL-1.6B** (§8 Q4): sub-strips of ≤ 8 slots are always used locally, pass 2 defaults to off, concurrency 1. llama.cpp + LFM2.5-VL needs `cache_prompt: false` with JSON-schema constraints (inkcheck README §2) — a requirement on the prerequisite feature, not solvable from script code.
- **Provider/schema failure** → slots `uncertain`, error recorded, exit 2, not cached.
- **Price conflicts** across photos → `conflict`, both raw readings kept.
- **Cloud data egress**: Gemini runs send store-photo strips to Google — documented in the README.
- **Reference is a draft**: 40/102 planogram SKUs are `read_method: inferred`; the report carries this as a standing note.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `opencv-python` | 4.10.0.84 (installed) | detection, crops, strips, overlays |
| `numpy` | 2.4.6 (installed) | geometry, alignment matrices |
| `rapidocr` + `onnxruntime` | 3.9.2 / 1.30.0 (installed) | local tag OCR |
| `rapidfuzz` | 3.11.0 (installed) | brand normalisation, alias rule |
| `pydantic` | v2 (installed) | models + LLM contracts |
| `pillow` | 11.3.0 (installed) | image hand-off to clients |
| `ai-parrot`, `ai-parrot-client-google`, `ai-parrot-client-local` | workspace | LLM access |

No new dependency is added to any `pyproject.toml`; the example documents these
in its README. Not used: `pytesseract` (binary missing), `easyocr`, `paddleocr`.

---

## Worktree Strategy

- **Isolation**: one feature worktree `feat-FEAT-565-new-planogram-compliance-algo`
  from `origin/dev`; the `sdd-coder` engine gives each task its own sub-worktree.
- **Prerequisite outside the worktree**: **M0** is committed in the primary
  checkout directly on `dev` and pushed *before* the worktree is created (the
  adopted detector script is untracked and exists only there). Its task is `parallel: false`.
- **Module dependency graph** (edge = "imports a symbol of"):
  - M1 → M0 · every other module → M1 (imports `plancheck.models`).
  - M5 → M6 (`VisionBackend` for the price fallback).
  - M7 → M2 (`resolve_identity`), M4 (`strip_box`, `to_strip_norm`), M6.
  - M9 → M6, M7 (`render_strip`).
  - M12 → M2…M11.
  - **No edge** between M2, M3, M4, M6, M8, M10, M11 → they run concurrently
    after M1. Second wave: M5, M7. Third: M9. Last: M12.
- **Shared files**: none between modules — each owns one source file and one
  `test_plancheck_<module>.py`. `tests/conftest.py` and `plancheck/__init__.py`
  are created by M1 and only read by the others (fixtures needed by later
  modules are all declared in M1's conftest per §4).
- **Exclusive resources**: `.gitignore` (M0 only). No lockfile, migration or
  extension rebuild. No `uv add`.
- **Cross-feature dependencies**: **`localllm-ask-to-image`** (placeholder slug — no brainstorm/spec yet; owner runs `/sdd-brainstorm`): adds `ask_to_image()` to `LocalLLMClient` only (not `OpenAIBaseClient`, not `AbstractClient`). It is a **soft** dependency: no FEAT-565 task waits for it (M6 is duck-typed and tested with fakes) and FEAT-565 can merge first; only *real* runs with `--llm llamacpp:…` need it. Requirements FEAT-565 places on it: multi-image input (`image` + `reference_images`), `structured_output` with a Pydantic type, `temperature=0`, and a way to send llama.cpp's `cache_prompt: false` (LFM2.5-VL + JSON-schema constraints crash with prompt reuse — inkcheck README §2). No overlap with FEAT-564 or any other in-flight spec.

---

## 8. Open Questions

- [x] **Q1 — Public exposure of `planogram_page1.json`** — *Resolved 2026-09-17 (Jesus Lara)*: do NOT track it. The repo is PUBLIC; the file stays local like the photos; M0 drops its re-include line; tests, README and `catalog.example.json` use synthetic data only. (Supersedes the "track `planogram_page1.json`" part of the brainstorm's git-tracking answer.)
- [x] Q2 — Partial-credit weights — *Resolved 2026-09-17 (Jesus Lara)*: misplaced 0.5 / variant_unresolved 0.5 / inferred_present 0.5 / verified_by_expectation 1.0, overridable through `ScoringWeights`.
- [x] Q3 — Ground truth for the two store-560 photos — *Resolved 2026-09-17 (Jesus Lara)*: out of scope for FEAT-565. No accuracy claim is made; the ablation switches (`--no-verify-pass`, `--no-marks`) ship; a labelled evaluation set is a follow-up after the first real run. (Design research S11.)
- [x] Q4 — Local vision model on `:8089` — *Resolved 2026-09-17 (Jesus Lara)*: LFM2.5-VL-1.6B. Sub-strips of ≤ 8 slots always on local backends; pass 2 off by default locally; `cache_prompt: false` is a requirement on the prerequisite feature.
- [x] Q5 — Common vision method in core — *Resolved 2026-09-17 (Jesus Lara)*: not on `AbstractClient` and not on `OpenAIBaseClient`; the prerequisite adds `ask_to_image()` to **`LocalLLMClient` only** (see Q7).
- [x] Q6 — Set-of-Marks overlays — *Resolved 2026-09-17 (Jesus Lara)*: on by default (2-px outlines, number over the tag area only); A/B with `--no-marks` at the first real run, result recorded in the README, default flipped if marks hurt.
- [x] **Q7 — Local-vision lane vs "never call a provider SDK directly"** — *Resolved 2026-09-17 (Jesus Lara)*: core `ask_to_image` first. No script-local SDK-handle lane exists in FEAT-565; `VisionBackend` has two lanes (Google `image_understanding`, generic `ask_to_image`). A separate prerequisite feature (placeholder slug `localllm-ask-to-image`, brainstormed by the owner) adds the method to `LocalLLMClient`; it is a soft dependency — until it lands `--llm llamacpp:…` exits 1 with a message naming it. (Design research S1.)
- [ ] Q8 — Create the prerequisite feature `localllm-ask-to-image` (`/sdd-brainstorm`), carrying the four requirements listed under Worktree Strategy → Cross-feature dependencies. Does not block any FEAT-565 task. — *Owner: Jesus Lara*
- [x] Flow type / base branch — *Resolved in brainstorm*: feature on `dev`.
- [x] Relationship to inkcheck / ai-parrot — *Resolved in brainstorm*: standalone script, LLM via ai-parrot clients; inkcheck is reference only.
- [x] Input unit — *Resolved in brainstorm*: N photos of one fixture, merged per planogram position.
- [x] LLM feeding strategy — *Resolved in brainstorm*: photo (row strip) + JSON of detected areas.
- [x] Vision backends — *Resolved in brainstorm*: Gemini Flash, local llama.cpp server, and any pluggable `provider:model`.
- [x] Registration — *Resolved in brainstorm*: automatic sequence alignment, inferred slots flagged; no CLI hints required.
- [x] Scoring strictness — *Resolved in brainstorm*: tiered; strict % and lenient % reported side by side, per shelf and overall.
- [x] Prices — *Resolved in brainstorm*: always reported; optional `--prices` file adds a separate price-compliance metric.
- [x] Tag OCR engine — *Resolved in brainstorm*: local OCR first, LLM fallback.
- [x] Git tracking — *Resolved in brainstorm*: track code + small inputs — force-add the new script/package, tests, `planogram_page1.json` and the detector script; store photos stay untracked and end-to-end runs take `--images-dir` from the main checkout. (**`planogram_page1.json` part superseded by Q1 — not tracked.** Implemented as a `.gitignore` re-include block rather than `git add -f`, so coder agents' plain `git add` works.)
- [x] Part-number ↔ consumer-name bridge — *Resolved in brainstorm*: the user supplies the catalog file — `--catalog` is required for identification; NO LLM enrichment module in v1.
- [x] Single file vs small package — *Resolved in brainstorm*: thin `planogram_check.py` CLI entry point + sibling helper package `examples/planogram/plancheck/` (one module per stage).

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: completed
> · Transcript: `sdd/state/FEAT-565/design_research/`
> Every row is a suggestion the reviewer made; the disposition is the spec author's
> call (CONFIRM = folded into the spec, REJECT = reason recorded, ESCALATE = §8 question).
> All 41 cited paths passed the containment + existence check; the factual claims behind
> S1 (`_encode_file` → `"document"`, `base.py:1392-1401`) and S3 (shelf 1 `position`
> non-monotone, `slot` contiguous) were reproduced before triage.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Resolve the vision-client capability gap first (architecture) | ESCALATE → resolved | Claim verified: no parrot method sends an image to a local OpenAI-compatible server. Owner decided (Q7): core `ask_to_image` first, on `LocalLLMClient` only, as a separate prerequisite feature; the script-local SDK lane was removed from this spec | §8 Q7, §3 M6, Worktree Strategy |
| S2 | Make the deliverable and tests trackable (architecture) | CONFIRM | Reached independently; narrow `.gitignore` re-include block instead of `git add -f` | §3 M0, §7 |
| S3 | Normalize a physical planogram axis before alignment (architecture) | CONFIRM | Verified: `position` is not monotone on shelf 1; order by `slot`, validate contiguity, keep `segment_slot` | §2 stage 4, §3 M1/M2, §4 |
| S4 | Versioned consumer-visible SKU identity bridge (api) | CONFIRM | Catalog already required with family/xl/colors/pack/aliases; added `provenance`; uncovered SKUs reported in `run.catalog_missing_skus`; MPNs never fuzzy-matched | §2 resolution rules, §3 M1/M2 |
| S5 | Represent unseen areas separately from unknown occupancy (architecture) | CONFIRM | Exposed a real gap: a registered-but-uncertain slot had no status. Added `not_assessed` beside `not_visible`; both out of denominators, never `empty` | §2 statuses/metrics, §3 M1, §4, §5 |
| S6 | Separate automatic registration from human-review semantics (api) | CONFIRM | No `reviewed` flag exists in the new models; grade, anchors, margin and runner-up are exposed; `run.registration_method = "auto_alignment"` added. Per-slot candidate-mapping lists not added (runner-up is recorded per image) | §3 M1 |
| S7 | Reference uncertainty as a separate scoring dimension (risk) | CONFIRM | 40/102 reference entries are inferred; added `reference_read_method`, direct-reference strict/lenient metrics and `run.reference_provisional` | §2 metrics, §3 M1, §4, §5 |
| S8 | Structured price evidence instead of raw strings (api) | CONFIRM | `PriceReading` already structured; made explicit that agreement/compliance compare normalised amounts and conflicts keep all raws. OCR confidence score not added (grammar acceptance is the gate) | §2 metrics, §4 |
| S9 | Preserve cross-photo conflicts before deduplication (architecture) | CONFIRM | Every observation stays in `slots[]`, `PositionResult.slot_ids` links them; added identity/price-conflict and per-image injectivity tests | §4 |
| S10 | Expand cache invalidation to all perception inputs (risk) | CONFIRM | Key already hashes full prompt text + rendered images (covers slot JSON, distractors, overlays); added base URL + generation params and atomic writes. OCR is not cached; alignment parameters never reach an LLM call | §2, §3 M6, §4 |
| S11 | Hand-labelled evaluation fixture before claiming accuracy (testing) | ESCALATE → resolved | Owner decided (Q3): out of scope for FEAT-565, follow-up after the first real run; spec makes no accuracy claim and ships the ablation switches | §8 Q3 |
| S12 | Gate Set-of-Marks and local OCR behind A/B tests (testing) | CONFIRM | Added `--no-marks`, marks-sensitive cache key, graceful absence of `rapidocr`. Default stays marks-on with labels drawn over the tag area only, pending the A/B (§8 Q6) | §2 CLI, §3 M5/M7, §4, §5 |

Summary: **10** confirmed · **0** rejected · **2** escalated (both since resolved by the owner in §8).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-17 | Jesus Lara | Initial draft from accepted brainstorm (Option D); design-research triage folded in (10 confirm / 2 escalate) |
| 0.2 | 2026-09-17 | Jesus Lara | Open questions Q1–Q7 resolved: planogram JSON not tracked (public repo); script-local SDK lane removed — prerequisite `localllm-ask-to-image` (LocalLLMClient only, soft dependency); weights confirmed; ground truth out of scope; local model LFM2.5-VL-1.6B (sub-strips always, pass 2 off locally); Set-of-Marks on by default |
