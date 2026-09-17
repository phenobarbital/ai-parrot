<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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

### Constraints and goals
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

### Recommended option / probable scope
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

### Recommended option body (Option D)

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

### Verified code anchors (paths only — open them yourself)
examples/planogram/inkcheck/inkcheck/catalog.py
examples/planogram/inkcheck/inkcheck/compare.py
examples/planogram/inkcheck/inkcheck/prepare.py
examples/planogram/inkcheck/inkcheck/schema.py
examples/planogram/inkcheck/inkcheck/vision.py
examples/planogram/planogram_page1.json
examples/planogram/results/image_01/labels.json
examples/planogram/white_label_detector/detect_price_labels.py
packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py
packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py
packages/ai-parrot-client-google/src/parrot/clients/google/client.py
packages/ai-parrot-client-local/src/parrot/clients/local/client.py
packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py
packages/ai-parrot/src/parrot/clients/base.py
packages/ai-parrot/src/parrot/clients/factory.py
packages/ai-parrot/src/parrot/clients/openai_base.py

### Questions still open in the exploration document
- [ ] Partial-credit weights for the lenient score (`misplaced`, `variant_unresolved`, `inferred_present`, `verified_by_expectation`): proposed 0.5 / 0.5 / 0.5 / 1.0 — confirm or supply business weights. — *Owner: Jesus Lara*
- [ ] Ground truth: is there (or can we produce) a hand-labelled answer for the two store-560 photos? Without it we can test determinism and plumbing but cannot report identification accuracy. — *Owner: Jesus Lara*
- [ ] Which vision model runs on the local `:8089` server for this script (LFM2.5-VL-1.6B as in inkcheck, or the qwen vision model from the recent `llama server for vision model` WIP)? It determines whether the row-strip contract is realistic locally or sub-strips must be the default there. — *Owner: Jesus Lara*
- [ ] Should the `VisionBackend` adapter stay script-local, or is the missing common vision method on `AbstractClient` / `LocalLLMClient` worth its own core feature later? (Out of scope here — `clients/base.py` must not be modified without discussion.) — *Owner: Jesus Lara*
- [ ] Set-of-Marks overlays: do thin numbered outlines measurably help Gemini on these strips, or do they occlude small package text? To be settled by an A/B run during implementation. — *Owner: implementer*

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
