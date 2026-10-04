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
The planogram cycle (`perceive → identify → compare`, FEAT-574) can today only
run its Stage-2 identification on Google, Anthropic or OpenAI. Amazon Nova 2 Lite
is a cheap, 1M-context, natively multimodal model that AWS explicitly markets for
grounded object detection, and it is the natural candidate for the high-volume
store-photo workload — but **no parrot client can send it an image**, so it has
never been measured against the incumbents on real ink-wall photos.

Two independent facts block it:

1. `BedrockConverseBase._prepare_messages` logs a warning and **silently drops**
   every file/image attachment
   (`packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py:725-745`).
2. `ask_to_image` — the single entry point the planogram vision adapter calls —
   is implemented only on the Anthropic, Google and OpenAI clients. Bedrock/Nova
   has no implementation at all.

Affected: the planogram/retail-compliance workstream (cost per photo is the
dominant operating constraint), and anyone who wants Nova for vision anywhere in
ai-parrot.

We want an **executable example** — `examples/planogram/aws/nova2.py` — that
feeds real OpenCV detection boxes to Nova 2 Lite and gets back, per box, whether
a product is present and which brand/product it is. The example is both a
demonstrator and the empirical evidence that justifies (or kills) the later
client-level work.

### Constraints and goals
- **No production client changes in this feature.** Teaching
  `BedrockConverseBase` to carry Converse image blocks is a deliberate
  follow-up (see Open Questions); this feature ships an example only.
- Must not duplicate logic that already exists and is tested in
  `parrot_pipelines.planogram.identification` — reuse the marking, chunking and
  response-reconciliation helpers, write only the Nova transport.
- Async-first: no blocking I/O. `aioboto3>=13.2.0` is already a declared
  dependency of `ai-parrot-client-amazon`
  (`packages/ai-parrot-client-amazon/pyproject.toml:17`) — **no new package**.
- Boxes come from the real Stage-1 perception (`propose_shapes` → `group_rows` →
  `build_slots`), with a `--boxes <PerceptionResult.json>` override so a run is
  reproducible without re-running OpenCV.
- Nova 2 Lite has **no in-region model access in any region**: a geo inference
  profile is mandatory. Default model id `us.amazon.nova-2-lite-v1:0`.
- Credentials resolve the same way the rest of the repo does: `parrot.conf`
  `AWS_CREDENTIALS` keyed by `aws_id`, with an environment fallback — never
  hard-coded, never committed.
- Coordinates: perception speaks **source-image pixels** (`Shape.box`,
  `Slot.box` are `DetectionBox`); Nova speaks **0–1000 normalised
  `[ymin, xmin, ymax, xmax]`**. A two-way conversion is mandatory in both
  directions.
- Output: flat `{bbox, brand, product, occupancy, ...}` JSON plus an annotated
  JPEG, written under `--output <dir>`.
- `examples/planogram/*` is git-ignored (`.gitignore:418`) — every new file in
  this feature needs `git add -f`.

---

### Recommended option / probable scope
**Option A** is recommended.

It is the only option that satisfies both discovery decisions simultaneously:
ship the example *now* without touching production clients (ruling out C), and
still get Set-of-Marks, closed-set prompting and a repair retry without writing
them from scratch (ruling out B). The `hasattr(client, "ask_to_image")` duck-type
in `VisionAdapter.__init__` is a genuine, already-intended extension seam — the
adapter's own docstring says "on **any** client exposing `ask_to_image`" — so
using it is not a hack around the design, it is the design.

What we trade away, honestly:

- **Coupling to pipeline internals.** The example will import `identify_strips`
  and construct a `CycleContext`, so a refactor inside `identification/` can
  break it. Accepted because the alternative (Option B) guarantees divergence
  rather than merely risking breakage, and a broken import is loud while silent
  prompt drift is not.
- **Two prompt builders.** The shared `build_identify_prompt` must stay open-set
  by contract, so the closed-set variant lives in the example and will not track
  changes to the shared one. Accepted, and flagged as an Open Question: if the
  closed-set prompt wins on accuracy, promoting it into the pipeline as an
  opt-in mode becomes a follow-up in its own right.
- **Nova stays broken for everyone else.** Option C's real bug is untouched.
  Accepted deliberately: this example produces the evidence that says whether
  that bug is worth fixing, and its shim is the prototype implementation.

Option D is not recommended now but is explicitly worth revisiting once
Option A has a baseline — it is the natural second feature, not a competitor.

---

### Option A: Nova transport shim behind the existing `VisionAdapter`

`VisionAdapter` is **duck-typed**: its only requirement is that the client
expose `ask_to_image`, checked with `hasattr` at construction
(`identification/vision.py:157-161`). Nothing else about the client is special.

So the example ships a small `examples/planogram/aws/nova_vision.py` exposing a
`NovaVisionClient` with `client_name = "nova"` and
`async def ask_to_image(prompt, image, **kwargs)` implemented over `aioboto3`'s
`bedrock-runtime` `converse` call, returning a lightweight object carrying the
model's text in `.output`. `nova2.py` then:

1. runs Stage-1 perception (or loads `--boxes`),
2. builds a `CycleContext` whose `vision` is a `VisionAdapter` wrapping the Nova
   shim,
3. calls the existing `identify_strips(...)` with `marks=True`,
4. flattens the resulting `IdentificationResult` to the requested
   `{bbox, brand, product, occupancy}` JSON and draws the annotated image.

Set-of-Marks rendering, per-row chunking, concurrency, the response cache, the
**repair retry** and id reconciliation all come for free — `VisionAdapter.ask`
already implements the retry, and `validate_response` already drops hallucinated
ids and backfills missing ones as `occupancy="unknown"`.

Crucially, `normalise_kwargs` (`vision.py:35-61`) falls back to the common kwarg
subset for any provider not in `SUPPORTED_KWARGS` — `"nova"` is not listed, so
it receives `{model, max_tokens, temperature, structured_output,
reference_images}` and `_final_prompt` folds the system prompt into the user
prompt automatically. **The pipeline package needs no edit whatsoever.**

One genuine consequence: `build_identify_prompt` is contractually open-set — its
docstring states it "Must NOT mention a planogram or expected products"
(`identification/identify.py:119-130`). The closed-set-from-planogram behaviour
chosen in discovery therefore needs a **local** prompt builder in the example
(`build_nova_identify_prompt`), not a change to the shared one.

✅ **Pros:**
- Zero changes to `ai-parrot-pipelines` or any client — pure addition under `examples/`.
- Reconciliation, repair-retry, caching and Set-of-Marks are reused, not rewritten (~150 lines of new code instead of ~450).
- The shim's `ask_to_image` body is a near copy-paste lift into `BedrockConverseBase` when the follow-up feature lands, so this example *is* the prototype for that work.
- Results are directly comparable to the Google/Claude/OpenAI runs because the prompt, marking and validation path are identical apart from the closed-set prompt.

❌ **Cons:**
- The example is coupled to `parrot_pipelines.planogram` internals, several of which are private-ish (`_targets`, `_id_allocator`, `_finalise`) and may drift.
- Two prompt builders now exist (shared open-set, example closed-set), which can silently diverge.
- Reading the example no longer tells the whole story — a reader must also read `identify.py`.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aioboto3` | async `bedrock-runtime` Converse calls | `>=13.2.0`, already declared in `ai-parrot-client-amazon/pyproject.toml:17` |
| `opencv-python` | image decode, Set-of-Marks drawing, annotation | already used throughout `planogram/` |
| `numpy` | BGR arrays | already a perception dependency |
| `pydantic` v2 | `IdentificationResponse` schema + CLI config | already the repo standard |

🔗 **Existing Code to Reuse:**
- `parrot_pipelines/planogram/identification/vision.py:131` — `VisionAdapter`, duck-typed on `ask_to_image`; brings the repair retry and the on-disk response cache.
- `parrot_pipelines/planogram/identification/identify.py:90` — `render_marked_strip`, the Set-of-Marks renderer.
- `parrot_pipelines/planogram/identification/identify.py:464` — `identify_strips`, per-row chunked concurrent calls with per-strip failure isolation.
- `parrot_pipelines/planogram/identification/identify.py:212` — `validate_response`, id reconciliation and added-shape acceptance.
- `parrot_pipelines/planogram/perception/slots.py:242,263` — `to_strip_norm` / `from_strip_norm`, the pixel ↔ 0–1000 converters.
- `parrot_pipelines/planogram/perception/shapes.py:128` + `rows.py:20` + `slots.py:115` — the Stage-1 chain.

---

### Verified code anchors (paths only — open them yourself)
.claude/rules/codebase-conventions.md
anthropic/claude_agent.py
clients/anthropic/client.py
clients/google/client.py
clients/openai/client.py
packages/ai-parrot-client-amazon/pyproject.toml
packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py
packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/client.py
packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/backend.py
packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py
packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py
packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py
packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/rows.py
packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/shapes.py
packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py
perception/__init__.py

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
