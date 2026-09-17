---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: New Planogram Compliance Algorithm (label-anchored, autonomous)

**Date**: 2026-09-17
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: D

---

## Problem Statement

We need an **autonomous** script — `examples/planogram/planogram_check.py` — that
takes the photos of one store fixture plus a planogram definition and returns a
structured JSON with detected products, names, prices, empty slots, occupancy by
brand, and a planogram-compliance score (overall and per shelf). No human review
step, no model training.

The intended procedure (from the request) has five steps:

1. Detect prominent, easy-to-find shapes that are later confirmed as **price tags**.
2. Use the tags as **anchors** to derive product areas and occupancy; OCR the tag
   for price (and any other readable feature).
3. **Compare** every detected product with the planogram definition; when a
   product cannot be read, **infer** it from the planogram reference.
4. Compute occupancy, empty areas and **share of occupation by brand**; brand +
   product identification is done by a vision LLM that is constrained to the
   detected areas (photo + JSON of areas) so it cannot report products outside them.
5. Compare the composed ("as-observed") planogram with the definition and **score** it.

Two assets already exist and both stop short of this goal:

- `white_label_detector/detect_price_labels.py` solves step 1 well — on
  `image_01` it finds **56 tag candidates in 5 consistent rows** plus 6
  unassigned — but by design does no OCR, no product recognition, no scoring.
- `inkcheck/` implements steps 1, 2 and 5 but **its autonomous mode produces a
  0 % result**. Verified in `results/auto-run2/report.json`: 117 regions
  processed, `unmapped_regions: 117`, `status_counts: {"unknown": 104}`,
  `occupancy_coverage: 0.0`. Two root causes:
  1. **No registration.** `Region.facing_id` is only ever set by the manual
     `review.html` editor; `compare()` ignores observations without a reviewed
     `facing_id`, so an unattended run can never score a single facing.
  2. **Per-crop identification with a 1.6 B local model is too weak**: 94 of 117
     detections graded `low`; `catalog.resolve()` deliberately refuses to use
     shelf expectations, so nothing is ever inferred (the opposite of step 3).

The gap this feature closes is therefore **automatic registration + planogram-aware
identification + inference + scoring**, on top of the tag detector that already works.

**Who is affected**: developers evaluating a label-first compliance algorithm as
an alternative to the pure-LLM `parrot_pipelines.planogram` pipeline; downstream,
field-merchandising users who get compliance from raw store-visit photos.

### Facts established during research (they shape every option)

- **Fixture/photo geometry.** Tags sit on the shelf edge *below* their products.
  `image_01` (4032×3024) shows 5 tag rows; the 6th (bottom) shelf is visible —
  Brother boxes — but **its tags are out of frame**. The planogram has 6 shelves.
- **Tag crops are small**: ~200×110 px at full resolution. The large dollar
  amount is legible ($68, $43, $47); the product-name line and the QR code are
  **not** readable. Tag OCR realistically yields **price only** — product
  identity must come from the package.
- **Local OCR probe** (RapidOCR 3.9.2, 4× bicubic upscale, all 56 crops of
  `image_01`): digits found in **40/56 crops (71 %)**, 33 s on CPU. Whole
  dollars are right, but the superscript cents are garbled (`'59"`, `45%`,
  `54"`) — the VLM in inkcheck read the same tag as `$45.99`. So local OCR is a
  good first pass for dollars; cents and the remaining ~29 % need the LLM fallback.
- **The planogram identifies products by manufacturer part number**
  (`C2P04AN#140`, `T212XL120-S`), with `brand`, `segment`, `slot`, `facings`,
  `confidence`, `read_method`, `notes`. It has **no consumer-facing name**
  ("HP 62 Black"), **no price**, **no physical width**. Packages show the
  consumer name, not the part number — an identity bridge is required.
  40 of 102 positions are `read_method: inferred` (the reference itself is a draft).
- **Brand sequences alone cannot register a photo**: shelves 1–5 all start with
  9 HP positions in the left segment. Registration needs vertical order,
  product-family evidence (60/61/62/64/67/902/910…), and the HP→Epson/Canon
  segment boundary.
- The two photos in `images/` **overlap** and neither covers the whole 8 ft gondola.

## Constraints & Requirements

- **Deliverable**: `examples/planogram/planogram_check.py`, runnable as a CLI;
  self-contained (adapts ideas from `inkcheck/` and `white_label_detector/`, does
  not import the `inkcheck` package).
- **Fully autonomous**: no review page, no manual manifest editing, no CLI hints
  required for a correct run (decision: *auto sequence alignment*).
- **Vision LLM through ai-parrot clients only** — never a provider SDK or raw
  HTTP. Must support: Gemini Flash (primary, `gemini-3.8-flash`), the local
  llama.cpp server (`:8089`, OpenAI-compatible), and any `provider:model`
  string for comparison runs.
- **LLM feeding = photo (row strip) + JSON of detected areas**; the model answers
  per known slot id only and must not report products outside the supplied areas.
- **Input unit = N photos of one fixture/visit**, merged into a single
  planogram-level result with cross-photo de-duplication by planogram position.
- **Tag OCR = local OCR first, LLM fallback** for unreadable tags / cents.
- **Prices**: always reported (raw + normalized). An **optional `--prices`
  file** (`sku → expected price`) adds a *separate* price-compliance metric;
  price never influences product identity or the planogram score.
- **Scoring is tiered and reports strict % and lenient % side by side**, per
  shelf and overall.
- Every inferred value is **flagged as inferred** with its evidence basis;
  unknown never silently becomes empty or compliant.
- Repo conventions: async-first, `aiohttp` only (no `requests`/`httpx`),
  Pydantic v2 models for all structures, Google-style docstrings + strict type
  hints, `self.logger`/`logging` instead of `print`, no matplotlib. OpenCV/OCR
  are CPU-bound and must not block the event loop.
- Determinism: everything except the LLM/OCR calls is pure Python and unit-testable
  with synthetic fixtures; LLM responses are cached on disk keyed by
  (model, prompt version, schema, image bytes) so re-runs are free and reproducible.
- **`examples/planogram/` is git-ignored** (`.gitignore:5`) and nothing under it
  is tracked — see Impact and Open Questions.

---

## Options Explored

### Option A: Port inkcheck's per-crop pipeline and bolt on registration

Keep inkcheck's shape: tag detection → one product crop per tag → one
occupancy call and one identification call **per crop** → catalog resolution →
compare. Add the missing piece (an automatic `facing_id` assignment) after
identification, and swap the raw aiohttp endpoint client for parrot clients.

✅ **Pros:**
- Smallest conceptual distance from code that already runs and has 20 tests.
- Per-crop calls are perfectly isolated and individually cacheable/retryable.
- A crop can never "see" a neighbouring product (strong area constraint).

❌ **Cons:**
- ~55–60 slots × 2 calls × N photos ≈ **230+ LLM calls per visit** — slow and
  costly on Gemini, very slow on the local server (concurrency 1).
- A crop has **no neighbour context**: the model cannot use "this is the 64-family
  bay" or relative package size, which is exactly what disambiguates XL/standard
  and look-alike black boxes.
- Contradicts the chosen feeding strategy (photo + JSON of areas).
- Inherits inkcheck's axis-aligned crop errors: a slightly-off crop boundary
  shows half of two products and the model has no way to tell.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `opencv-python` | tag detection, crops | 4.10.0.84 installed (contrib + headless 5.0 also present) |
| `numpy` | geometry | 2.4.6 installed |
| `pydantic` | schemas | v2 |
| `ai-parrot-client-google` / `-local` | LLM access | per-crop `ask_to_image` (Google) — local client has no such method, see Code Context |

🔗 **Existing Code to Reuse:**
- `examples/planogram/inkcheck/inkcheck/pipeline.py` — per-region orchestration and escalation flow
- `examples/planogram/inkcheck/inkcheck/schema.py` — `Occupancy`, `Identity`, `Observation` shapes
- `examples/planogram/inkcheck/inkcheck/vision.py` — response cache keyed by config+prompt+schema+image

---

### Option B: Row-strip open-set identification + deterministic 2-D alignment

Tags → slot grid. For each visible shelf row, cut a **full-resolution horizontal
strip** and send it once with the JSON list of slot boxes; the model returns,
per slot id, an *open-set* description (occupancy, brand, family/cartridge
number, XL, colour, pack, visible text, confidence). Python resolves each
description against a catalog, then registers the photo with a **monotone 2-D
alignment**: rows map to increasing shelf numbers, and within a row the
identified sequence is aligned against the planogram shelf sequence with an
order-preserving, gap-tolerant alignment. Unanchored slots between anchors are
inferred from the planogram. The model never sees the expected products.

✅ **Pros:**
- ~6 LLM calls per photo instead of ~115; strips keep native resolution (a
  4032-px-wide strip is not downscaled the way a full photo is).
- Neighbour context available to the model; area constraint still enforced
  (answers are keyed by supplied slot id, unknown ids are rejected).
- Identification is **unbiased** — the model does not know what is expected, so
  a wrong product is reported as what it is.
- Registration is deterministic, explainable and unit-testable.

❌ **Cons:**
- Open-set reading of small, glossy, look-alike ink boxes is the hardest
  vision task here; many slots will come back as "HP, black box, unreadable",
  leaving few anchors on some rows.
- Needs the part-number ↔ consumer-name bridge (catalog enrichment) to resolve
  anything at all.
- Inferred slots are *only* inferred — no visual confirmation — so the lenient
  score leans heavily on inference.

📊 **Effort:** Medium–High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `opencv-python`, `numpy` | detection, strips, overlays | installed |
| `rapidocr` | local tag OCR | 3.9.2 installed (onnxruntime 1.30.0); 71 % dollar-read rate in probe |
| `rapidfuzz` | tolerant text ↔ catalog matching | 3.11.0 installed |
| `pydantic` | schemas + structured output | v2 |
| parrot LLM clients | vision calls | via `LLMFactory.create("provider:model")` |

🔗 **Existing Code to Reuse:**
- `examples/planogram/white_label_detector/detect_price_labels.py` — `candidates()`, `group_rows()` (adapt verbatim)
- `examples/planogram/inkcheck/inkcheck/prepare.py` L37–60 — slot box from neighbouring tag centres + previous row line
- `examples/planogram/inkcheck/inkcheck/catalog.py` — `normalize_planogram()` facing expansion, CLOSEOUT handling

---

### Option C: One-shot Set-of-Marks — let the LLM do the mapping (unconventional)

Draw numbered outlines for every detected slot **onto the photo** (Set-of-Marks
prompting), attach the planogram shelf lists as text, and ask the model in a
single call per photo to return `mark → planogram position + status`. Python
only validates the answer and computes the score.

✅ **Pros:**
- By far the least code; 1 call per photo; trivially pluggable across providers.
- Marks drawn on the image are a more reliable grounding channel than pixel
  coordinates in JSON — models point at visible numbers better than at numbers
  in a prompt.
- The model can use global context (segment boundary, brand blocks) the way a
  human auditor does.

❌ **Cons:**
- Registration becomes **non-deterministic and unauditable**; the user already
  chose deterministic alignment over "LLM does the mapping".
- Maximum **confirmation bias**: given the expected list, models tend to report
  the expected product, inflating compliance — the worst failure mode for an
  audit tool.
- Full photo is downscaled by the provider → small text on packages is lost.
- A 102-position list + 56 marks in one response is long; one malformed answer
  loses the whole photo. Weak local models will not manage it at all.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `opencv-python` | detection + mark overlay | installed |
| parrot LLM clients | single vision call | Gemini-class model effectively required |

🔗 **Existing Code to Reuse:**
- `detect_price_labels.py` — detection and the annotated-overlay drawing (L158–161)

---

### Option D: Two-pass hybrid — open-set anchors → alignment → targeted closed-set verification

Option B's pipeline, plus a bounded second LLM pass that implements the
request's step 3 ("sometimes we need to infer … the product referenced in the
planogram") **with visual confirmation instead of blind inference**:

1. **Pass 1 (open-set, unbiased)** — row strips + slot JSON + light
   Set-of-Marks outlines; model describes what it sees per slot. Confident
   reads become **anchors**.
2. **Deterministic registration** — monotone 2-D alignment of anchors against
   the planogram; every slot gets a planogram position (or `unregistered`).
3. **Pass 2 (closed-set, only for occupied-but-unresolved slots)** — per row,
   the model gets the strip again and, for each unresolved slot, the expected
   product *plus 2–3 distractors* from the same family/neighbours, and must
   choose one of them, `other`, or `cannot_tell`, quoting visible evidence.
   Results are tagged `verified_by_expectation`, distinct from pass-1 `direct` reads.
4. Anything still unresolved but occupied and registered is `inferred`.

Strict score counts only `direct` matches; lenient score also counts
`verified_by_expectation` (full) and `inferred` (partial). Both are reported.

✅ **Pros:**
- Fulfils all five requested steps, including inference, while keeping an
  **unbiased strict number** next to the assisted lenient number — the bias of
  the closed-set pass is contained and visible, not hidden.
- Distractors + mandatory evidence make pass 2 a discrimination task rather
  than a yes/no rubber stamp.
- Still cheap: ~6 calls/photo in pass 1 + ≤6 in pass 2 (only rows with
  unresolved slots); all cached.
- Registration stays deterministic and testable; the LLM never assigns positions.
- Degrades gracefully on weak local models: pass 2 can be disabled, leaving Option B.

❌ **Cons:**
- Highest design/implementation effort; two prompt contracts and three
  evidence grades to keep straight.
- If pass 1 yields too few anchors on a row, registration of that row relies on
  vertical order and geometry alone (mitigated, not eliminated — see Edge Cases).
- Single-file script will be long (~900–1200 lines); needs disciplined sectioning.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `opencv-python` | detection, strips, overlays, annotated output | 4.10.0.84 installed |
| `numpy` | geometry, alignment DP matrices | 2.4.6 installed |
| `rapidocr` | local-first tag price OCR | 3.9.2 installed; ONNX, CPU-only OK |
| `rapidfuzz` | fuzzy description ↔ catalog matching | 3.11.0 installed |
| `pydantic` | I/O schemas, LLM structured output | v2 |
| `ai-parrot-client-google` | Gemini vision (`gemini-3.8-flash`) | `image_understanding()` accepts multiple images + `structured_output` |
| `ai-parrot-client-local` | llama.cpp `:8089` | no vision helper — needs a thin adapter (Code Context) |
| `pillow` | image hand-off to clients | 11.3.0 installed |

Not used: `pytesseract` (package installed, **`tesseract` binary is not**),
`easyocr`/`paddleocr` (installed, heavier; keep as a documented alternative
OCR engine, not a v1 dependency).

🔗 **Existing Code to Reuse:**
- `examples/planogram/white_label_detector/detect_price_labels.py` — `candidates()` L15–52, `group_rows()` L55–107, ROI filter L123–126, crop padding L146–147
- `examples/planogram/inkcheck/inkcheck/prepare.py` L37–60 — slot-box derivation
- `examples/planogram/inkcheck/inkcheck/catalog.py` — `normalize_planogram()` L5–20 (facings expansion, CLOSEOUT → `identity_required=False`)
- `examples/planogram/inkcheck/inkcheck/compare.py` — multi-view merge rules (conflict / agreeing views count once) L24–47, metric definitions L64–69
- `examples/planogram/inkcheck/inkcheck/vision.py` L25–40 — cache-key recipe
- `packages/ai-parrot/src/parrot/clients/factory.py` — `LLMFactory.create()`

---

## Recommendation

**Option D** is recommended because:

- It is the only option that delivers **every** requested step — in particular
  step 3's planogram-referenced inference — without giving up auditability. A
  (no context, 230 calls) contradicts the chosen feeding strategy; C contradicts
  the chosen deterministic registration and maximises confirmation bias; B is
  D minus the step the request explicitly asks for.
- The inkcheck post-mortem shows the two things that actually failed were
  *registration* and *identification strength*. D attacks both: deterministic
  2-D alignment for the first, row-context + a closed-set verification pass for
  the second.
- Reporting **strict and lenient side by side** (already decided) is what makes
  the closed-set pass acceptable: the biased-but-useful number never
  masquerades as the unbiased one.

What we trade off: effort (High) and script length. This is acceptable because
the expensive parts — alignment, scoring, merge, price normalisation — are pure
functions that can be built and tested incrementally, and because **D strictly
contains B**: if pass 2 proves unhelpful it is switched off by a flag, not ripped out.
One idea is borrowed from C: light Set-of-Marks outlines on the strips, because
visible marks ground slot ids more reliably than coordinates in JSON.

---

## Feature Description

### User-Facing Behavior

A CLI, run from the activated venv:

- Inputs: `--images-dir` (default `examples/planogram/images/`) or `--images f1 f2 …`;
  `--planogram` (default `planogram_page1.json`); `--output <new dir>`;
  `--llm provider:model` (default `google:gemini-3.8-flash`);
  optional `--ocr-llm` (defaults to `--llm`), `--base-url` (local servers),
  `--prices <json>`, `--catalog <json>`, `--roi L T R B`, `--no-verify-pass`,
  `--concurrency`, `--visit-id`.
- The output directory must not exist (no stale artefacts), mirroring both
  existing tools.
- Artefacts written:
  - **`compliance.json`** — the primary deliverable (below).
  - `annotated_<image>.jpg` — tags, slot boxes, planogram position and status colour per slot.
  - `slots/` and `tags/` crops; `cache/` of validated LLM/OCR responses;
    `run.snapshot.json` (settings, model ids, prompt versions, input hashes).
- Exit code `0` on a complete run, `2` when any model/OCR error was recorded
  (results still written), `1` on invalid input.

`compliance.json` content (described, not coded):

- `run`: visit id, fixture/planogram ids, models, image list with hashes, timings, error count.
- `images[]`: per photo — detected rows, tag count, synthesized rows, the
  row→shelf registration with its alignment score and the evidence that fixed it.
- `slots[]`: one per detected/synthesized slot per photo — slot id, image id,
  product box, tag box, `origin` (`tag_anchored` | `gap_filled` | `untagged_row`),
  occupancy (`occupied` | `empty` | `uncertain`) + visibility, observed brand /
  family / variant / visible text, resolved SKU + `resolution`
  (`direct` | `verified_by_expectation` | `inferred` | `unresolved`),
  price (`raw`, `amount`, `currency`, `source` = `ocr` | `llm` | `none`),
  registered planogram position (or `unregistered`), confidence grade, issues.
- `positions[]`: one per **expected planogram facing** — expected sku/brand/
  shelf/segment/slot, merged status across photos (`match`, `misplaced`,
  `variant_unresolved`, `mismatch`, `empty`, `inferred_present`,
  `occupied_unassigned`, `conflict`, `not_visible`), score tier, observed
  product, price, contributing slot ids.
- `shelves[]`: per shelf — expected/visible/decided counts, strict %, lenient %,
  occupancy %, empty positions, brand breakdown.
- `brands[]`: expected facings share vs observed facings share vs observed
  **linear share** (slot widths normalised per row), and occupancy % per brand.
- `compliance`: overall strict %, lenient %, **coverage** (share of expected
  facings actually assessed), occupancy %, products present / expected,
  unexpected products, and — only with `--prices` — price match %, mismatches list.
- `notes`: standing caveats (reference is a draft: 40 inferred SKUs; metrics
  are observations, not calibrated accuracy).

### Internal Behavior

Eight stages; stages 1, 2a, 4, 6, 7, 8 are deterministic Python.

1. **Tag detection** — multi-threshold contour candidates + row-consensus
   grouping (adapted verbatim from the white-label detector), per photo, at a
   2048-px working width with coordinates kept in original resolution.
2. **Slot grid** —
   a. *Tag-anchored slots*: horizontal bounds from neighbouring tag centres
      (capped so a missed tag does not stretch a slot); vertical bounds from the
      previous row's fitted line down to the tag top.
   b. *Gap filling*: where the spacing between two consecutive tags is ≈ k ×
      the row's median pitch, synthesize k−1 slots flagged `gap_filled`
      (the detector never invents tags; the grid layer may invent *slots*).
   c. *Untagged bottom row*: if there is product area below the last tag row,
      synthesize a row using the median row pitch and the column pitch of the
      row above, flagged `untagged_row` (no price possible).
3. **Tag price reading** — upscale each tag crop; local OCR first; parse with a
   price grammar (dollars + superscript cents). Tags with no confident
   dollars-and-cents read go to the LLM as **one contact sheet per row** with
   numbered cells. Output keeps raw text and a normalised amount; never guesses digits.
4. **Catalog build** — expand planogram positions to physical facings
   (CLOSEOUT → occupancy-only), then attach consumer-facing descriptors
   (brand, family/cartridge number, XL flag, colour set, pack size) from
   `--catalog` if given, else from a one-off, cached LLM enrichment of the part
   numbers, written back as `catalog.generated.json` for human correction.
5. **Pass 1 — open-set identification** — per visible row: full-resolution strip
   with thin numbered slot outlines + JSON of slot boxes (normalised to the
   strip). Structured response keyed by slot id; ids not in the request are
   dropped and logged. Descriptions are resolved to catalog entries by exact
   identifier first, then descriptor signature (brand + family + XL + colour +
   pack, all must agree), then marked ambiguous/unresolved. XL/standard and
   colour variants are never fuzzy-merged.
6. **Registration (monotone 2-D alignment)** —
   - *Vertical*: rows (including the synthesized one) are assigned to shelf
     numbers preserving order; candidate assignments are scored by the sum of
     their row alignment scores, with a prior for "all 6 shelves visible".
   - *Horizontal*: per (row, shelf) an order-preserving, gap-tolerant global
     alignment of the observed slot sequence against the shelf's facing
     sequence. Match score grades: exact SKU > same family/variant differs >
     same brand > unknown-occupied (neutral) > different brand (penalty);
     gaps cost less at row ends (partial view) than in the middle.
   - Slot *pitch* cross-checks the alignment: k skipped planogram positions
     must correspond to ≈ k pitches of pixel distance.
   - The HP→Epson/Canon brand transition is used as a segment-boundary landmark.
7. **Pass 2 — closed-set verification** (skippable) — only for slots that are
   registered, occupied and unresolved: expected product + distractors +
   `other` + `cannot_tell`, evidence text mandatory; choosing the expected
   product without evidence is downgraded to `inferred`.
8. **Merge, score, report** — observations from all photos are merged per
   planogram facing (agreeing views count once; occupied-vs-empty or two
   different direct SKUs → `conflict`; an unknown view never erases a positive
   one). Tiering: `match` = 1.0; `misplaced` (right SKU, same shelf, wrong
   slot), `variant_unresolved` (right brand+family) and `inferred_present` =
   partial credit in the lenient score, 0 in strict; `empty`/`mismatch` = 0;
   `not_visible`/`conflict` stay in the denominator of *coverage* and are
   excluded from the compliance denominators, so a high score with low coverage
   is visibly not full compliance.

**LLM access layer.** A small internal `VisionBackend` adapter is needed because
ai-parrot has **no vision method common to all clients**: Google exposes
`image_understanding()` / `ask_to_image()`, OpenAI and Anthropic expose
`ask_to_image()` (different signatures), and `LocalLLMClient` exposes neither.
The adapter offers one coroutine — *prompt + images + Pydantic schema → validated
model* — and dispatches on client type; for the local client it builds the
OpenAI-shaped message with the inherited `_encode_image_for_openai()` and calls
the `AsyncOpenAI` object returned by `get_client()`. Clients are created with
`LLMFactory.create()`. Schema validation failures get one repair retry, then are
recorded as errors (never as `empty`).

**Concurrency.** Row-level LLM calls run under an `asyncio.Semaphore`
(`--concurrency`, default 4 for cloud, 1 for local). OpenCV and OCR work is
pushed off the event loop (`asyncio.to_thread` / process pool for OCR batches).

### Edge Cases & Error Handling

- **Fewer than 4 tags in a row / no rows found** → row not formed by the
  detector. Photo is reported `unregistered` with its raw candidates; run continues.
- **Missed tag mid-row** → `gap_filled` slot; if pitch is ambiguous (k not
  within tolerance of an integer) no slot is invented and the alignment absorbs a gap.
- **Bottom shelf without tags** → `untagged_row`; price `none`; occupancy and
  identity still assessed.
- **Neighbouring-fixture tags** (left edge of `image_01` shows another bay) →
  excluded by optional `--roi`; without it, rows that extend beyond the fixture
  produce leading gaps in the alignment and those slots end `unregistered`, not mis-scored.
- **Too few anchors on a row** → vertical order + pitch + segment landmark
  decide; the row's registration is graded `low` and all its positions are
  capped at lenient-only credit.
- **Ambiguous registration** (two shelf assignments within a small margin) →
  keep the best, record the runner-up and margin in `images[].registration`,
  grade `low`.
- **Multi-facing positions** (CLOSEOUT ×3) → occupancy-only facings, excluded
  from SKU-specific denominators (same interpretation as inkcheck).
- **Overlapping photos disagree** → `conflict`, both observations retained.
- **Glare / partial visibility** → an `empty` claim with non-full visibility is
  downgraded to `uncertain` (inkcheck rule, kept).
- **LLM invents a slot id or returns a product for an area not supplied** →
  dropped, counted in `run.errors`.
- **Provider/HTTP/schema failure** → recorded per row, affected slots
  `uncertain`/`unresolved`; exit code 2; failed calls are not cached.
- **Price parse** → only surrounding whitespace and the cents superscript are
  normalised; missing digits are never inferred; two different readable prices
  for the same facing across photos → price `conflict`.
- **`--prices` contains SKUs not in the planogram / missing SKUs** → listed in
  the report, not an error.
- **Weak local model cannot follow the row-strip contract** → `--no-verify-pass`
  and an automatic fallback to smaller sub-strips (N slots per call) are the
  degradation path; per-crop mode is *not* in scope for v1.

---

## Capabilities

### New Capabilities
- `planogram-tag-anchored-slot-grid`: price-tag detection → slot grid with gap-filling and untagged-row synthesis.
- `planogram-tag-price-ocr`: local-first price OCR on tag crops with LLM contact-sheet fallback and price normalisation.
- `planogram-catalog-bridge`: part-number ↔ consumer-descriptor catalog (file-supplied or LLM-enriched and cached).
- `planogram-area-constrained-vision`: row-strip + slot-JSON (+ Set-of-Marks) open-set identification, answers keyed by slot id.
- `planogram-auto-registration`: deterministic monotone 2-D alignment of observed rows/slots to planogram shelves/positions.
- `planogram-expectation-verification`: closed-set second pass with distractors and mandatory evidence.
- `planogram-compliance-scoring`: multi-photo merge, tiered strict/lenient scoring, per-shelf and per-brand occupancy, optional price compliance.
- `planogram-check-cli`: the `planogram_check.py` entry point, artefacts and exit codes.
- `vision-backend-adapter`: script-local adapter giving Google / OpenAI-compatible-local / other parrot clients one vision+structured-output call.

### Modified Capabilities
<!-- None. `parrot_pipelines.planogram` (planogram-compliance-modular, planogram-new-types) is untouched. -->

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `examples/planogram/planogram_check.py` | new | The deliverable. Path is git-ignored (`.gitignore:5 examples/planogram/`) → needs `git add -f` or an ignore exception |
| `examples/planogram/tests/` | new | Unit tests for grid, price grammar, alignment, merge, scoring (synthetic fixtures, no network) |
| `examples/planogram/white_label_detector/detect_price_labels.py` | depends on (adapted copy) | Two functions copied/adapted; original left untouched |
| `examples/planogram/inkcheck/` | reference only | Not imported. Its `pyproject.toml` declares `httpx` but the code uses `aiohttp`; irrelevant to the new script |
| `examples/planogram/planogram_page1.json` | depends on (read-only input) | Untracked; invisible to worktrees |
| `parrot.clients.factory.LLMFactory` | depends on | `create("provider:model")` |
| `parrot.clients.google` (`ai-parrot-client-google`) | depends on | `image_understanding()` with `structured_output` |
| `parrot.clients.local` (`ai-parrot-client-local`) | depends on | via adapter — no vision helper on the client itself |
| `packages/ai-parrot-pipelines/.../planogram/` | none | Existing pure-LLM pipeline is not modified or reused |
| Workspace dependencies | none expected | `rapidocr`, `rapidfuzz`, `opencv`, `onnxruntime` are already in the shared venv; whether they are *declared* anywhere the example can rely on is an open question |

No breaking changes, no API/DB/CI impact. Gemini calls send store photos to a
cloud provider — acceptable for this example, but noted.

---

## Code Context

### User-Provided Code

No code was pasted. The user supplied these paths and the five-step procedure
(quoted in the Problem Statement):

```text
# Source: user-provided (invocation notes)
target script        : examples/planogram/planogram_check.py
code examples        : examples/planogram/inkcheck
images directory     : examples/planogram/images            (2 JPEGs, Best Buy store 560, 2026-09-04)
opencv tag detector  : examples/planogram/white_label_detector/detect_price_labels.py
labels artefact      : examples/planogram/results/image_01/labels.json
annotated example    : examples/planogram/results/image_01/annotated.jpg
planogram definition : examples/planogram/planogram_page1.json
suggested model      : "gemini 3.8 flash"
```

### Verified Codebase References

#### Classes & Signatures
```python
# From examples/planogram/white_label_detector/detect_price_labels.py
def candidates(image, min_width, max_width):  # L15-52
    """Return contrasting, approximately rectangular components at several thresholds."""
    # thresholds (130,150,170,190,210,230); filters: min_width*w < bw < max_width*w,
    # .014*h < bh < .06*h, 1.65 < bw/bh < 4.4, rectangularity >= .75, gray std >= 25
    # returns list[{"box": [x1,y1,x2,y2], "rectangularity": float, "contrast": float}]
def group_rows(items, image_width, min_row_labels=4, max_slope=.12):  # L55-107
    # returns (rows, unassigned_indexes); row = {"members": [idx...], "slope": float, "intercept": float}
    # rows sorted top-to-bottom; members sorted left-to-right
def detect(path, output, args):  # L110-182 — writes labels.json, annotated.jpg, crops/
# CLI defaults: --work-width 2048, --min-width .025, --max-width .09, --min-row-labels 4, --roi L T R B
# NOTE: inkcheck/inkcheck/detector.py L15-107 is byte-identical to L15-107 of this file (diff verified).

# labels.json shape (results/image_01/labels.json):
# {image, original_shape:[h,w], processing_shape, roi_normalized, method,
#  candidate_count:56, visible_row_count:5,
#  rows:[{visible_row, count, line_original_pixels:{slope,intercept},
#         labels:[{id:"r01_p01", position_in_visible_row, box_xyxy, crop_box_xyxy,
#                  crop, rectangularity, status:"unverified_label_candidate", price:null}]}],
#  unassigned_candidates:[{box_xyxy}], notes:[...]}

# From examples/planogram/inkcheck/inkcheck/prepare.py
def prepare(image_paths, planogram, output, visit_id):  # L12-72
    # slot box derivation L37-60:
    #   left/right = midpoints to neighbouring tag centres, clamped to ±0.85*median_width (±0.65 at row ends)
    #   top = previous_row_line(x) + 0.7*tag_height   (first row: tag_top - 0.7*row_gap)
    #   bottom = tag_top - 3px ; label_box = tag box padded (4px, 3px)

# From examples/planogram/inkcheck/inkcheck/catalog.py
def normalize_planogram(data):  # L5-20 — shelves[].products{} -> facings; id f"p{position:03d}_f{index}";
                                #         identity_required = product.upper() != "CLOSEOUT"
def catalog_from_planogram(planogram):  # L23-29
def resolve(identity, catalog):  # L36-54 — "Never use shelf expectations, fuzzy SKU matching, or model-selected catalog IDs."

# From examples/planogram/inkcheck/inkcheck/compare.py
def compare(planogram, observations):  # L6-75 — only observations with facing_id AND mapping_reviewed are grouped (L21-22)
# statuses: match | mismatch | empty | identity_unknown | unknown | conflict | occupied_unassigned

# From examples/planogram/inkcheck/inkcheck/schema.py (Pydantic v2, extra="forbid")
class Facing(StrictModel): ...        # L9-19  id, position, shelf, segment, facing, sku, brand, identity_required, source_confidence, notes
class Region(StrictModel): ...        # L43-51 id, image_id, box, label_box, facing_id, reviewed, enabled, origin
class LabelAssessment(StrictModel): ...  # L84-87 kind, price_text, evidence
class Occupancy(StrictModel): ...     # L90-93 state: occupied|empty|uncertain ; visibility: full|partial|unusable
class Identity(StrictModel): ...      # L96-100 brand, visible_identifiers, visible_text, evidence
class Observation(StrictModel): ...   # L130-143

# From examples/planogram/inkcheck/inkcheck/vision.py
class VisionClient:                   # L19-119 — aiohttp, OpenAI-compatible endpoint
    async def ask(self, stage, png, schema):  # L25 — cache key = hash(prompt version, endpoint config, stage, image b64, schema, prompt)

# From packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:
    @staticmethod
    def create(llm: str, model_args: Optional[Dict[str, Any]] = None,
               tool_manager: Optional[Any] = None, **kwargs) -> AbstractClient:  # L257-339
# LLMFactory.list_providers() includes: 'google', 'openai', 'anthropic', 'local', 'localllm', 'llamacpp', 'ollama', 'vllm', ...

# From packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient:
    async def ask(self, prompt: str, model: str, max_tokens: Optional[int] = None, temperature: float = 0.7,
                  files: Optional[List[Union[str, Path]]] = None, system_prompt: Optional[str] = None,
                  history: Optional[Sequence[HistoryMessage]] = None,
                  structured_output: Union[type, StructuredOutputConfig, None] = None, ...) -> MessageResponse:  # L1796

# From packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py
class GoogleAnalysis:  # mixed into GoogleGenAIClient (hasattr verified)
    async def image_understanding(
        self, prompt: str,
        images: Union[str, Path, bytes, Image.Image, List[Union[str, Path, bytes, Image.Image]]],
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_3_FLASH_PREVIEW,
        prompt_instruction: Optional[str] = None, user_id: Optional[str] = None,
        session_id: Optional[str] = None, stateless: bool = True, timeout: Optional[int] = 600,
        temperature: Optional[float] = None, detect_objects: bool = False,
        response_schema: Optional[Any] = None,
        structured_output: Union[type, StructuredOutputConfig, None] = None,
    ) -> AIMessage:  # L438-625 ; path inputs > 5 MB are uploaded via the File API

# From packages/ai-parrot-client-google/src/parrot/clients/google/client.py
class GoogleGenAIClient:  # L101 ; provider_keys = ("google",) L120
    async def ask_to_image(self, prompt: str, image: Union[Path, bytes],
                           reference_images: Optional[Union[List[Path], List[bytes]]] = None,
                           model: Union[str, GoogleModel] = None, max_tokens: Optional[int] = None,
                           temperature: Optional[float] = None,
                           structured_output: Union[type, StructuredOutputConfig] = None,
                           count_objects: bool = False, history=None, no_memory: bool = False) -> AIMessage:  # L4999

# From packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py
class OpenAIClient(OpenAIBaseClient):  # L87
    async def ask_to_image(self, prompt: str, image: Union[Path, bytes, Image.Image],
                           reference_images=None, model: str = OpenAIModel.GPT5_MINI.value, max_tokens: int = None,
                           temperature: float = None, structured_output: Optional[type] = None,
                           history=None, no_memory: bool = False, low_quality: bool = False) -> AIMessage:  # L1468
# AnthropicClient.ask_to_image exists too: packages/ai-parrot-client-anthropic/.../client.py L1307

# From packages/ai-parrot/src/parrot/clients/openai_base.py
class OpenAIBaseClient(AbstractClient):  # L73
    def _encode_image_for_openai(self, image: Path | bytes | Image.Image, low_quality: bool = False) -> dict[str, Any]:  # L1137
        # returns {"type": "image_url", "image_url": {"url": "data:<mime>;base64,...", "detail": "low"|"auto"}}

# From packages/ai-parrot-client-local/src/parrot/clients/local/client.py
class LocalLLMClient(OpenAIBaseClient):  # L27-369 ; provider_keys = ("local", "localllm", "ollama", "llamacpp")
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None,
                 model: Optional[str] = None, **kwargs):  # L79 ; env: LOCAL_LLM_API_KEY, LOCAL_LLM_BASE_URL, LOCAL_LLM_MODEL
    async def get_client(self) -> "AsyncOpenAI":  # L91
    async def ask(self, prompt: str, model=None, **kwargs):  # L117
    async def invoke(...):  # L186
```

#### Verified Imports
```python
# Confirmed by execution in the shared venv:
from parrot.clients.factory import LLMFactory
from parrot.clients.google import GoogleGenAIClient          # same object as parrot.clients.google.client.GoogleGenAIClient
from parrot.clients.google.models import GoogleModel         # GoogleModel.GEMINI_3_8_FLASH.value == "gemini-3.8-flash" (models.py L19)
from parrot.clients.local.client import LocalLLMClient
from rapidocr import RapidOCR                                # engine(img) -> result with .txts
import cv2, numpy, rapidfuzz                                 # installed
```

#### Key Attributes & Constants
- Planogram JSON top level → `{"planogram": {...8 meta keys...}, "shelves": [6]}`; shelf → `shelf`, `shelf_number`, `product_count`, `facing_count`, `products: {"pos <shelf>:<slot>": {...}}`.
- Product record → `position`, `segment` (`left`|`right`), `segment_number`, `slot` (left→right across the shelf), `segment_slot`, `product` (part number), `brand`, `shelf`, `facings`, `confidence`, `read_method`, `notes`.
- Planogram stats → 102 positions / 104 facings; shelf sizes 17, 18, 18, 18, 16, 15; brands HP, Epson, Canon, Brother, Paris Corp, Paris Business, one `None` (CLOSEOUT, `facings: 3`, shelf 5); `read_method` direct 58 / inferred 40 / partial 4; no duplicate SKUs.
- Every shelf 1–5 starts with 9 HP positions in the left segment (brand sequence alone is non-discriminative).
- Local llama.cpp server → `http://127.0.0.1:8089/v1` (inkcheck `config.local.json`); llama.cpp needs `cache_prompt: false` with JSON-schema constraints for LFM2.5-VL (inkcheck README §2).
- Installed OCR stack → `rapidocr 3.9.2`, `onnxruntime 1.30.0`, `easyocr 1.7.2`, `paddleocr 3.2.0`, `pytesseract 0.3.13` (binary missing).

### Does NOT Exist (Anti-Hallucination)
- ~~`AbstractClient.ask_to_image`~~ — there is **no** vision method on the base client; `hasattr` is `False`.
- ~~`LocalLLMClient.ask_to_image`~~ / ~~`OpenAIBaseClient.ask_to_image`~~ — not defined; only `OpenAIClient`, `AnthropicClient`, `GoogleGenAIClient` have it (with different signatures).
- ~~`from parrot.models.google import GoogleModel`~~ — ImportError; the enum lives in `parrot.clients.google.models`.
- ~~`tesseract` binary~~ — not installed; `pytesseract` would fail at runtime.
- ~~prices / product names / physical widths in `planogram_page1.json`~~ — none of these fields exist.
- ~~any automatic registration in inkcheck~~ — `facing_id` is only set by the manual `review.html`; there is no alignment code to reuse.
- ~~`import detect_price_labels` as a package~~ — it is a standalone script in a directory without `__init__.py`; adapt the functions, do not import.
- ~~`examples/planogram/**` in git~~ — the whole directory is ignored and untracked; a worktree will contain **none** of the inputs.
- ~~reuse of `parrot_pipelines.planogram.PlanogramCompliance`~~ — a different, pure-LLM, config/DB-driven pipeline; intentionally not used here.

---

## Parallelism Assessment

- **Internal parallelism**: Low. The deliverable is one script; the pure-function
  blocks (slot grid, price grammar, alignment, merge/scoring) are logically
  independent but land in the same file, so parallel worktrees would only produce
  merge conflicts. Tasks should be sequential, ordered along the pipeline stages.
- **Cross-feature independence**: High. Touches only `examples/planogram/`; no
  overlap with FEAT-564 (video-reel) or any in-flight spec, and
  `parrot_pipelines.planogram` is untouched.
- **Recommended isolation**: `per-spec`.
- **Rationale**: single file + sequential stages. **Caveat**: because
  `examples/planogram/` is git-ignored, a worktree created from `origin/dev`
  contains no images, no planogram JSON and no detector — end-to-end runs can
  only happen in the main checkout. Either resolve the tracking question first
  or implement on a plain branch in the primary checkout (the worktree rule
  allows skipping worktrees for small example work).

---

## Open Questions

- [x] Flow type / base branch — *Owner: Jesus Lara*: feature on `dev`.
- [x] Relationship to inkcheck / ai-parrot — *Owner: Jesus Lara*: standalone script, LLM via ai-parrot clients; inkcheck is reference only.
- [x] Input unit — *Owner: Jesus Lara*: N photos of one fixture, merged per planogram position.
- [x] LLM feeding strategy — *Owner: Jesus Lara*: photo (row strip) + JSON of detected areas.
- [x] Vision backends — *Owner: Jesus Lara*: Gemini Flash, local llama.cpp server, and any pluggable `provider:model`.
- [x] Registration — *Owner: Jesus Lara*: automatic sequence alignment, inferred slots flagged; no CLI hints required.
- [x] Scoring strictness — *Owner: Jesus Lara*: tiered; strict % and lenient % reported side by side, per shelf and overall.
- [x] Prices — *Owner: Jesus Lara*: always reported; optional `--prices` file adds a separate price-compliance metric.
- [x] Tag OCR engine — *Owner: Jesus Lara*: local OCR first, LLM fallback.
- [ ] Git tracking: should `planogram_check.py` (+ tests, `planogram_page1.json`, the detector) be force-added / un-ignored so the SDD flow and worktrees can see them, or does this stay a local-only example? Store photos are large and possibly sensitive — track them, or a downscaled fixture set, or nothing? — *Owner: Jesus Lara*
- [ ] Part-number ↔ consumer-name bridge: is there an authoritative catalog (BBY SKU / cartridge family / colour / pack) we can ship as `catalog.json`, or is a cached one-off LLM enrichment with human correction acceptable for v1? — *Owner: Jesus Lara*
- [ ] Partial-credit weights for the lenient score (`misplaced`, `variant_unresolved`, `inferred_present`, `verified_by_expectation`): proposed 0.5 / 0.5 / 0.5 / 1.0 — confirm or supply business weights. — *Owner: Jesus Lara*
- [ ] Ground truth: is there (or can we produce) a hand-labelled answer for the two store-560 photos? Without it we can test determinism and plumbing but cannot report identification accuracy. — *Owner: Jesus Lara*
- [ ] Single file vs small package: the recommended design is ~900–1200 lines. Keep strictly one `planogram_check.py`, or allow `planogram_check.py` + a sibling helper package? — *Owner: Jesus Lara*
- [ ] Which vision model runs on the local `:8089` server for this script (LFM2.5-VL-1.6B as in inkcheck, or the qwen vision model from the recent `llama server for vision model` WIP)? It determines whether the row-strip contract is realistic locally or sub-strips must be the default there. — *Owner: Jesus Lara*
- [ ] Should the `VisionBackend` adapter stay script-local, or is the missing common vision method on `AbstractClient` / `LocalLLMClient` worth its own core feature later? (Out of scope here — `clients/base.py` must not be modified without discussion.) — *Owner: Jesus Lara*
- [ ] Set-of-Marks overlays: do thin numbered outlines measurably help Gemini on these strips, or do they occlude small package text? To be settled by an A/B run during implementation. — *Owner: implementer*
