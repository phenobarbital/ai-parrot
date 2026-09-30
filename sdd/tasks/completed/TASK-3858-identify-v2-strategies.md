# TASK-3858: identify-v2-ocr prompt, zone targets, reference attachments and slots strategy

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3857, TASK-3854
**Assigned-to**: unassigned

---

## Context

Spec §2 **Stage 2** (prompt and strategies paragraphs) and §3 **Module 3** skeletons
`build_identify_prompt(..., *, reference_labels=())` and `identify_slots(...)`.

`identification/identify.py` is the shared stage-2 engine. Today it:
- uses prompt version `identify-v1` (`identify.py:33`) and a prompt without the OCR-anchored
  occupancy recipe that the Nova example proved (`examples/planogram/aws/prompt.py:66`);
- ignores zones whenever slots exist (`_targets`, `identify.py:63-66`, spec §6 Corrections);
- sends ONE image per call (`_run_call`, `identify.py:363-365`) — references never reach the model;
- supports only `full_image` and `strips`.

This task upgrades the engine in place, keeping `identify_full_image` / `identify_strips`
signatures and the Nova example's public APIs (`render_marked_strip`, `validate_response`)
unchanged, and adds the opt-in `slots` strategy (user-confirmed, spec §8).

---

## Scope

- Bump `IDENTIFY_PROMPT_VERSION` to `"identify-v2-ocr"`.
- Rewrite `build_identify_prompt` as the provider-neutral v2 prompt; add keyword-only
  `reference_labels: Sequence[str] = ()`; two-positional-argument callers keep working.
- Give `_targets` a keyword-only `include_zones: bool = False`; zones are identification targets
  when `ctx.layout is not None` (the profile-driven cycle). De-duplicate by id.
- Use the perception's own-box OCR readings (`PerceptionResult.ocr_readings`, TASK-3854) in the
  AREAS JSON (`ocr_text`, `ocr_confidence`, separate `tag_text` for a slot's anchor tag).
- In `_run_call`: select references per call with `select_references` (TASK-3857), send
  `[png, *reference_pngs]` on the initial AND the repair call, pass `reference_labels`, and
  reject a returned `Identification.reference_id` that was not offered in that call.
- Route validation through a private `_validate(...)` that takes the explicit target list;
  `validate_response` keeps its exact signature and behaviour by delegating to it.
- Allow profile-declared custom descriptor names in `_check_vocabulary`
  (built-in `Descriptors` fields ∪ `ctx.layout.descriptor_fields`).
- Add `identify_slots(image, perception, ctx, *, vocabulary, marks=True)`: one padded crop call per
  target, concurrent, failure-isolated, coordinates remapped to source pixels.
- Extend `test_identify.py`.

**NOT in scope**:
- OCR reading itself and the reference bank — TASK-3857 (`targets.py`, `references.py`).
- Choosing the strategy from the profile, running OCR before identification, rule evidence —
  TASK-3859 (`stages/identify.py`, `identification/evidence.py`).
- `verify.py` evidence gating — TASK-3861. Type hooks — TASK-3864…TASK-3869.
- Any edit to `examples/planogram/aws/*` (the Nova shim/prompt stay untouched).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py` | MODIFY | v2 prompt, zone targets, own-box OCR areas, references, `_validate`, `identify_slots` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_identify.py` | MODIFY | new tests for the above; existing tests keep passing |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# already imported at the top of identify.py (verified :5-29) — reuse, do not duplicate
import asyncio, json, logging, math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union
from parrot.models.detections import DetectionBox                                      # :14
from parrot_pipelines.planogram.comparison.definition import Descriptors               # :15
from parrot_pipelines.planogram.contracts import (CycleContext, Identification, IdentificationResponse,
    IdentificationResult, ObservationSource, PerceptionResult, Shape, Slot)             # :16-25
from parrot_pipelines.planogram.grid.merger import _compute_iou                        # :26 (KEEP)
from parrot_pipelines.planogram.identification.vision import VisionError, encode_png   # :27
from parrot_pipelines.planogram.perception.membership import assign_membership, usable_shapes  # :28
from parrot_pipelines.planogram.perception.slots import from_strip_norm, strip_box, to_strip_norm  # :29

# to ADD
from parrot_pipelines.planogram.contracts import ShapeKind                              # contracts.py:15
from parrot_pipelines.planogram.identification.references import select_references      # TASK-3857
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py
IDENTIFY_PROMPT_VERSION: str = "identify-v1"                                     # :33 (anchor, count 1)
IDENTIFY_STAGE: str = "identify"                                                 # :34
def _target_id(target: Target) -> str                                            # :51
def _order_key(target: Target) -> Tuple[int, int, int, str]                      # :56 (row None sorts last)
def _targets(perception: PerceptionResult) -> List[Target]                       # :63-66
def _plan_chunks(targets: Sequence[Any], substrip_max_slots: int) -> List[List[Any]]   # :69 (row None -> -1)
def render_marked_strip(image: np.ndarray, strip: PixelBox, marks: List[Tuple[int, PixelBox]]) -> bytes  # :115 PUBLIC, unchanged
def build_identify_prompt(targets: Sequence[Dict[str, Any]], vocabulary: Sequence[str]) -> str   # :148-184
def _uncertain(target_id, image_id, source, reason) -> Identification           # :187
def _source_for(perception: PerceptionResult) -> ObservationSource              # :200
def _inside(box: DetectionBox, strip: DetectionBox) -> bool                      # :205
def validate_response(response: IdentificationResponse, perception: PerceptionResult, *,
                      strip: Optional[DetectionBox], next_shape_id: Callable[[], str]
                      ) -> Tuple[List[Identification], List[Shape], List[str]]   # :241-326 PUBLIC, unchanged
    # body line 264: targets = [t for t in _targets(perception) if strip is None or _inside(t.box, strip)]
def _area(target, strip, mark, perception) -> Dict[str, Any]                     # :329-337
def _as_tuple(box: DetectionBox) -> PixelBox                                     # :340
async def _run_call(image, targets, strip, perception, ctx, *, vocabulary, marks, next_shape_id,
                    full_image: bool = False) -> _CallResult                     # :345-402
    # :360 prompt = build_identify_prompt(areas, vocabulary)
    # :363-366 png = await ctx.executor.run(render_marked_strip, ...); ctx.vision.ask(prompt, [png], ...)
    # :375-390 one missing-id repair call with the same [png]
def _id_allocator(perception) -> Callable[[], str]                               # :405
def _finalise(perception, ctx, results) -> IdentificationResult                  # :416-451 (uses _targets at :437)
def _check_vocabulary(vocabulary: Sequence[str]) -> None                         # :454-458
async def identify_full_image(image, perception, ctx, *, vocabulary) -> IdentificationResult   # :461-490
async def identify_strips(image, perception, ctx, *, vocabulary, marks: bool = True,
                          substrip_max_slots: int = 8) -> IdentificationResult   # :493-533

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py
def strip_box(slots: Sequence[Slot], image_size: Tuple[int, int], pad: float = 0.04) -> DetectionBox   # :214 (duck-typed .box)
def to_strip_norm(box: DetectionBox, strip: DetectionBox) -> List[int]           # :240
def from_strip_norm(norm: Sequence[int], strip: DetectionBox) -> DetectionBox    # :260

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py
async def ask(self, prompt: str, images: Sequence[bytes], schema, *, stage: str, prompt_version: str,
              system_prompt=None)                                                # :173; images[1:] -> reference_images (:260)

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/verify.py
def crop_and_encode(image, box, pad: float = 0.08) -> bytes                      # :132 (source of the 0.08 pad convention)
```

### Symbols created by dependency tasks (not yet on dev)
```python
# TASK-3854 — contracts.py
class IdentifyStrategy(str, Enum): FULL_IMAGE = "full_image"; STRIPS = "strips"; SLOTS = "slots"
class OcrReading(BaseModel): text: str = ""; confidence: float = 0.0
class ReferenceImage(BaseModel): label: str; image: bytes; catalog_key: str; brand: str | None = None
# PerceptionResult.ocr_readings: dict[str, OcrReading]      (default {})
# Identification.reference_id: str | None = None
# CycleContext.layout: Any = None ; CycleContext.reference_bank: list[ReferenceImage]
# TASK-3855 — layout.py: LayoutProfile.references (ReferencePolicy), .descriptor_fields: list[str]
# TASK-3857 — identification/references.py
def select_references(bank: Sequence[ReferenceImage], readings: Mapping[str, OcrReading],
                      policy: ReferencePolicy) -> tuple[list[ReferenceImage], list[str]]
```

### Does NOT Exist
- ~~`identify_slots`~~ / ~~`IdentifyStrategy.SLOTS`~~ — added here / by TASK-3854.
- ~~`reference_labels` parameter~~ — added here (keyword-only).
- ~~`_validate`~~ — new private helper added here.
- ~~a diagnostics field on `IdentificationResult`~~ — reference diagnostics go into the call's `errors` list (see Notes).
- ~~`ReferenceImage.catalog_key` in prompts~~ — never send catalogue keys; labels only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_identify.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py#build_identify_prompt",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py#validate_response",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py#render_marked_strip",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py#_targets",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py#_area",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py#_run_call",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py#_finalise",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py#_check_vocabulary",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py#identify_full_image",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py#identify_strips",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py#strip_box",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py#VisionAdapter.ask"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Prompt wording: promote `examples/planogram/aws/prompt.py:66-126` (independent per-area
  judgment, visual definition of occupied vs empty, OCR is not evidence of emptiness, printed code
  reading) — but DROP its `KNOWN BRANDS` catalogue and its `schema_instruction` (spec §2: "do not
  copy its SKU catalogue or provider-specific schema string").
- Repair: keep the single missing-id repair exactly as today (`identify.py:372-390`); only the
  image list and prompt change.

### Key Constraints
- **No expectation leaks** (AC7): the prompt must not contain the words `planogram` or `expected`
  (existing test `test_prompt_has_ocr_text_and_vocabulary_not_products` asserts both), no product
  names, no catalogue keys. Reference prompt text names only labels (`ref-0001`) and says they
  are look-alike aids, not placement instructions.
- **Backwards compatibility**: `validate_response`, `render_marked_strip`, `identify_full_image`,
  `identify_strips` keep their signatures. With `ctx.layout is None` and empty
  `perception.ocr_readings`, the AREAS JSON is byte-identical to today's (existing tests pin this);
  only the instruction text and version change.
- **Zones as targets** only when `ctx.layout is not None`: legacy callers (bare `CycleContext`) keep
  today's target counts, so `test_full_image_makes_one_call` (6 ids) stays green. Zones have
  `row_index=None`, so `_order_key` puts them last and `_plan_chunks` groups them into their own
  call (row -1) — that is intended.
- **Own-box OCR in AREAS** (spec §2): when `perception.ocr_readings` is non-empty, `ocr_text` /
  `ocr_confidence` come from `ocr_readings[<target id>]`; a slot's anchor tag text goes to a
  separate `tag_text` key (from `ocr_readings[anchor]`, else the anchor shape's `ocr_text`).
  Missing reading ⇒ `ocr_text: null`, never the tag's text.
- **References**: selection per call from `ctx.reference_bank` with the call's own readings; the
  same `images` list is used for the repair call. `reference_id` not in this call's labels ⇒ set to
  `None` + error `"<image_id>: unknown reference_id <rid> for <shape_id>"`. Never change
  `product`, `text`, `uncertain` or `raw_confidence` because of a reference (spec: "A reference
  match does not overwrite contradictory printed text or turn an uncertain observation into a
  strict match"). Do not copy the catalogue key into `evidence` — `resolve_identity` reads
  evidence lines and would turn a reference into an identifier match.
- **Reference diagnostics**: messages returned by `select_references` that start with
  `"references: selected"` are logged at INFO only; every other diagnostic (omitted/capped,
  fallback, disabled-with-bank) is appended to that call's errors as `"<image_id>: <message>"`
  (AC6 "missing/capped references are reported"). The spec defines no dedicated sink.
- **Slots strategy**: `strip = strip_box([target], perception.image_size, pad=SLOT_CROP_PAD)` with
  `SLOT_CROP_PAD = 0.08` (same padding convention as `verify.crop_and_encode`), then `_run_call`
  with `full_image=False` so `validate_response`'s strip mapping returns additions in source pixels.
  Calls run concurrently with `asyncio.gather`; the adapter semaphore bounds provider concurrency.
- Cancellation propagates: never catch `asyncio.CancelledError` / `BaseException`.

### References in Codebase
- `examples/planogram/aws/prompt.py:66-126` — v2 prompt recipe (read only)
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/verify.py:132` — padding convention
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py:173-260` — how `images[1:]` become reference images

---

## Implementation Blueprint

### Steps (in order)
1. Confirm TASK-3854 / TASK-3857 symbols exist (`grep -n "SLOTS\|ocr_readings\|reference_id\|reference_bank" .../contracts.py`, `grep -n "def select_references" .../references.py`) — *why*: every block below uses them; STOP if missing.
2. Bump the version constant and add `SLOT_CROP_PAD` + imports — *why*: the v2 prompt must invalidate v1 cache entries (version is part of the cache key, `vision.py:204`).
3. Replace `_targets`, add `_include_zones` — *why*: spec §6 Corrections (zones ignored when slots exist).
4. Replace `build_identify_prompt` — *why*: AC6 default v2 prompt.
5. Split `validate_response` into `_validate` + thin wrapper — *why*: zone targets must be "known" in the cycle path without changing the public signature.
6. Replace `_area`, then `_run_call` — *why*: own-box OCR in AREAS; references on initial and repair calls.
7. Thread `include_zones` through `_finalise`, `identify_full_image`, `identify_strips`; relax `_check_vocabulary` — *why*: consistent ordering and custom descriptor fields.
8. Append `identify_slots` — *why*: user-confirmed opt-in strategy.
9. Extend `test_identify.py` and run the Validation Commands — *why*: AC6/AC7 regression coverage.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py` (MODIFY) — version + imports
```python
# occurrences: 1 (verified: grep -Fxc 'IDENTIFY_PROMPT_VERSION: str = "identify-v1"' identify.py)
# REPLACE line 33 (verified: identify.py:33) with:
IDENTIFY_PROMPT_VERSION: str = "identify-v2-ocr"
# AFTER — insert below `DUPLICATE_IOU: float = 0.5` (verified: identify.py:35, count 1):
SLOT_CROP_PAD: float = 0.08  # per-slot crop padding; same convention as verify.crop_and_encode (verify.py:132)
# Imports: add ShapeKind to the contracts import block (:16-25) and, below line 27:
from parrot_pipelines.planogram.identification.references import select_references
```
**Why**: the version string is part of the vision cache key, so v1 answers are never replayed for
the v2 prompt.

### `identify.py` (MODIFY) — `_targets`
```python
# occurrences: 1 (verified: grep -Fxc 'def _targets(perception: PerceptionResult) -> List[Target]:' identify.py)
# REPLACE lines 63-66 (verified: identify.py:63-66) with:
def _targets(perception: PerceptionResult, *, include_zones: bool = False) -> List[Target]:
    """Slots when perception produced any, otherwise the on-fixture shapes; plus zones when requested."""
    targets: List[Target] = list(perception.slots) if perception.slots else list(usable_shapes(perception.shapes))
    if include_zones:
        # FILL IN: append perception.zones whose shape_id is not already a target id (de-dup, first wins);
        #   when there are no slots, drop ShapeKind.ZONE shapes from the usable list first so a zone is never twice
        pass
    return sorted(targets, key=_order_key)


def _include_zones(ctx: CycleContext) -> bool:
    """Zones are identification targets only in the profile-driven cycle (legacy callers keep their counts)."""
    return ctx.layout is not None
```

### `identify.py` (MODIFY) — `build_identify_prompt`
```python
# occurrences: 1 (verified: grep -Fxc 'def build_identify_prompt(targets: Sequence[Dict[str, Any]], vocabulary: Sequence[str]) -> str:' identify.py)
# REPLACE lines 148-184 (verified: identify.py:148-184) with:
def build_identify_prompt(
    targets: Sequence[Dict[str, Any]], vocabulary: Sequence[str], *, reference_labels: Sequence[str] = ()
) -> str:
    """Build provider-neutral identify-v2-ocr instructions and own-area OCR/confidence.

    Args:
        targets: ``{"id", "mark", "box_2d", "ocr_text"[, "ocr_confidence", "tag_text"]}`` per area.
        vocabulary: Descriptor field names to report (names only, never values).
        reference_labels: Opaque labels of the reference images attached after the main image, in order.

    Returns:
        The prompt text. Never mentions a planogram, an expected product or a catalogue key.
    """
    areas = json.dumps(list(targets), separators=(",", ":"), ensure_ascii=False)
    fields = ", ".join(vocabulary) if vocabulary else "(none)"
    # FILL IN: compose the v2 instruction text. MUST keep: "You are analysing a retail shelf image", the
    #   AREAS contract sentence, one entry per area with shape_id == id, per-area independent judgment,
    #   occupancy definition (package body visible incl. dark/tilted/glare/side view = occupied; only backing,
    #   hook, divider, price tag or fixture parts = empty; unknown only when unreadable), "ocr_text is NOT
    #   evidence of emptiness", read the printed product code into text/product (corrected from ocr_text),
    #   brand from the visible logo, the descriptor sentence ending with f"{fields}." (existing test asserts
    #   "family, colors"), raw_confidence 0..1 also for empty areas, one-sentence evidence, "use null when not
    #   legible — do not guess", added_shapes box_norm rule, then f"AREAS: {areas}".
    #   When reference_labels: one paragraph naming the labels in order, saying they only show what some
    #   catalogue items look like (not what belongs in any area), reference_id = matching label or null, and
    #   printed text wins over a reference. Words "planogram"/"expected" must not appear — bounded by AC6, AC7
    raise NotImplementedError
```
**Why**: spec §3 fixes the signature (keyword-only addition keeps two-positional callers working);
§2 fixes the content rules.

### `identify.py` (MODIFY) — `_validate` + `validate_response` wrapper
```python
# occurrences: 1 (verified: grep -Fxc 'def validate_response(' identify.py) — definition at identify.py:241
# REPLACE the body line 264 (verified: identify.py:264)
#     targets = [t for t in _targets(perception) if strip is None or _inside(t.box, strip)]
# by moving lines 262-326 into a new private function placed ABOVE validate_response:
def _validate(
    response: IdentificationResponse,
    perception: PerceptionResult,
    candidates: Sequence[Target],
    *,
    strip: Optional[DetectionBox],
    next_shape_id: Callable[[], str],
) -> Tuple[List[Identification], List[Shape], List[str]]:
    """``validate_response`` with an explicit candidate target list (cycle path may include zones)."""
    width, height = perception.image_size
    frame = strip or DetectionBox(x1=0, y1=0, x2=width, y2=height, confidence=1.0)
    targets = [t for t in candidates if strip is None or _inside(t.box, strip)]
    # FILL IN: the remainder is lines 265-326 of today's validate_response, moved verbatim
    raise NotImplementedError
# ...and validate_response's body becomes exactly:
#     return _validate(response, perception, _targets(perception), strip=strip, next_shape_id=next_shape_id)
```
**Why**: the Nova example imports `validate_response` (`examples/planogram/aws/identify.py:24`);
its signature and behaviour must not change (spec §7), yet zone ids must be known in the cycle.

### `identify.py` (MODIFY) — `_area`
```python
# occurrences: 1 (verified: grep -Fxc 'def _area(target: Target, strip: DetectionBox, mark: Optional[int], perception: PerceptionResult) -> Dict[str, Any]:' identify.py)
# REPLACE lines 329-337 (verified: identify.py:329-337) with:
def _area(target: Target, strip: DetectionBox, mark: Optional[int], perception: PerceptionResult) -> Dict[str, Any]:
    """Structured-input entry of one target; own-box OCR readings win when the perception carries them."""
    readings = perception.ocr_readings
    if not readings:
        # FILL IN: today's lines 331-337 verbatim (legacy AREAS dict — byte-identical for old callers)
        raise NotImplementedError
    own = readings.get(_target_id(target))
    area: Dict[str, Any] = {
        "id": _target_id(target),
        "mark": mark,
        "box_2d": to_strip_norm(target.box, strip),
        "ocr_text": (own.text or None) if own else None,
        "ocr_confidence": own.confidence if own and own.text else None,
    }
    # FILL IN: for a Slot with anchor_shape_id add "tag_text" = readings[anchor].text or the anchor Shape's
    #   ocr_text (None when neither) — NEVER copy it into "ocr_text" — bounded by AC5
    return area
```

### `identify.py` (MODIFY) — `_run_call`
```python
# occurrences: 1 (verified: grep -Fxc 'async def _run_call(' identify.py) — definition at identify.py:345
# REPLACE lines 345-402 (verified: identify.py:345-402). New signature adds keyword-only include_zones:
async def _run_call(image, targets, strip, perception, ctx, *, vocabulary, marks, next_shape_id,
                    full_image: bool = False, include_zones: bool = False) -> _CallResult:
    """One LLM call for ``targets`` (+ selected references). VisionError ⇒ targets uncertain + one error."""
    mark_list = [(n, _as_tuple(t.box)) for n, t in enumerate(targets, start=1)] if marks else []
    areas = [_area(t, strip, n if marks else None, perception) for n, t in enumerate(targets, start=1)]
    call_readings = {k: v for k, v in perception.ocr_readings.items() if k in {_target_id(t) for t in targets}}
    policy = ctx.layout.references if ctx.layout is not None else None
    references, diagnostics = select_references(ctx.reference_bank, call_readings, policy) if policy else ([], [])
    labels = [r.label for r in references]
    prompt = build_identify_prompt(areas, vocabulary, reference_labels=labels)
    # FILL IN: png = render_marked_strip via ctx.executor (as today :363); images = [png, *(r.image for r in references)];
    #   initial ask with `images`; on VisionError return today's uncertain triple (:367-371);
    #   missing-id repair once with the SAME `images` (:372-390);
    #   idents, added, errors = _validate(answer, perception, _targets(perception, include_zones=include_zones),
    #                                     strip=None if full_image else strip, next_shape_id=next_shape_id);
    #   reject reference_id not in `labels` (see Notes); prepend non-"selected" diagnostics as
    #   f"{perception.image_id}: {msg}"; keep today's final-missing error and own-id filter (:394-402) — bounded by AC6, AC7, AC12
    raise NotImplementedError
```
**Why**: spec §2 "Both initial and repair calls receive identical reference attachments";
`VisionAdapter.ask` forwards `images[1:]` as reference images (`vision.py:260`).

### `identify.py` (MODIFY) — `_finalise`, `_check_vocabulary`, public strategies
```python
# _finalise (verified: identify.py:416, count 1 for 'def _finalise(perception: PerceptionResult, ctx: CycleContext, results: Sequence[_CallResult]) -> IdentificationResult:'):
#   add keyword-only `include_zones: bool = False` and use `_targets(perception, include_zones=include_zones)` at :437.
# _check_vocabulary (verified: identify.py:454-458): new signature
def _check_vocabulary(vocabulary: Sequence[str], extra: Sequence[str] = ()) -> None:
    """ValueError when a name is neither a Descriptors field nor a profile-declared custom field."""
    allowed = set(Descriptors.model_fields) | set(extra)
    unknown = [name for name in vocabulary if name not in allowed]
    if unknown:
        raise ValueError(f"unknown descriptor fields in vocabulary: {unknown}")
# identify_full_image (:461) and identify_strips (:493): signatures UNCHANGED. In each body:
#   extra = ctx.layout.descriptor_fields if ctx.layout is not None else ()
#   _check_vocabulary(vocabulary, extra); zones = _include_zones(ctx)
#   targets from _targets(perception, include_zones=zones); pass include_zones=zones to every _run_call and _finalise.
```

### `identify.py` (MODIFY) — `identify_slots` (append at end of file, after `identify_strips`, verified: identify.py:533 is the last line)
```python
async def identify_slots(
    image: np.ndarray,
    perception: PerceptionResult,
    ctx: CycleContext,
    *,
    vocabulary: Sequence[str],
    marks: bool = True,
) -> IdentificationResult:
    """One bounded crop call per target; source-coordinate validation and isolated errors.

    Args:
        image: Untouched full-resolution BGR image.
        perception: Stage-1 output of the image.
        ctx: Per-run services (vision adapter, CPU executor, layout, reference bank, error sink).
        vocabulary: Descriptor fields to report.
        marks: Draw the numbered outline on each crop.

    Returns:
        The validated identification result (same ordering rules as the other strategies).
    """
    _check_vocabulary(vocabulary, ctx.layout.descriptor_fields if ctx.layout is not None else ())
    zones = _include_zones(ctx)
    allocate = _id_allocator(perception)
    targets = _targets(perception, include_zones=zones)
    # FILL IN: results = await asyncio.gather(*(_run_call(image, [t], strip_box([t], perception.image_size,
    #   pad=SLOT_CROP_PAD), perception, ctx, vocabulary=vocabulary, marks=marks, next_shape_id=allocate,
    #   include_zones=zones) for t in targets)); return _finalise(perception, ctx, results, include_zones=zones)
    #   — bounded by AC12 (one failed call isolated; cancellation propagates)
    raise NotImplementedError
```
**Why**: spec §3 skeleton; reusing `_run_call` gives the repair, unknown-id rejection, addition
remapping and failure isolation for free.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_identify.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -Fxc 'class InlineExecutor:' test_identify.py) — at test_identify.py:36
# REPLACE StubAdapter (test_identify.py:41-54) so it also records images (existing assertions unchanged):
class StubAdapter:
    """Pops queued answers; an Exception instance is raised. Callables receive the prompt."""

    def __init__(self, *answers):
        self.answers, self.calls, self.images = list(answers), [], []

    async def ask(self, prompt, images, schema, *, stage, prompt_version, system_prompt=None):
        self.calls.append(prompt)
        self.images.append(list(images))
        assert images and images[0][:8] == b"\x89PNG\r\n\x1a\n"
        assert prompt_version == IDENTIFY_PROMPT_VERSION
        item = self.answers.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item(prompt) if callable(item) else item
# APPEND the new tests from the Test Specification at the end of the file (after test_additions_get_membership, :272-281).
```
**Why**: `BaseException` lets a test queue `asyncio.CancelledError()`; recording images proves
identical attachments on initial and repair calls.

### FILL IN checklist
- [ ] `_targets` zone append + de-dup; bounded by spec §6 Corrections
- [ ] `build_identify_prompt` v2 text; bounded by AC6, AC7 (no "planogram"/"expected")
- [ ] `_validate` moved body; bounded by `validate_response` behaviour unchanged
- [ ] `_area` legacy branch verbatim + `tag_text`; bounded by AC5
- [ ] `_run_call` images/repair/reference_id/diagnostics; bounded by AC6, AC7, AC12
- [ ] `identify_slots` gather; bounded by AC12

---

## Acceptance Criteria

- [ ] AC6: `IDENTIFY_PROMPT_VERSION == "identify-v2-ocr"`; initial and repair calls send identical `images` (`[png, *references]`); capped/omitted references are reported in errors.
- [ ] AC7: prompt contains no `planogram`/`expected`, no catalogue key; an unknown `reference_id` is rejected and `product`/`raw_confidence` are untouched.
- [ ] AC5: with `ocr_readings`, a slot's `ocr_text` is its own reading and the tag text is under `tag_text`.
- [ ] AC3: `identify_slots` makes one call per target; additions are returned in source pixels; custom descriptor names declared by the profile are accepted.
- [ ] AC12: one failed slot/strip call is isolated; `asyncio.CancelledError` propagates.
- [ ] Zones become targets only with `ctx.layout` set; every pre-existing test in `test_identify.py` passes unchanged.
- [ ] `ruff check` / `black --check --line-length 120` pass on both files.

---
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_identify.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_identify.py`

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_identify.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_detector_verify.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py -q`

---

## Test Specification

```python
# appended to packages/ai-parrot-pipelines/tests/planogram_cycle/test_identify.py
import asyncio
from parrot_pipelines.planogram.contracts import OcrReading, ReferenceImage
from parrot_pipelines.planogram.identification.identify import identify_slots
from parrot_pipelines.planogram.layout import LayoutProfile, ReferencePolicy
from parrot_pipelines.planogram.perception.profiles import PRICE_TAG_PROFILE

PNG = b"\x89PNG\r\n\x1a\n" + b"ref"


def _layout(**overrides):
    return LayoutProfile(shape_profiles=[PRICE_TAG_PROFILE], **overrides)


def test_prompt_version_is_v2():
    assert IDENTIFY_PROMPT_VERSION == "identify-v2-ocr"


def test_v2_prompt_has_occupancy_and_printed_code_rules_without_expectations(): ...
    # prompt = build_identify_prompt(areas, ["family"]) (two positional args still work)
    # "empty" and "ocr_text" rules present; "planogram" and "expected" absent (lowercased)


def test_reference_labels_listed_without_catalogue_keys(): ...
    # build_identify_prompt(areas, [], reference_labels=["ref-0001", "ref-0002"]) contains both labels, "reference_id"


async def test_references_attached_to_initial_and_repair_calls(perception): ...
    # ctx.layout=_layout(); ctx.reference_bank=[ReferenceImage(label="ref-0001", image=PNG, catalog_key="A")]
    # first answer omits one id -> repair; adapter.images[0] == adapter.images[1] and len == 2


async def test_unknown_reference_id_is_rejected(perception): ...
    # answer returns reference_id="ref-9999" -> identification.reference_id is None, error mentions "unknown reference_id",
    # product and raw_confidence unchanged


async def test_capped_references_reported(perception): ...
    # 7 refs, ReferencePolicy(max_per_call=2) -> each call has 3 images; result.errors mention "omitted"


async def test_zones_are_targets_only_with_layout(perception): ...
    # without layout: 6 identifications (as today); with ctx.layout: "img0:zone" also present, 7 total


async def test_own_box_ocr_used_and_tag_text_separate(perception): ...
    # perception.ocr_readings={"img0:r0:s1": OcrReading(text="62XL", confidence=0.9)}; prompt AREAS has
    # "ocr_text":"62XL" for the slot and "tag_text":"OCR-01"; a slot without reading has "ocr_text":null


async def test_custom_descriptor_allowed_when_declared_by_profile(perception): ...
    # vocabulary=["capacity_ml"] raises ValueError without layout; passes with _layout(descriptor_fields=["capacity_ml"])


async def test_identify_slots_one_call_per_target(perception): ...
    # 6 slots -> 6 calls, each AREAS has exactly one id


async def test_identify_slots_addition_is_source_pixels(perception): ...
    # added_shapes box_norm on a slot crop maps back inside the padded crop in source coordinates


async def test_identify_slots_failure_isolated(perception): ...
    # one VisionError among 6 answers -> that target uncertain, others resolved, one error


async def test_cancellation_propagates(perception): ...
    # StubAdapter(asyncio.CancelledError()) -> pytest.raises(asyncio.CancelledError)
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug refactor-planogram-compliance --feature-id FEAT-612`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/refactor-planogram-compliance.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/refactor-planogram-compliance.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3858 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Merged cleanly via sdd-worker orchestration; lint clean (residual style debt left to /sdd-done).

