---
type: feature
base_branch: dev
projects: [ai-parrot-pipelines, ai-parrot-client-amazon]
tags: [nova, bedrock, planogram, vision, object-detection]
---

# Feature Specification: Amazon Nova 2 Lite slot identification for planogram images

**Feature ID**: FEAT-592
**Date**: 2026-09-23
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.0.6

---

## 1. Motivation & Business Requirements

### Problem Statement

The planogram cycle (`perceive → identify → compare`, FEAT-574) can today only run its
Stage-2 identification on Google, Anthropic or OpenAI. Amazon Nova 2 Lite is a cheap,
1M-context, natively multimodal model that AWS explicitly markets for grounded object
detection, and it is the natural candidate for the high-volume store-photo workload —
but **no parrot client can send it an image**, so it has never been measured against
the incumbents on real ink-wall photos.

Two independent facts block it:

1. `BedrockConverseBase._prepare_messages` logs a warning and **silently drops** every
   file/image attachment (`bedrock.py:725-745`).
2. `ask_to_image` — the single entry point the planogram vision adapter calls — is
   implemented only on the Anthropic, Google and OpenAI clients. Bedrock/Nova has no
   implementation at all.

Affected: the planogram/retail-compliance workstream (cost per photo is the dominant
operating constraint), and anyone who wants Nova for vision anywhere in ai-parrot.

We want an executable example — `examples/planogram/aws/nova2.py` — that feeds real
OpenCV detection boxes to Nova 2 Lite and gets back, per box, whether a product is
present and which brand/product it is. The example is both a demonstrator and the
empirical evidence that justifies (or kills) the later client-level work.

### Goals

- G1 — Ship a runnable example that identifies products/brands per detection box on
  Nova 2 Lite, producing flat `{bbox, brand, product, occupancy}` JSON in
  source-image pixels plus an annotated image.
- G2 — Reuse the existing planogram machinery (marking, reconciliation, repair retry,
  response cache) rather than reimplementing it.
- G3 — Change **nothing** under `packages/` — the example is pure addition, and the
  Bedrock image-support defect is a separate follow-up feature.
- G4 — Delegate AWS credentials, region, model translation and client lifetime to the
  existing `NovaClient` instead of re-resolving configuration.
- G5 — Record cost, latency and provider-call counts per run so the go/no-go decision
  on Nova can be made from evidence.
- G6 — Make the new example files reliably trackable in git, following the repo's
  existing negation-rule convention.

### Non-Goals (explicitly out of scope)

- Teaching `BedrockConverseBase` to carry Converse image content blocks, and adding a
  real `ask_to_image` to the Bedrock/Nova clients. Rejected for *this* feature in the
  brainstorm (Option C) — the example produces the evidence that justifies that work.
- Promoting closed-set prompting into `parrot_pipelines`. `build_identify_prompt` stays
  contractually open-set; see `proposals/nova-image-planogram.brainstorm.md` Open
  Questions.
- Running Nova as a free-running detector and arbitrating its boxes against OpenCV's
  (brainstorm Option D) — a natural follow-up, not part of this feature.
- Any change to comparison/scoring: this feature stops at identification.

---

## 2. Architectural Design

### Overview

Brainstorm **Option A** — a Nova transport shim behind the existing `VisionAdapter`.

`VisionAdapter` is duck-typed: its only requirement is that the client expose
`ask_to_image`, checked with `hasattr` at construction (`vision.py:157-161`). Its own
docstring says "on **any** client exposing `ask_to_image`", so this is the intended
extension seam, not a workaround. The example therefore supplies a small
`NovaVisionClient` and inherits the repair retry, the on-disk response cache and the
kwarg normalisation unchanged.

Two corrections to the brainstorm's plan, both found during §4 research and
independently raised by the design-research seat (§9 S1, S3, S11):

1. **The example cannot call `identify_strips`.** `_run_call` (`identify.py:331`)
   calls `build_identify_prompt` by module-level name — there is no prompt-builder
   hook. Since the closed-set prompt is a resolved requirement, the example owns a
   ~60-line per-strip loop built from the *public* helpers (`strip_box`,
   `render_marked_strip`, `validate_response`, `VisionAdapter.ask`). It does **not**
   monkeypatch the pipeline and does **not** import underscore-prefixed internals.
2. **The shim composes `NovaClient` rather than building its own session.**
   `BedrockConverseBase` already resolves the `AWS_CREDENTIALS` profile chain
   (`bedrock.py:300-313`), the region, the geo-prefixed model id
   (`translate_bedrock_model`, `bedrock.py:434`) and a loop-local `aioboto3`
   bedrock-runtime client with cleanup (`get_client()` 338, `close()` 673). The shim
   calls `await nova.get_client()` and issues one `converse` call.
3. **Trackability is a `.gitignore` negation, not `git add -f`.** `.gitignore:418`
   ignores `examples/planogram/*`, and the repo's convention for example code is
   explicit negation rules (`.gitignore:438-441` for `pipelines/`).

Because Bedrock `converse` has no `structured_output` parameter, the shim renders the
requested Pydantic schema into a JSON-schema instruction appended to the prompt and
returns the model's raw text. `VisionAdapter._extract` (`vision.py:278-302`) already
strips ```` ```json ```` fences and validates, so the shim parses nothing itself.

### Component Diagram

```
nova2.py (CLI)
   │
   ├─→ perceive()  ──→ CpuExecutor.run(propose_shapes) ──→ group_rows ──→ build_slots
   │                    └─→ candidate_shape_id ──→ assign_membership ──→ PerceptionResult
   │        (mirror of types/ink_wall.py:181-214)
   │
   ├─→ prompt.py: load_planogram_vocabulary() ──→ PlanogramVocabulary(products, brands)
   │
   └─→ identify.py: identify_strips_closed_set()
            │   per row-chunk:
            │     strip_box() ─→ CpuExecutor.run(render_marked_strip) ─→ PNG
            │     to_strip_norm() ─→ areas JSON
            │     build_nova_identify_prompt(areas, vocabulary, schema_instruction)
            │        ↓
            │     VisionAdapter.ask(...)        [repair retry + cache, unchanged]
            │        ↓
            │     NovaVisionClient.ask_to_image(...)
            │        ↓
            │     NovaClient.get_client() ─→ bedrock-runtime.converse
            │        ↓
            │     validate_response()  [id reconciliation, added_shapes]
            │
            └─→ flatten() ─→ [FlatDetection]  ─→ detections.json + annotated.jpg + run.json
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `VisionAdapter` (`vision.py:131`) | uses (duck-type) | Constructed with `NovaVisionClient`; supplies repair retry + cache. Not modified. |
| `NovaClient` (`nova/client.py:34`) | composes | Source of credentials, region, resolved model id and the live bedrock-runtime client. Not modified. |
| `render_marked_strip` (`identify.py:90`) | calls | Set-of-Marks renderer, run through `CpuExecutor`. |
| `validate_response` (`identify.py:212`) | calls | Id reconciliation + added-shape acceptance. |
| `strip_box` / `to_strip_norm` / `from_strip_norm` (`slots.py:214,242,263`) | calls | Strip geometry and the pixel ↔ 0–1000 conversion. |
| `propose_shapes` / `group_rows` / `build_slots` / `candidate_shape_id` / `assign_membership` | calls | Stage-1 chain, mirroring `types/ink_wall.py:181-214`. |
| `CpuExecutor` (`perception/executor.py:17`) | uses | All OpenCV work stays off the event loop. |
| `identify_strips` (`identify.py:464`) | **not used** | No prompt-builder hook; the example owns its loop. See §9 S1. |
| `build_identify_prompt` (`identify.py:119`) | **not used, not modified** | Contractually open-set. |
| `.gitignore` | modifies | Negation rules for `examples/planogram/aws/`. |
| `examples/planogram/tests/test_plancheck_gitignore.py` | modifies | One `NOT_IGNORED` row guarding the tracking decision. |

### Data Models

```python
# examples/planogram/aws/prompt.py
class PlanogramVocabulary(BaseModel):
    """Closed-set candidates read from a planogram JSON — product + brand ONLY."""
    products: List[str]    # distinct, sorted; e.g. ["9C228AN", ...]
    brands: List[str]      # distinct, sorted; e.g. ["Canon", "Epson", "HP", ...]

# examples/planogram/aws/identify.py
class FlatDetection(BaseModel):
    """One row of detections.json. ``bbox`` is ALWAYS source-image pixels."""
    shape_id: str
    bbox: List[int]                    # [x1, y1, x2, y2], source-image pixels
    occupancy: str                     # "occupied" | "empty" | "unknown"
    brand: Optional[str] = None
    product: Optional[str] = None
    text: Optional[str] = None
    confidence: float = 0.0            # Identification.raw_confidence, never modified
    evidence: Optional[str] = None
    source: str = "cv"                 # "cv" | "llm_added"
    inferred: bool = False             # True for gap-filled slots
    uncertain: bool = False

class RunStats(BaseModel):
    """Provider-call accounting — one strip can cost up to three calls (§9 S8)."""
    strips: int = 0
    failed_strips: int = 0
    calls: int = 0                     # every ask_to_image that reached Bedrock
    cache_hits: int = 0
    incomplete_retries: int = 0        # the missing-id repair prompt
    image_bytes_sent: int = 0          # total PNG bytes actually transmitted (§9 S9 guard)
    input_tokens: int = 0
    output_tokens: int = 0
    wall_seconds: float = 0.0
```

### New Public Interfaces

```python
# examples/planogram/aws/nova_vision.py
class NovaVisionClient:
    """Bedrock Converse image transport that satisfies VisionAdapter's duck-type."""
    client_name: str = "nova"
    async def ask_to_image(self, *, prompt: str, image: bytes, **kwargs: Any) -> "NovaAnswer": ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: gitignore tracking rules | yes | Exact 4 lines to append after `.gitignore:441`, copying the `pipelines/` block shape; one `NOT_IGNORED` string in the existing list. | — |
| M2: Nova Converse transport shim | yes | Class name, `client_name="nova"`, `ask_to_image` kwargs fixed by `_COMMON` (vision.py:21), composes `NovaClient`, returns `.output` text. Converse request shape decided in the skeleton. | — |
| M3: vocabulary + closed-set prompt | yes | JSON path `shelves[].products{}` → `product`/`brand` only (resolved). Prompt contract fixed: same AREAS shape as `build_identify_prompt`, plus the candidate lists and the schema instruction. | — |
| M4: strip orchestration + flatten | yes | Loop shape, chunk cap 8, `validate_response` call with `strip=<strip box>`, join rules for the flat output all fixed below. | — |
| M5: CLI, perception, outputs | yes | Perception tail is a line-for-line mirror of `ink_wall.py:181-214`; flags, exit codes and output files enumerated in §2/§5. | — |

### Module 1: Git tracking rules for `examples/planogram/aws/`
- **Path**: `.gitignore`, `examples/planogram/tests/test_plancheck_gitignore.py`
- **Responsibility**: Make the new example directory trackable by the repo's existing
  negation convention, so later helper files cannot silently vanish from commits.
- **Depends on**: nothing
- **Interface Skeleton**:
  ```gitignore
  # .gitignore  (modifies .gitignore:441 — append immediately after)
  # FEAT-592: Nova 2 Lite planogram identification example (code only —
  # photos, results and the vision cache are retailer-derived and stay ignored)
  !examples/planogram/aws/
  examples/planogram/aws/*
  !examples/planogram/aws/*.py
  !examples/planogram/aws/README.md
  ```
  ```python
  # examples/planogram/tests/test_plancheck_gitignore.py  (modifies :15)
  NOT_IGNORED = [
      ...,
      "examples/planogram/aws/nova2.py",   # FEAT-592
  ]
  ```
  This is not a test of the shim (the user resolved "no test" for that) — it extends an
  existing invariant test that already guards which example paths are trackable.

### Module 2: Nova Converse transport shim
- **Path**: `examples/planogram/aws/nova_vision.py` (new)
- **Responsibility**: The only new AWS-facing code. Turns a prompt + PNG bytes + a
  Pydantic schema into one `bedrock-runtime.converse` call and returns the model's raw
  text. Delegates every configuration concern to a composed `NovaClient`.
- **Depends on**: `NovaClient` (existing)
- **Interface Skeleton**:
  ```python
  # examples/planogram/aws/nova_vision.py  (new)
  from parrot.clients.amazon.nova.client import NovaClient  # verified: nova/client.py:34

  class NovaAnswer:
      """Minimal AIMessage-like carrier. VisionAdapter._extract reads ``.output``.

      verified: vision.py:280 reads ``structured_output`` then ``output``; a str is
      accepted and ```json fences are stripped before json.loads.
      """
      output: str
      usage: Dict[str, int]          # {"input_tokens", "output_tokens"} from Converse
      image_bytes: int               # PNG bytes actually transmitted (§9 S9 guard)

  class NovaVisionClient:
      """``ask_to_image``-compatible Bedrock Converse image transport for Nova.

      Satisfies VisionAdapter's duck-type — verified: vision.py:157-161 raises
      VisionError unless ``hasattr(client, "ask_to_image")``.
      """

      client_name: str = "nova"      # read by VisionAdapter — verified: vision.py:165

      def __init__(self, nova: NovaClient, model_id: str) -> None:
          """Bind an already-configured NovaClient and its fully resolved model id."""

      @classmethod
      async def create(
          cls,
          *,
          aws_id: Optional[str] = None,
          region: Optional[str] = None,
          model: str = "nova-2-lite",
          region_prefix: Optional[str] = "us",
      ) -> "NovaVisionClient":
          """Build a NovaClient, resolve the geo-prefixed model id, open the runtime client.

          Credentials/region come from NovaClient's own chain — verified:
          bedrock.py:300-313 (aws_id → AWS_CREDENTIALS profile → 'default' → env).
          The model id is resolved via the client, NOT re-derived here — verified:
          bedrock.py:434 ``translate_bedrock_model(raw, self._region_prefix)``.

          Raises:
              RuntimeError: the resolved model id carries no geo/global prefix while
                  the model has no in-region access (Nova 2 Lite, Nova Premier).
          """

      @property
      def resolved_model_id(self) -> str:
          """The exact id sent to Bedrock, e.g. ``us.amazon.nova-2-lite-v1:0``.

          Used as the backend model in ResolvedBackend so the response cache keys on
          the effective route, not on an alias — see §9 S10.
          """

      async def ask_to_image(
          self,
          *,
          prompt: str,
          image: bytes,
          model: Optional[str] = None,
          max_tokens: int = 8192,
          temperature: float = 0.0,
          structured_output: Optional[Type[BaseModel]] = None,
          reference_images: Optional[List[bytes]] = None,
      ) -> NovaAnswer:
          """One Converse call with a PNG image block; returns the raw answer text.

          The kwarg set is fixed by VisionAdapter for an unregistered provider —
          verified: vision.py:21 ``_COMMON`` and vision.py:52 ``SUPPORTED_KWARGS.get
          (client_name, _COMMON)``; ``None`` values are dropped before the call.

          Bedrock Converse has NO ``structured_output`` parameter (§9 S2): the schema
          is rendered by ``_schema_instruction`` and appended to the prompt text.
          ``reference_images`` become additional image blocks in the same user message.

          Before sending, the assembled content blocks are checked: a request that
          carries no image block is REFUSED, never sent (§9 S9 / §8 Q1). A text-only
          Converse call returns plausible JSON and would silently turn the whole
          experiment into a measurement of nothing.

          Returns:
              NovaAnswer whose ``output`` is the model's text, whose ``usage`` carries
              the Converse token counts, and whose ``image_bytes`` is the PNG payload
              actually transmitted.

          Raises:
              RuntimeError: the assembled request carries no image content block, or
                  Converse returned no text content block.
          """

      @staticmethod
      def _assert_has_image(blocks: Sequence[Dict[str, Any]]) -> int:
          """Guard: the request must carry at least one image block; return its total bytes.

          Raises:
              RuntimeError: no block in ``blocks`` is an ``{"image": ...}`` block.
          """

      @staticmethod
      def _schema_instruction(schema: Type[BaseModel]) -> str:
          """Render ``schema.model_json_schema()`` into a 'reply with only this JSON' rule."""

      async def aclose(self) -> None:
          """Close the composed NovaClient — verified: bedrock.py:673 ``async def close``."""
  ```

### Module 3: Planogram vocabulary + closed-set prompt
- **Path**: `examples/planogram/aws/prompt.py` (new)
- **Responsibility**: Read the closed-set candidates out of a planogram JSON and build
  the identification prompt. Deliberately example-local: the shared
  `build_identify_prompt` must not mention a planogram (`identify.py:125`).
- **Depends on**: Module 2 (for the schema instruction string)
- **Interface Skeleton**:
  ```python
  # examples/planogram/aws/prompt.py  (new)
  NOVA_PROMPT_VERSION: str = "nova-closed-set-v1"
  NOVA_STAGE: str = "identify-nova"
  # Distinct from IDENTIFY_PROMPT_VERSION="identify-v1" / IDENTIFY_STAGE="identify"
  # (verified: identify.py:33-34) so cache entries can never collide — cache_key
  # mixes both (verified: vision.py:63-75).

  class PlanogramVocabulary(BaseModel):
      """Closed-set candidates: ``product`` and ``brand`` ONLY (resolved decision)."""
      products: List[str]
      brands: List[str]

  def load_planogram_vocabulary(path: Path) -> PlanogramVocabulary:
      """Distinct product/brand values from ``shelves[].products{}`` of a planogram JSON.

      Shape verified against examples/planogram/planogram_page1.json:
      ``{"planogram": ..., "shelves": [{"products": {"pos 1:1": {"product": "9C228AN",
      "brand": "HP", ...}}}]}``. Descriptor fields (display_name, family, xl, colors,
      pack, aliases) are deliberately NOT read — resolved decision, keeps the prompt short.

      Returns:
          Sorted, de-duplicated products and brands; empty lists are legal.

      Raises:
          ValueError: the file is not a planogram JSON (no ``shelves`` list).
      """

  def build_nova_identify_prompt(
      areas: Sequence[Dict[str, Any]],
      vocabulary: PlanogramVocabulary,
      schema_instruction: str,
  ) -> str:
      """Closed-set counterpart of build_identify_prompt (verified: identify.py:119).

      Keeps that function's AREAS contract verbatim — ``id``, ``mark``, ``box_2d``
      ([ymin,xmin,ymax,xmax] 0-1000 relative to the strip sent), ``ocr_text`` — and the
      same per-area rules (report only from inside the box; one entry per area;
      occupancy/product/brand/raw_confidence/evidence; null when not legible; extra
      products only under ``added_shapes``).

      Differs in exactly one way: it offers the planogram's products and brands as the
      expected candidates, and tells the model it may answer outside the list when the
      package clearly shows something else.

      Args:
          areas: ``{"id", "mark", "box_2d", "ocr_text"}`` per area.
          vocabulary: Closed-set candidates.
          schema_instruction: From ``NovaVisionClient._schema_instruction``.

      Returns:
          The prompt text.
      """
  ```

### Module 4: Strip orchestration and flattening
- **Path**: `examples/planogram/aws/identify.py` (new)
- **Responsibility**: The per-row call loop `identify_strips` would have provided, with
  the closed-set prompt substituted, plus the join from `IdentificationResult` back to
  boxes. All OpenCV work goes through the `CpuExecutor`.
- **Depends on**: Modules 2 and 3
- **Interface Skeleton**:
  ```python
  # examples/planogram/aws/identify.py  (new)
  from parrot_pipelines.planogram.identification.identify import (  # verified: identify.py:90,212
      render_marked_strip, validate_response,
  )
  from parrot_pipelines.planogram.perception.slots import strip_box, to_strip_norm  # verified: slots.py:214,242

  SUBSTRIP_MAX_SLOTS: int = 8   # mirrors identify_strips' default (verified: identify.py:471)

  class FlatDetection(BaseModel):
      """One row of detections.json — see §2 Data Models."""

  class RunStats(BaseModel):
      """Provider-call accounting — see §2 Data Models."""

  async def identify_strips_closed_set(
      image: np.ndarray,
      perception: PerceptionResult,
      vision: VisionAdapter,
      vocabulary: PlanogramVocabulary,
      *,
      executor: CpuExecutor,
      schema_instruction: str,
      marks: bool = True,
      substrip_max_slots: int = SUBSTRIP_MAX_SLOTS,
  ) -> Tuple[IdentificationResult, RunStats]:
      """One call per row (sub-strips above the cap), concurrently; a failed strip is isolated.

      Example-local replacement for identify_strips (verified: identify.py:464), which
      cannot be reused because _run_call calls build_identify_prompt by module-level
      name with no hook (verified: identify.py:331) — see §9 S1.

      Reuses verbatim: strip_box for strip geometry, render_marked_strip via the
      executor for Set-of-Marks, to_strip_norm for the 0-1000 boxes, VisionAdapter.ask
      for the call (which owns the schema repair retry), and validate_response with
      ``strip=<this strip>`` for id reconciliation and added-shape acceptance.

      Also mirrors the missing-id repair prompt (verified: identify.py:344-359): when
      the answer omits requested ids, one corrective call is made. Combined with
      VisionAdapter.repair_retries=1 this means a strip can cost up to THREE provider
      calls; every attempt is counted in RunStats (§9 S8).

      A VisionError never propagates: its targets become uncertain identifications and
      an error string, exactly as _run_call does (verified: identify.py:338-343).

      Returns:
          The validated result for the whole image, and the call accounting.
      """

  def flatten(result: IdentificationResult, perception: PerceptionResult) -> List[FlatDetection]:
      """Join identifications back to source-pixel boxes.

      Identification carries no box (verified: contracts.py:101-114) and
      IdentificationResult carries none either (verified: contracts.py:137-142), so the
      join is explicit (§9 S6):
        - a ``shape_id`` matching ``Slot.slot_id``  → that slot's box, ``inferred`` kept
        - a ``shape_id`` matching ``Shape.shape_id`` → that shape's box
        - an id in ``result.added``                  → the accepted added Shape's box
      Boxes are emitted as pipeline-owned ``[x1, y1, x2, y2]`` source pixels only; Nova's
      0-1000 coordinates are never exposed as the primary bbox.

      Returns:
          Rows ordered by row then left→right; an unmatched id is skipped and logged.
      """
  ```

### Module 5: CLI, perception and outputs
- **Path**: `examples/planogram/aws/nova2.py` (new), `examples/planogram/aws/README.md` (new)
- **Responsibility**: Argument parsing, Stage-1 perception (or a validated `--boxes`
  override), adapter wiring, result/annotation/`run.json` writing, exit codes.
- **Depends on**: Module 4
- **Interface Skeleton**:
  ```python
  # examples/planogram/aws/nova2.py  (new)
  async def perceive(image_bgr: np.ndarray, image_id: str, executor: CpuExecutor) -> PerceptionResult:
      """Stage-1 perception, mirroring types/ink_wall.py:181-214 (§9 S4).

      The full tail, not just three calls: propose_shapes through the executor with
      PRICE_TAG_PROFILE, group_rows, build_slots with rule=AnchorRule.TAG_BELOW_PRODUCT,
      fill_gaps=True and untagged_bottom_row=True, pipeline-owned ids via
      candidate_shape_id, and assign_membership. OCR is optional and skipped when
      rapidocr is absent (ocr_available=False).

      Returns:
          A PerceptionResult equivalent to what the production pipeline would produce.
      """

  def load_perception(path: Path, image_bgr: np.ndarray) -> PerceptionResult:
      """Deserialize a --boxes override and fail fast when it does not match the image (§9 S7).

      Pydantic validation alone is not enough: from_strip_norm trusts
      PerceptionResult.image_size (verified: slots.py:263) and annotation trusts the
      real array shape.

      Raises:
          ValueError: image_size differs from the decoded image's (width, height), or a
              box falls outside the image, or a slot's anchor_shape_id names no shape.
      """

  def annotate(image_bgr: np.ndarray, detections: Sequence[FlatDetection]) -> np.ndarray:
      """Draw each box labelled ``brand / product``; empty slots in a distinct colour.

      Picklable and synchronous — runs in the CpuExecutor, never on the event loop (§9 S5).
      """

  async def main(argv: Optional[Sequence[str]] = None) -> int:
      """Parse flags, run the cycle, write outputs.

      Flags: --image (required), --boxes, --planogram, --output (required), --model,
      --region, --aws-id, --concurrency, --no-marks, --cache-dir.

      Returns:
          0 success, 1 invalid input (missing image/planogram/credentials, bad --boxes,
          zero shapes perceived), 2 completed with errors (IdentificationResult.errors
          non-empty).
      """
  ```

---

## 4. Test Specification

The user resolved: **no automated test for the shim** ("throwaway prototype code
superseded by the real `BedrockConverseBase` image support; manual runs against live
Nova are sufficient validation"). §9 S9 contested that; §8 Q1 closed it by adopting the
*failure mode* without the *test form* — `NovaVisionClient._assert_has_image` refuses to
send a request that carries no image block, and `RunStats.image_bytes_sent` makes the
transmitted payload auditable per run. There is therefore no fake-`aioboto3` test.

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_gitignore_tracks_code_not_photos[examples/planogram/aws/nova2.py]` | Module 1 | Existing parametrized invariant test, one new row: the new example path is NOT ignored. |

### Integration Tests
| Test | Description |
|---|---|
| Manual run (not automated) | `python examples/planogram/aws/nova2.py --image <photo> --planogram examples/planogram/planogram_page1.json --output examples/planogram/results/nova_run1` against live Nova in `us-east-1`; inspect `detections.json`, `annotated.jpg`, `run.json`. |

### Test Data / Fixtures
```python
# No new fixtures. examples/planogram/tests/conftest.py is untouched.
# The transport is guarded at runtime instead (§8 Q1): _assert_has_image raises
# before the call, so a text-only vision request cannot reach Bedrock unnoticed.
```

---

## 5. Acceptance Criteria

- [ ] AC1 — `python examples/planogram/aws/nova2.py --help` exits 0 and lists every flag
      in §3 M5.
- [ ] AC2 — A live run against `us.amazon.nova-2-lite-v1:0` in `us-east-1` writes
      `detections.json`, `annotated.jpg` and `run.json` under `--output` and exits 0.
- [ ] AC3 — `detections.json` has exactly one entry per perceived target, each with a
      `bbox` in source-image pixels, an `occupancy` of `occupied`/`empty`/`unknown`, and
      `brand`/`product` present whenever `occupancy == "occupied"` and legible.
- [ ] AC4 — Every `bbox` lies inside the image bounds and, when drawn, lands on the
      product it labels in `annotated.jpg`.
- [ ] AC5 — `run.json` records the resolved model id (with geo prefix), region, prompt
      version, target count, `strips`, `calls`, `cache_hits`, `incomplete_retries`,
      `image_bytes_sent`, token counts and wall time (G5, §9 S8).
- [ ] AC6 — No file under `packages/` is modified by this feature (`git diff --name-only
      origin/dev...HEAD | grep '^packages/'` is empty) (G3).
- [ ] AC7 — `git check-ignore -q examples/planogram/aws/nova2.py` exits 1 (not ignored),
      and `git check-ignore -q examples/planogram/aws/results/x.json` exits 0 (G6).
- [ ] AC8 — `pytest examples/planogram/tests/test_plancheck_gitignore.py -v` passes,
      including the new row.
- [ ] AC9 — A `--boxes` file whose `image_size` disagrees with the image exits 1 with a
      message naming both sizes (§9 S7).
- [ ] AC10 — A run with `--planogram` pointing at a non-planogram JSON exits 1 with a
      message naming the missing `shelves` key.
- [ ] AC11 — Zero perceived shapes exits 1 and sends no provider call.
- [ ] AC12 — `ruff check examples/planogram/aws/` and `black --check --line-length 120
      examples/planogram/aws/` both pass.
- [ ] AC13 — No `requests`, `httpx`, `boto3` (sync), `print(...)` or LangChain import
      appears in `examples/planogram/aws/` (`ruff` TID251 plus review).
- [ ] AC14 — Re-running with the same `--cache-dir` issues zero provider calls and
      produces byte-identical `detections.json`.
- [ ] AC15 — A Converse request assembled without an image content block is refused by
      `_assert_has_image` before reaching Bedrock, and `run.json` reports a non-zero
      `image_bytes_sent` on every successful run (§8 Q1, §9 S9).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Every reference below was re-verified at base commit `f9d362cd5` (2026-09-23).
> All 29 anchors carried from the brainstorm verified with zero drift.

### Verified Imports

```python
# Pipeline — all confirmed to resolve
from parrot.models.detections import DetectionBox                                     # verified: identify.py:14
from parrot_pipelines.planogram.contracts import (                                    # verified: identify.py:16-25
    CycleContext, Identification, IdentificationResponse, IdentificationResult,
    ObservationSource, PerceptionResult, Shape, ShapeKind, Slot,
)
from parrot_pipelines.planogram.identification.identify import (                      # verified: identify.py:90,212
    render_marked_strip, validate_response,
)
from parrot_pipelines.planogram.identification.vision import (                        # verified: vision.py:31,100,131
    VisionAdapter, VisionError, encode_png,
)
from parrot_pipelines.planogram.backend import ResolvedBackend                        # verified: vision.py:17
from parrot_pipelines.planogram.perception import PRICE_TAG_PROFILE, propose_shapes   # verified: perception/__init__.py:3-6
from parrot_pipelines.planogram.perception.executor import CpuExecutor                # verified: perception/executor.py:17
from parrot_pipelines.planogram.perception.membership import assign_membership        # verified: membership.py:192
from parrot_pipelines.planogram.perception.ocr import read_crop                       # verified: ocr.py:73
from parrot_pipelines.planogram.perception.rows import group_rows                     # verified: rows.py:20
from parrot_pipelines.planogram.perception.slots import (                             # verified: slots.py:27,34,115,214,242,263
    AnchorRule, build_slots, candidate_shape_id, from_strip_norm, strip_box, to_strip_norm,
)

# Client
from parrot.clients.amazon.nova.client import NovaClient                              # verified: nova/client.py:34

# Third-party — already installed (aioboto3 13.2.0, botocore 1.35.36)
import aioboto3                                                                       # verified: ai-parrot-client-amazon/pyproject.toml:17
```

### Existing Class Signatures

```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py
_COMMON: FrozenSet[str] = frozenset(                                  # line 21
    {"model", "max_tokens", "temperature", "structured_output", "reference_images"})
SUPPORTED_KWARGS: Dict[str, FrozenSet[str]] = {...}                   # line 22-27 — keys: google, claude, openai ONLY

def normalise_kwargs(client_name: str, requested: Dict[str, Any]) -> Dict[str, Any]:   # line 35
    # line 52: supported = SUPPORTED_KWARGS.get(client_name, _COMMON)  ← "nova" lands here
    # drops None values; raises VisionError for keys outside KNOWN_KWARGS

def encode_png(image: np.ndarray) -> bytes: ...                       # line 100

class VisionAdapter:                                                  # line 131
    def __init__(self, client: Any, backend: ResolvedBackend, *,      # line 134
                 semaphore: asyncio.Semaphore, cache_dir: Optional[Path] = None,
                 max_tokens: int = 8192, timeout: float = 120.0,
                 repair_retries: int = 1) -> None: ...
        # line 157-161: raises VisionError when not hasattr(client, "ask_to_image")
        # line 165:     self.client_name = str(getattr(client, "client_name", "") or "").lower()
    async def ask(self, prompt: str, images: Sequence[bytes], schema: Type[T], *,     # line 173
                  stage: str, prompt_version: str,
                  system_prompt: Optional[str] = None) -> T: ...
    def _final_prompt(self, prompt, system_prompt) -> str: ...        # line 238 — folds system into prompt for "nova"
    async def _call(self, prompt, images, schema, system_prompt, stage="") -> Any:    # line 244
        # line 269-271: await self.client.ask_to_image(prompt=final_prompt, image=images[0], **kwargs)
    @staticmethod
    def _extract(message: Any, schema: Type[T]) -> T: ...             # line 278
        # line 280: reads `.structured_output` then `.output`; a str is accepted and
        #           ```/```json fences stripped before json.loads (lines 291-297)

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py
IDENTIFY_PROMPT_VERSION: str = "identify-v1"                          # line 33
IDENTIFY_STAGE: str = "identify"                                      # line 34
PixelBox = Tuple[int, int, int, int]                                  # line 35
_MARK_COLOUR = (0, 255, 0)                                            # line 40
def render_marked_strip(image: np.ndarray, strip: PixelBox,           # line 90
                        marks: List[Tuple[int, PixelBox]]) -> bytes: ...
def build_identify_prompt(targets: Sequence[Dict[str, Any]],          # line 119
                          vocabulary: Sequence[str]) -> str: ...
    # docstring line 125: "Must NOT mention a planogram or expected products."
def validate_response(response: IdentificationResponse,               # line 212
                      perception: PerceptionResult, *,
                      strip: Optional[DetectionBox],
                      next_shape_id: Callable[[], str],
                      ) -> Tuple[List[Identification], List[Shape], List[str]]: ...
async def _run_call(...) -> _CallResult: ...                          # line 316
    # line 331: prompt = build_identify_prompt(areas, vocabulary)   ← NO HOOK (§9 S1)
    # line 338-343: VisionError → uncertain targets + error string, never raised
    # line 344-359: missing-id repair prompt (a SECOND provider call)
async def identify_strips(image, perception, ctx, *, vocabulary,      # line 464
                          marks: bool = True, substrip_max_slots: int = 8
                          ) -> IdentificationResult: ...

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py
class ShapeKind(str, Enum):                                           # line 15
    PRICE_TAG, PRODUCT, BOX, FACT_TAG, ZONE, UNKNOWN
class ObservationSource(str, Enum):                                   # line 26
    CV = "cv"; LLM_ADDED = "llm_added"; LLM = "llm"; LEGACY_LLM = "legacy_llm"
class Shape(BaseModel):                                               # line 50 — "in SOURCE-image pixels"
    shape_id: str; image_id: str; kind: ShapeKind; box: DetectionBox
    row_index: Optional[int]; slot_index: Optional[int]; ocr_text: Optional[str]
    source: ObservationSource = ObservationSource.CV
class Slot(BaseModel):                                                # line 67
    slot_id: str        # "<image_id>:r<row_index>:s<slot_index>"
    image_id: str; row_index: int; slot_index: int; box: DetectionBox
    anchor_shape_id: Optional[str] = None; inferred: bool = False
class PerceptionResult(BaseModel):                                    # line 86
    image_id: str = "img0"
    image_size: Tuple[int, int] = (0, 0)      # (width, height)
    shapes: List[Shape]; slots: List[Slot]; zones: List[Shape]
    row_count: int = 0; detection_source: str = "cv"; ocr_available: bool = False
class Identification(BaseModel):                                      # line 101
    shape_id: str                                                     # line 104
    product: Optional[str]; brand: Optional[str]; text: Optional[str]  # lines 106-108
    occupancy: str = "unknown"    # "occupied"|"empty"|"unknown"       # line 110
    raw_confidence: float = Field(default=0.0, ge=0.0, le=1.0)         # line 111 — NEVER modified
    evidence: List[str]; source: ObservationSource; uncertain: bool    # lines 112-114
class AddedShape(BaseModel):                                          # line 117
    box_norm: List[int]   # [ymin, xmin, ymax, xmax], 0-1000           # line 120
class IdentificationResponse(BaseModel):                              # line 130
    existing_identifications: List[Identification]; added_shapes: List[AddedShape]
class IdentificationResult(BaseModel):                                # line 137
    image_id: str; identifications: List[Identification]
    added: List[Shape]; errors: List[str]
class CycleContext(BaseModel):                                        # line 322
    vision: Any; executor: Any; ocr: Any; output_dir: Optional[Path]; errors: List[str]

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py
class AnchorRule(str, Enum):                                          # line 27
    TAG_BELOW_PRODUCT = "tag_below_product"; SHAPE_IS_SLOT = "shape_is_slot"
def candidate_shape_id(image_id: str, candidate: ShapeCandidate) -> str: ...   # line 34
def build_slots(rows, image_size, *, image_id, rule,                  # line 115
                fill_gaps: bool = True, untagged_bottom_row: bool = False) -> List[Slot]: ...
def strip_box(slots: Sequence[Slot], image_size: Tuple[int, int],     # line 214
              pad: float = 0.04) -> DetectionBox: ...
def to_strip_norm(box: DetectionBox, strip: DetectionBox) -> List[int]: ...    # line 242
def from_strip_norm(norm: Sequence[int], strip: DetectionBox) -> DetectionBox: ...  # line 263

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/shapes.py
def propose_shapes(image: np.ndarray, profiles: Sequence[ShapeProfile], *,     # line 128
                   work_width: int = 2048) -> List[ShapeCandidate]: ...
# perception/rows.py
def group_rows(candidates: Sequence[ShapeCandidate], image_width: int, *,      # line 20
               min_row_items: int = 4, max_slope: float = 0.12) -> List[List[ShapeCandidate]]: ...
# perception/executor.py
class CpuExecutor:                                                    # line 17
    def __init__(self, max_workers: int = 2) -> None: ...             # line 26
    async def run(self, fn: Callable[..., T], *args: Any) -> T: ...   # line 62
    async def __aenter__(self) -> "CpuExecutor": ...                  # line 99
    async def __aexit__(self, *exc: Any) -> None: ...                 # line 103

# packages/ai-parrot/src/parrot/models/detections.py
class DetectionBox(BaseModel):                                        # line 37
    x1: int; y1: int; x2: int; y2: int                                # lines 39-42
    confidence: float = Field(ge=0.0, le=1.0)                         # line 43
    label: Optional[str]; ocr_text: Optional[str]                     # lines 56-60

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py
def _prepare_messages(self, prompt, files=None) -> List[Dict[str, Any]]:       # line 725
    # lines 736-745: files are logged and DROPPED — the defect this feature works around
async def get_client(self) -> Any: ...                                # line 338
async def close(self) -> None: ...                                    # line 673
# lines 300-313: credential chain — aws_id → AWS_CREDENTIALS[profile] → AWS_CREDENTIALS['default']
#   → explicit kwargs → bearer token; region: kwarg → profile.region_name →
#   BEDROCK_AWS_REGION → AWS_REGION_NAME → "us-east-1"
# line 434: return translate_bedrock_model(raw, self._region_prefix)

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/client.py
class NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration):     # line 34
    client_type: str = "nova"; client_name: str = "nova"
    _default_model: str = "nova-2-lite"; _fallback_model: str = "nova-lite"
    def __init__(self, ..., region_prefix: Optional[str] = "us", ...)  # line 93
# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/models.py
"nova-2-lite": "amazon.nova-2-lite-v1:0"                              # line 150
```

### Key Attributes & Constants
- `_COMMON` = `{model, max_tokens, temperature, structured_output, reference_images}` —
  the exact kwarg set `NovaVisionClient.ask_to_image` will receive (`vision.py:21,52`).
- `Identification.occupancy` ∈ `{"occupied", "empty", "unknown"}` (`contracts.py:110`).
- `Slot.slot_id` format `"<image_id>:r<row_index>:s<slot_index>"` (`contracts.py:69`).
- Added-shape ids are `"<image_id>:added:<n>"` (`identify.py:377-386`).
- `.gitignore:418` = `examples/planogram/*`; `.gitignore:438-441` = the `pipelines/`
  negation block this feature copies.
- Planogram JSON shape: `{"planogram": ..., "shelves": [{"shelf", "shelf_number",
  "product_count", "facing_count", "products": {"pos 1:1": {"product": "9C228AN",
  "brand": "HP", "display_name": null, ...}}}]}` (verified against
  `examples/planogram/planogram_page1.json`).
- `aioboto3` 13.2.0 / `botocore` 1.35.36 installed in `.venv`.

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `NovaVisionClient` | `VisionAdapter.__init__` | duck-type `hasattr(client, "ask_to_image")` | `vision.py:157-161` |
| `NovaVisionClient.client_name` | `VisionAdapter.client_name` | `getattr` → `normalise_kwargs` fallback to `_COMMON` | `vision.py:165`, `vision.py:52` |
| `NovaAnswer.output` | `VisionAdapter._extract` | attribute read, fenced-JSON tolerated | `vision.py:280-297` |
| `NovaVisionClient.create` | `NovaClient.__init__` / `get_client()` / `close()` | composition | `nova/client.py:93`, `bedrock.py:338,673` |
| `NovaVisionClient.resolved_model_id` | `ResolvedBackend.model` → `cache_key` | constructor arg | `backend.py:30`, `vision.py:63` |
| `identify_strips_closed_set` | `render_marked_strip` | `CpuExecutor.run(...)` | `identify.py:90`, `executor.py:62` |
| `identify_strips_closed_set` | `validate_response` | direct call, `strip=<strip box>` | `identify.py:212` |
| `identify_strips_closed_set` | `VisionAdapter.ask` | `stage=NOVA_STAGE`, `prompt_version=NOVA_PROMPT_VERSION` | `vision.py:173` |
| `flatten` | `PerceptionResult.slots` / `.shapes` / `result.added` | id join | `contracts.py:67,50,139` |
| `perceive` | `propose_shapes`/`group_rows`/`build_slots`/`assign_membership` | mirrors the reference tail | `types/ink_wall.py:181-214` |

### Does NOT Exist (Anti-Hallucination)

- ~~`BedrockConverseBase.ask_to_image`~~ / ~~`NovaClient.ask_to_image`~~ — **does not
  exist.** Implemented only at `anthropic/client.py:1329`, `google/client.py:5011`,
  `openai/client.py:1468` (plus a passthrough at `anthropic/claude_agent.py:1036`).
  This is the whole reason the shim exists.
- ~~Bedrock Converse image content blocks~~ — `bedrock.py:725-745` drops files;
  `_to_bedrock_content_block` (`bedrock.py:747`) returns `None` for unsupported types.
- ~~a `structured_output` parameter on `bedrock-runtime.converse`~~ — Converse takes
  `modelId`, `messages`, `system`, `inferenceConfig`, `toolConfig`. The Pydantic class
  must never be forwarded to AWS (§9 S2).
- ~~`SUPPORTED_KWARGS["nova"]` / `["bedrock"]` / `["amazon"]`~~ — not registered
  (`vision.py:22-27`). The `_COMMON` fallback is correct and needs **no** edit.
- ~~a prompt-builder hook on `identify_strips` / `_run_call`~~ — `build_identify_prompt`
  is called by module-level name at `identify.py:331`. There is no injection point.
- ~~`parrot_pipelines...identify.build_closed_set_prompt`~~ — no closed-set builder exists.
- ~~`IdentifyStrategy.CROPS`~~ — the enum has only `FULL_IMAGE` and `STRIPS`
  (`contracts.py:43-47`).
- ~~`Identification.box` / `Identification.bbox`~~ — `Identification` carries **no box**
  (`contracts.py:101-114`); neither does `IdentificationResult` (`contracts.py:137-142`).
- ~~`examples/planogram/aws/`~~ — the directory does not exist yet.
- ~~`common.py`, `prompt_template.txt`, `change_detection_result_format`,
  `is_bbox_valid`, `sanitize_object_list`, `visualize_boxes`~~ — upstream aws-samples
  symbols, **absent from this repository**. Do not import them.
- ~~`requests` / `httpx` / sync `boto3` / `langchain*` / `print(...)`~~ — banned by
  `.claude/rules/codebase-conventions.md` (ruff TID251).
- ~~a repo-root `parrot/` package~~ — uv workspace; sources live under `packages/<dist>/src/`.

### Edit Sites (Blueprint Anchors)

Verified against: `f9d362cd5`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `.gitignore` | MODIFY | `!examples/planogram/pipelines/README.md` | `.gitignore:441` | 1 |
| `examples/planogram/tests/test_plancheck_gitignore.py` | MODIFY | `    "examples/planogram/white_label_detector/detect_price_labels.py",` | `test_plancheck_gitignore.py:15` | 1 |
| `examples/planogram/aws/nova_vision.py` | CREATE | — | — | — |
| `examples/planogram/aws/prompt.py` | CREATE | — | — | — |
| `examples/planogram/aws/identify.py` | CREATE | — | — | — |
| `examples/planogram/aws/nova2.py` | CREATE | — | — | — |
| `examples/planogram/aws/README.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first: `aioboto3` only, never sync `boto3`, never `requests`/`httpx`.
- **Every OpenCV and file-I/O operation goes through `CpuExecutor.run`** — image decode,
  Set-of-Marks rendering, annotation, PNG/JPEG encoding. `cv2.imread`/`imwrite` must
  never be called directly inside a coroutine (§9 S5; reference `ink_wall.py:181,235`).
- `self.logger` / module logger, never `print`.
- Google-style docstrings and strict type hints on every function and class.
- Pydantic v2 for every structured payload (`PlanogramVocabulary`, `FlatDetection`,
  `RunStats`).
- `black --line-length 120`; `ruff check` is the gate.
- Reuse pipeline helpers by their **public** names only. Do not import
  underscore-prefixed pipeline internals (`_targets`, `_plan_chunks`, `_area`,
  `_id_allocator`, `_finalise`) — the example supplies its own trivial equivalents.

### Known Risks / Gotchas
- **Nova 2 Lite has no in-region access in any region.** A bare
  `amazon.nova-2-lite-v1:0` fails with an access error. `NovaClient` defaults
  `region_prefix="us"`; the shim asserts the resolved id carries a geo/global prefix and
  raises a message naming the requirement rather than surfacing a raw AWS error.
- **Cache identity.** `cache_key` (`vision.py:63`) keys on `ResolvedBackend.as_string()`,
  so `nova:nova-2-lite` and `nova:us.amazon.nova-2-lite-v1:0` would be different entries
  for the same route. Always construct `ResolvedBackend` from
  `NovaVisionClient.resolved_model_id` (§9 S10).
- **Prompt-version collision.** The closed-set prompt must use `NOVA_PROMPT_VERSION`
  and `NOVA_STAGE`, never `"identify-v1"`/`"identify"` (`identify.py:33-34`), or a
  cached open-set answer could be served for a closed-set prompt.
- **Up to three provider calls per strip** — `VisionAdapter.repair_retries=1` for a
  schema-invalid answer, plus the missing-id repair prompt. Material to the cost
  objective; `RunStats` must count every attempt (§9 S8).
- **`--boxes` staleness.** `from_strip_norm` trusts `PerceptionResult.image_size`
  (`slots.py:263`) and annotation trusts the real array shape. A stale override silently
  misplaces every box, so `load_perception` fails fast on any mismatch (§9 S7).
- **Perception must mirror the full ink-wall tail.** Three bare calls do not produce an
  equivalent `PerceptionResult` — pipeline-owned ids, gap filling, the synthesized
  bottom row and membership assignment all matter to target selection (§9 S4).
- **The model may return fewer entries than boxes sent.** `validate_response` backfills
  them as `occupancy="unknown"`, `uncertain=True`; hallucinated ids are dropped and
  recorded as errors. Never treat a short answer as a failure.
- **Strips can exceed the model's practical attention.** Cap targets per call at 8, as
  `identify_strips` does; split longer rows into sub-strips.
- **A text-only Converse call fails silently.** Bedrock accepts a request with no image
  block and Nova answers from the prompt alone, producing well-formed JSON with invented
  identities — an experiment that looks successful and measures nothing. `ask_to_image`
  therefore refuses to send a request whose assembled blocks contain no image, and
  `RunStats.image_bytes_sent` makes the transmitted payload auditable (§8 Q1, §9 S9).
  This guard is the one piece of the shim that must survive the lift into
  `BedrockConverseBase`.
- **`examples/planogram/` is git-ignored by default.** Without M1's negation rules, new
  files silently never reach a commit (§9 S11).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `aioboto3` | `>=13.2.0` | Async `bedrock-runtime.converse`. Already declared at `ai-parrot-client-amazon/pyproject.toml:17`; installed 13.2.0. **No new dependency.** |
| `opencv-python` | already present | Perception, Set-of-Marks, annotation. |
| `numpy` | already present | BGR arrays. |
| `pydantic` | v2, already present | All structured payloads. |

---

## 8. Open Questions

- [x] Flow type and base branch — *Resolved in brainstorm*: `type: feature`, `base_branch: dev`.
- [x] Standalone example vs. fixing the client first — *Resolved in brainstorm*: ship the example now; `BedrockConverseBase` image support is a separate follow-up feature.
- [x] Where the boxes come from — *Resolved in brainstorm*: run Stage-1 perception live, with `--boxes <PerceptionResult.json>` to override for reproducible reruns.
- [x] Output JSON shape — *Resolved in brainstorm*: flat `{bbox, brand, product, occupancy, …}` in source-image pixels, not the `Identification` contract.
- [x] How boxes are presented to Nova — *Resolved in brainstorm*: Set-of-Marks numbered overlay plus the boxes JSON, reusing `render_marked_strip`.
- [x] Open-set or closed-set prompting — *Resolved in brainstorm*: closed-set, vocabulary built from the planogram.
- [x] Behaviour on a mismatched answer — *Resolved in brainstorm*: reconcile ids against those sent and retry once on an invalid answer.
- [x] Self-contained vs. reusing pipeline helpers — *Resolved in brainstorm*: reuse the pipeline helpers; write only the Nova transport locally.
- [x] Result destination — *Resolved in brainstorm*: `--output <dir>` with `detections.json` and an annotated image.
- [x] Model, region and credentials — *Resolved in brainstorm*: `parrot.conf` `AWS_CREDENTIALS` resolution, default model `us.amazon.nova-2-lite-v1:0`.
- [x] Closed-set prompt location — *Resolved in brainstorm*: example-local permanently; the pipeline's open-set contract stays untouched. Promotion would be a separate follow-up.
- [x] Vocabulary source fields — *Resolved in brainstorm*: `product` + `brand` only; descriptor fields are deliberately excluded to keep prompts short.
- [x] Region and model access — *Resolved in brainstorm*: `us-east-1`, Nova 2 Lite access already granted; the default `us.amazon.nova-2-lite-v1:0` is correct there.
- [x] Fixture test for the shim — *Resolved in brainstorm*: no test; the shim is throwaway prototype code, manual live runs suffice. **Contested by §9 S9 — see Q1.**
- [x] Cost/latency target — *Resolved in brainstorm*: no hard target; record cost and latency in `run.json` and decide qualitatively alongside accuracy.
- [x] **Q1** — The design-research seat argues the Converse transport is the highest-risk
  code in this feature and that a fake-`aioboto3` test asserting the exact payload would
  catch a silently text-only request *before* a live experiment produces numbers that
  look real but are not. This contradicts the resolved "no test" answer. Keep "no test",
  or add this one transport test? — *Owner: Jesus Lara*: **runtime self-check, no test
  file.** `ask_to_image` asserts its own assembled request carries an image content block
  and refuses to send a text-only vision call; `RunStats.image_bytes_sent` records the
  image payload actually transmitted. This closes the exact failure the reviewer named
  while honouring "no test files for throwaway prototype code" — and, unlike a test, the
  guard travels with the shim when it is lifted into `BedrockConverseBase`.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the accepted brainstorm (never
> over this spec). Model: `gpt-5.6-luna` (codex-cli 0.155.1, `model_reasoning_effort=high`)
> · Status: completed · Transcript: `sdd/state/FEAT-592/design_research/`
> All 18 `affected_paths` passed repository containment and `test -e`; no suggestion was
> rejected for unverifiable evidence.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Resolve the closed-set prompt injection contradiction (architecture) | CONFIRM | Verified: `_run_call` calls `build_identify_prompt` by module-level name (`identify.py:331`) — no hook exists. The example owns its per-strip loop; no monkeypatching, no pipeline edit. | §2 Overview, §3 M4, §7 |
| S2 | Specify how the shim consumes `structured_output` (api) | CONFIRM | Verified: `VisionAdapter._call` passes the Pydantic class (`vision.py:257-261`); Converse has no such parameter. The shim renders the schema into the prompt and returns text. | §3 M2, §6 Does-NOT-Exist |
| S3 | Reuse `NovaClient` for credentials and async client lifetime (architecture) | CONFIRM | Verified: credential chain (`bedrock.py:300-313`), `get_client()` (338), `close()` (673), `translate_bedrock_model` (434) already exist. Removes a whole duplicated-configuration module. | §2 Overview, §3 M2 |
| S4 | Match the complete InkWall perception tail (architecture) | CONFIRM | Verified: `ink_wall.py:181-214` also does `candidate_shape_id`, `assign_membership`, `fill_gaps=True`, `untagged_bottom_row=True`. Three bare calls are not equivalent. | §3 M5, §7 |
| S5 | Keep OpenCV and file I/O off the event loop (risk) | CONFIRM | Verified: `ink_wall.py:181,235` routes CPU work through `ctx.executor.run`. Async-first applies to examples too. | §3 M4/M5, §7 Patterns |
| S6 | Define the flattening join and bbox convention explicitly (api) | CONFIRM | Verified: `Identification` carries no box (`contracts.py:101-114`) and `IdentificationResult` none either (137-142). Without an explicit join the flat output cannot be produced. | §2 Data Models, §3 M4 |
| S7 | Validate `--boxes` against the decoded image (testing) | CONFIRM | Verified: `from_strip_norm` trusts `image_size` (`slots.py:263`). Adopted as runtime fail-fast validation (AC9); the automated-test half folds into Q1. | §3 M5, §5 AC9, §7 |
| S8 | Make the real retry and cost envelope visible (risk) | CONFIRM | Verified: two independent repair paths — `repair_retries` (`vision.py:143`) and the missing-id retry (`identify.py:344-359`) — so one strip can cost three calls. Material to the cost objective. | §2 Data Models, §5 AC5, §7 |
| S9 | Test the exact Converse payload without AWS (testing) | CONFIRM (variant) | Escalated to the user as §8 Q1, then resolved: the *failure mode* is adopted, the *test form* is declined. A runtime guard in `ask_to_image` refuses to send a request carrying no image block, and `RunStats.image_bytes_sent` makes the transmitted payload visible per run — closing the silently-text-only hole without a test file for code that is explicitly throwaway. The guard also survives the lift into `BedrockConverseBase`, which a test under `examples/` would not. | §3 M2, §2 Data Models, §5 AC15, §7, §8 Q1 |
| S10 | Canonicalize the resolved Nova model before caching (api) | CONFIRM | Verified: `models.py:150` maps the alias while `region_prefix="us"` (`nova/client.py:93`) adds the profile; `cache_key` keys on the backend string (`vision.py:63`). | §3 M2, §7 |
| S11 | Make ignored example files reliably trackable (risk) | CONFIRM | Verified: `.gitignore:418` ignores the tree and the repo convention is negation rules (`.gitignore:438-441`), not `git add -f`. Corrects the brainstorm. | §2 Overview, §3 M1, §5 AC7 |

Summary: **11** confirmed (one as a variant) · **0** rejected · **0** escalated — §8 Q1 closed by the user.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for the whole spec —
  `.claude/worktrees/feat-FEAT-592-nova-image-planogram`, cut from `origin/dev`. The
  `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  ```
  M1 (.gitignore)            ← independent, no edge to anything
  M2 (nova_vision.py)        ← independent of M3
  M3 (prompt.py)             ← M2, for _schema_instruction's output contract only
  M4 (identify.py)           ← M2 (VisionAdapter is fed a NovaVisionClient),
                                M3 (build_nova_identify_prompt, NOVA_PROMPT_VERSION)
  M5 (nova2.py, README)      ← M4 (identify_strips_closed_set, flatten, FlatDetection)
  ```
  M1 and M2 have no edge between them and are expected to run concurrently. M3's edge to
  M2 is weak (a string contract); if M2's `_schema_instruction` signature is fixed first,
  M3 can start in parallel too.
- **Shared files**: none. Every module owns files no other module touches — M1 owns
  `.gitignore` + the gitignore test, M2–M5 each own one new file (M5 owns two).
- **Exclusive resources**: none. No extension rebuild, no lockfile change, no migration,
  no dependency addition (`aioboto3` is already declared and installed).
- **Cross-feature dependencies**: none. This feature modifies nothing under `packages/`,
  so it cannot conflict with in-flight work on FEAT-574 (`new-planogram-pipeline`) or
  FEAT-565 (`new-planogram-compliance-algo`) at the file level. Note that
  `examples/planogram/pipelines/` has uncommitted work on `dev` — this feature must not
  touch those paths.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-23 | Jesus Lara | Initial draft from `proposals/nova-image-planogram.brainstorm.md` (Option A), with 10 design-research suggestions folded in and 1 escalated. |
| 0.2 | 2026-09-23 | Jesus Lara | §8 Q1 resolved: the Converse transport is guarded at runtime (`_assert_has_image` + `RunStats.image_bytes_sent`) instead of by a fake-`aioboto3` test. S9 → CONFIRM (variant); no open questions remain. |
