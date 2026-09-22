---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot-pipelines, ai-parrot-client-amazon]
tags: [nova, bedrock, planogram, vision, object-detection]
---

# Brainstorm: Amazon Nova 2 Lite slot identification for planogram images

**Date**: 2026-09-23
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

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

## Constraints & Requirements

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

## Options Explored

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

### Option B: Self-contained mirror of the aws-samples script

Port the AWS reference script into `examples/planogram/aws/` and give it its own
marking, prompting, parsing and reconciliation, importing nothing from
`parrot_pipelines`. The file reads top-to-bottom next to the upstream sample.

✅ **Pros:**
- Readable in isolation; a newcomer sees the whole Nova interaction in one file.
- Immune to refactors inside `parrot_pipelines.planogram`.
- Closest to the upstream aws-samples code the user referenced, so diffing against it is trivial.

❌ **Cons:**
- Re-implements ~450 lines that already exist and are covered by tests in `packages/ai-parrot-pipelines/tests/planogram_cycle/`.
- Its results are **not** comparable to the Google/Claude runs — a different prompt and a different reconciliation policy confound any accuracy comparison, defeating the main reason to build it.
- Guaranteed drift: the shared marking/validation logic has already been revised twice (TASK-3344 → TASK-3438) and would leave the copy behind.

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aioboto3` | async Converse calls | already declared |
| `opencv-python`, `numpy`, `pillow` | drawing and I/O | already present |

🔗 **Existing Code to Reuse:**
- `examples/planogram/plancheck/identify.py` — `render_strip` (example-local Set-of-Marks precedent) as the copy source.
- `examples/planogram/plancheck/report.py` — `annotate`, the status-coloured overlay drawer.

---

### Option C: Land Bedrock image support in the client first

Implement Converse image content blocks in `BedrockConverseBase._prepare_messages`
and `_to_bedrock_content_block`, add `ask_to_image` to the Bedrock base, register
`"nova"` in `vision.py`'s `SUPPORTED_KWARGS`, then let `nova2.py` be a ~60-line
demo that just passes `--llm nova:nova-2-lite` into the existing pipeline.

✅ **Pros:**
- Fixes the real defect: Nova silently discarding images is a bug that will bite anyone else who tries.
- Makes Nova available to the *whole* framework — planogram, agents, every vision caller — not just this example.
- The example becomes trivial and permanently maintenance-free.

❌ **Cons:**
- Touches `clients/base.py`'s descendants and a heavily-used client (`bedrock.py` is 108 KB); needs its own spec, regression tests and a careful review.
- Blocks the example behind client work, so the empirical question ("is Nova 2 Lite good enough on ink walls?") stays unanswered for longer — which is backwards, since the answer should *justify* the client work.
- Risk of building image support against an unvalidated assumption about how Nova wants boxes presented.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aioboto3` | already the client's transport | no new dependency |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py:725` — `_prepare_messages`, the exact place the drop happens.
- `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py:747` — `_to_bedrock_content_block`, already returns `None` for unsupported block types and documents the gap.
- `packages/ai-parrot-client-google/src/parrot/clients/google/client.py:5011` — `ask_to_image`, the reference signature to mirror.

---

### Option D (unconventional): Nova as a *competing detector*, not a labeller

Invert the premise. The AWS blog sells Nova 2 Lite on its *native* grounded
detection — returning its own boxes — which is precisely the capability we throw
away by handing it OpenCV's boxes. This option runs Nova twice: once
box-constrained (Option A's mode) and once free-running ("find every ink
cartridge box"), then IoU-matches the two box sets against the OpenCV shapes and
reports where they disagree.

The output is not a compliance answer but an **arbitration report**: boxes only
OpenCV found, boxes only Nova found, boxes both agree on. `backend_benchmark.py`
(`examples/planogram/backend_benchmark.py`, TASK-3450) already exists as the
precedent for this kind of harness, and `grid/merger.py` already exposes
`_compute_iou`.

✅ **Pros:**
- Answers a question nothing else in the repo answers: is our OpenCV perception stage even finding the right shapes? Today Stage 1 has no independent check.
- Directly exercises the capability AWS actually benchmarks, so a poor result is interpretable rather than "maybe we prompted it wrong".
- Naturally extends `backend_benchmark.py` instead of adding an orphan script.

❌ **Cons:**
- Doubles the call count and the cost per photo.
- Not what was asked for — it does not produce the `{bbox, brand, product}` deliverable on its own, only alongside it.
- Needs `AddedShape` handling and a match-quality metric with no agreed threshold yet, which is real design work.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aioboto3` | Converse calls | already declared |
| `opencv-python` | IoU overlay rendering | already present |

🔗 **Existing Code to Reuse:**
- `parrot_pipelines/planogram/grid/merger.py` — `_compute_iou`, already imported by `identify.py:29`.
- `parrot_pipelines/planogram/contracts.py:117` — `AddedShape`, the existing contract for "a product the model found that perception missed".
- `examples/planogram/backend_benchmark.py` — the existing unlabelled-backend comparison harness.

---

## Recommendation

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

## Feature Description

### User-Facing Behavior

```bash
source .venv/bin/activate
python examples/planogram/aws/nova2.py \
    --image examples/planogram/images/shelf_01.jpg \
    --planogram examples/planogram/planogram_page1.json \
    --output examples/planogram/results/nova_run1
```

Flags:

- `--image <path>` (required) — the store photo.
- `--boxes <path>` — a saved `PerceptionResult` JSON; when omitted, Stage-1
  perception runs live on the image.
- `--planogram <path>` — planogram JSON supplying the closed-set SKU/brand
  vocabulary (default `examples/planogram/planogram_page1.json`).
- `--output <dir>` (required) — new directory for results.
- `--model <id>` — default `us.amazon.nova-2-lite-v1:0`.
- `--region <name>` — default from `parrot.conf`/env, falling back to `us-east-1`.
- `--concurrency <n>` — bounds concurrent Bedrock calls (default 4).
- `--no-marks` — disable the Set-of-Marks overlay, for A/B comparison.
- `--cache-dir <dir>` — reuse `VisionAdapter`'s response cache across reruns.

Outputs in `<output>/`:

- `detections.json` — a flat array, one entry per box sent:
  `{"bbox": [x1, y1, x2, y2], "shape_id": "...", "occupancy": "occupied|empty|unknown", "brand": "HP", "product": "63XL Black", "confidence": 0.82, "evidence": "..."}`.
  `bbox` is in **source-image pixels**, so it drops straight back onto the photo.
- `annotated.jpg` — the photo with each box drawn and labelled `brand / product`,
  empty slots in a distinct colour.
- `run.json` — model id, region, prompt version, box count, call count, token
  usage and per-strip errors.

Exit codes: `0` success, `1` invalid input (missing image, unreadable planogram,
no credentials), `2` completed with errors (one or more strips failed).

### Internal Behavior

1. **Resolve configuration.** Credentials via the `parrot.conf` `AWS_CREDENTIALS`
   profile pattern with an env fallback; region and model from flags or defaults.
   Fail fast with exit 1 before any image work if credentials are absent.
2. **Perceive.** Either deserialize `--boxes` into a `PerceptionResult`, or run
   `propose_shapes → group_rows → build_slots` on the decoded BGR image and
   assemble a `PerceptionResult` with the real `image_size`.
3. **Build the closed-set vocabulary.** Read the planogram's positions and
   collect the distinct `brand` values and product descriptors into the candidate
   list the prompt will offer.
4. **Wire the adapter.** Construct `NovaVisionClient` (the aioboto3 shim), wrap it
   in a `VisionAdapter` with the resolved backend, a semaphore sized by
   `--concurrency`, the cache dir and `repair_retries=1`. Put it on a
   `CycleContext` alongside a `CpuExecutor`.
5. **Identify.** Call `identify_strips(image, perception, ctx, vocabulary=...,
   marks=True)`. Per row, it crops a strip, draws numbered outlines, converts
   each target box to 0–1000 strip-relative coordinates, sends the prompt plus
   the strip PNG, and validates the answer back into `Identification` objects.
6. **Flatten and render.** Convert each `Identification` back to source pixels,
   write `detections.json`, and draw `annotated.jpg`.
7. **Report.** Write `run.json`; exit 2 if `IdentificationResult.errors` is
   non-empty.

The Nova shim itself does one thing: take `(prompt, image_bytes, model,
max_tokens, temperature, structured_output)`, build a Converse request with a
`{"image": {"format": "png", "source": {"bytes": ...}}}` content block, append a
JSON-schema instruction derived from `structured_output.model_json_schema()`,
call `bedrock-runtime.converse`, and return an object whose `.output` is the
model's text. `VisionAdapter._extract` already strips ```` ```json ```` fences and
validates, so the shim never parses anything itself.

### Edge Cases & Error Handling

- **No credentials / no Bedrock access** — fail before touching the image, exit 1
  with the resolution order printed.
- **Nova 2 Lite without a geo prefix** — Bedrock returns an access error; the
  shim detects a bare `amazon.nova-2-lite-v1:0` model id and raises a message
  naming the required `us.`/`eu.`/`jp.`/`global.` prefix rather than surfacing a
  raw AWS error.
- **Model returns fewer entries than boxes sent** — `validate_response` backfills
  the missing ids as `occupancy="unknown"`, `uncertain=True`; the run still
  succeeds and `run.json` records the shortfall.
- **Model invents a `shape_id`** — dropped by `validate_response`; recorded as an
  error string.
- **Model proposes a box no target covers** — accepted only under `added_shapes`
  with a pipeline-owned id and `source=llm_added`; surfaced in `detections.json`
  with `"source": "llm_added"` so it is never confused with an OpenCV box.
- **Unparseable answer** — `VisionAdapter` retries once with the parse error
  appended; a second failure raises `VisionError`, which `identify_strips`
  isolates to that strip so other rows still produce results.
- **Perception finds zero shapes** — exit 1 with a message telling the user to
  pass `--boxes` or adjust the shape profile; never send an empty AREAS list.
- **Degenerate or out-of-bounds boxes** — clipped to the image before conversion;
  zero-area boxes are dropped with a warning.
- **Strip wider than Nova's image limits** — `_plan_chunks` already caps targets
  per call (`substrip_max_slots`, default 8); rows above the cap split into
  sub-strips.
- **Token budget exhausted mid-array** — surfaces as an invalid answer and takes
  the repair-retry path; `run.json` records the stop reason.

---

## Capabilities

### New Capabilities
- `nova-image-planogram`: run planogram Stage-2 identification on Amazon Nova 2 Lite from an example script, using real Stage-1 OpenCV boxes and a closed-set planogram vocabulary.
- `nova-vision-shim`: an example-local, `ask_to_image`-compatible Bedrock Converse image transport that satisfies `VisionAdapter`'s duck-type, and serves as the prototype for the eventual client implementation.

### Modified Capabilities
- None. `new-planogram-pipeline` (FEAT-574) is **used**, not changed — no file under `packages/ai-parrot-pipelines/` is edited by this feature.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `examples/planogram/aws/nova2.py` | creates | CLI entry point; git-ignored, needs `git add -f` |
| `examples/planogram/aws/nova_vision.py` | creates | aioboto3 Converse shim exposing `ask_to_image` |
| `examples/planogram/aws/README.md` | creates | setup, IAM/region prerequisites, geo-prefix caveat |
| `parrot_pipelines.planogram.identification` | depends on | imports `identify_strips`, `validate_response`, `render_marked_strip`, `VisionAdapter` — **read-only** |
| `parrot_pipelines.planogram.perception` | depends on | `propose_shapes`, `group_rows`, `build_slots`, `to_strip_norm`, `from_strip_norm` — read-only |
| `ai-parrot-client-amazon` | depends on | `aioboto3` dependency and the `AWS_CREDENTIALS` resolution pattern; the client itself is unchanged |
| `packages/ai-parrot-pipelines/tests/` | none | no pipeline behaviour changes; example tests (if any) live under `examples/planogram/tests/` |
| CI | none | example is git-ignored and not collected by the default pytest run |

Breaking changes: none. New runtime dependencies: none (`aioboto3` already declared).

---

## Code Context

### User-Provided Code

```python
# Source: user-provided (aws-samples/sample-object-detection-nova-2-lite)
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Object detection and visualization using Amazon Bedrock Nova models."""

import ast
import os
import re
import sys
from typing import Dict, List, Union
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import (
    analyze_image as _analyze_image_base,
    change_detection_result_format,
    is_bbox_valid,
    sanitize_object_list,
    visualize_boxes,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_TEMPLATE_PATH = os.path.join(SCRIPT_DIR, "prompt_template.txt")


def analyze_image(
    image_path: Union[str, bytes],
    image_format: str,
    user_message: str,
    model_id: str,
    region: str = "us-west-2",
    temperature: float = 0,
) -> str:
    """Analyze an image using Amazon Bedrock's Converse API."""
    if isinstance(image_path, str):
        with open(image_path, "rb") as file:
            image_bytes = file.read()
    else:
        image_bytes = image_path

    return _analyze_image_base(
        image_bytes=image_bytes,
        image_format=image_format,
        user_message=user_message,
        model_id=model_id,
        region=region,
        temperature=temperature,
    )


def detect_objects_and_visualize(
    image_path: str, object_list: List[str], model_id: str, region: str = "us-west-2", show: bool = True
) -> Dict[str, List]:
    """Detect objects in an image and display results with bounding boxes."""
    with open(PROMPT_TEMPLATE_PATH, "r") as f:
        user_message_template = f.read()

    image = Image.open(image_path)
    w, h = image.size
    image_format = image.format.lower()

    validated_objects = sanitize_object_list(object_list)

    schema = {}
    for object_name in validated_objects:
        schema[object_name] = [{"bbox": [int, int, int, int]}]

    elements = ", ".join(schema.keys())
    user_message = user_message_template.format(elements=elements, schema=schema)

    bbox_info = analyze_image(
        image_path=image_path,
        image_format=image_format,
        user_message=user_message,
        model_id=model_id,
        region=region,
        temperature=0,
    )
    print(bbox_info)

    if "```" in bbox_info:
        pattern = r"```json(.*?)```"
        bbox_info = re.search(pattern, bbox_info, flags=re.DOTALL).group(1)
    detection_result = change_detection_result_format(ast.literal_eval(bbox_info))

    labels = []
    boxes = []
    for i in range(len(detection_result["boxes"])):
        label = detection_result["labels"][i]
        box = detection_result["boxes"][i]
        if is_bbox_valid(box):
            labels.append(label)
            x1, y1, x2, y2 = box
            x1, x2 = round(x1 / 1000 * w), round(x2 / 1000 * w)
            y1, y2 = round(y1 / 1000 * h), round(y2 / 1000 * h)
            boxes.append([x1, y1, x2, y2])

    detection_result["labels"] = labels
    detection_result["boxes"] = boxes

    visualized_image = visualize_boxes(image, detection_result)
    if show:
        visualized_image.show()

    detection_result["image"] = visualized_image
    return detection_result
```

Notes on the reference code, for the implementer:

- `common.py`, `prompt_template.txt`, `change_detection_result_format`,
  `is_bbox_valid`, `sanitize_object_list` and `visualize_boxes` are **upstream
  aws-samples symbols — none of them exist in this repository.** Do not import
  them; the parrot equivalents are listed below.
- The `/ 1000 * w` and `/ 1000 * h` scaling confirms Nova's 0–1000 normalised
  convention. `parrot_pipelines...perception.slots.from_strip_norm` does the same
  conversion, correctly handling the strip offset, and must be used instead.
- `ast.literal_eval` on model output is unsafe and unnecessary here —
  `VisionAdapter._extract` already handles fenced JSON via `json.loads`.
- The upstream sample is synchronous (`boto3`); this repo is async-first and
  `aioboto3` is already available.

Reference links supplied by the user:
- <https://github.com/aws-samples/sample-object-detection-nova-2-lite/tree/main>
- <https://aws.amazon.com/es/blogs/machine-learning/object-detection-with-amazon-nova-2-lite/>

Requested prompt semantics (verbatim intent): pass the image and the JSON of
detected boxes; ask Nova 2 Lite, for each coordinate passed, whether there is a
product or an empty slot; if there is a product, identify product and brand (HP,
Epson, Canon, …); return a JSON structure with bbox, brand and product.

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py:131
class VisionAdapter:
    """Prompt + images + Pydantic schema → validated instance, on any client exposing ``ask_to_image``."""

    def __init__(                                              # line 134
        self,
        client: Any,
        backend: ResolvedBackend,
        *,
        semaphore: asyncio.Semaphore,
        cache_dir: Optional[Path] = None,
        max_tokens: int = 8192,
        timeout: float = 120.0,
        repair_retries: int = 1,
    ) -> None: ...
    # line 157-161: raises VisionError when `not hasattr(client, "ask_to_image")`
    # line 165:     self.client_name = str(getattr(client, "client_name", "") or "").lower()

    async def ask(                                             # line 173
        self,
        prompt: str,
        images: Sequence[bytes],
        schema: Type[T],
        *,
        stage: str,
        prompt_version: str,
        system_prompt: Optional[str] = None,
    ) -> T: ...

    async def _call(self, prompt, images, schema, system_prompt, stage="") -> Any:  # line 244
        # line 269-271: await self.client.ask_to_image(prompt=final_prompt, image=images[0], **kwargs)

    @staticmethod
    def _extract(message: Any, schema: Type[T]) -> T:           # line 278
        # reads `.structured_output` then `.output`; accepts schema instance,
        # BaseModel, dict, list, or a str (strips ``` / ```json fences, json.loads)

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py:35
def normalise_kwargs(client_name: str, requested: Dict[str, Any]) -> Dict[str, Any]: ...
    # line 52: supported = SUPPORTED_KWARGS.get(client_name, _COMMON)
    # raises VisionError for keys outside KNOWN_KWARGS; drops None values

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py:100
def encode_png(image: np.ndarray) -> bytes: ...

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py:90
def render_marked_strip(image: np.ndarray, strip: PixelBox, marks: List[Tuple[int, PixelBox]]) -> bytes: ...
    # PixelBox = Tuple[int, int, int, int]  (identify.py:35)

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py:119
def build_identify_prompt(targets: Sequence[Dict[str, Any]], vocabulary: Sequence[str]) -> str: ...
    # docstring, line 125: "Must NOT mention a planogram or expected products."

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py:212
def validate_response(
    response: IdentificationResponse,
    perception: PerceptionResult,
    *,
    strip: Optional[DetectionBox],
    next_shape_id: Callable[[], str],
) -> Tuple[List[Identification], List[Shape], List[str]]: ...

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py:432
async def identify_full_image(
    image: np.ndarray, perception: PerceptionResult, ctx: CycleContext, *, vocabulary: Sequence[str]
) -> IdentificationResult: ...

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py:464
async def identify_strips(
    image: np.ndarray,
    perception: PerceptionResult,
    ctx: CycleContext,
    *,
    vocabulary: Sequence[str],
    marks: bool = True,
    substrip_max_slots: int = 8,
) -> IdentificationResult: ...

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:101
class Identification(BaseModel):
    shape_id: str                                    # line 104
    image_id: Optional[str] = None                   # line 105
    product: Optional[str] = None                    # line 106
    brand: Optional[str] = None                      # line 107
    text: Optional[str] = None                       # line 108
    descriptors: Dict[str, Any] = Field(default_factory=dict)   # line 109
    occupancy: str = "unknown"                       # line 110  ("occupied"|"empty"|"unknown")
    raw_confidence: float = Field(default=0.0, ge=0.0, le=1.0)  # line 111
    evidence: List[str] = Field(default_factory=list)           # line 112
    source: ObservationSource = ObservationSource.CV            # line 113
    uncertain: bool = False                          # line 114

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:117
class AddedShape(BaseModel):
    box_norm: List[int]      # [ymin, xmin, ymax, xmax], 0-1000, relative to the image/strip sent  (line 120)
    kind: ShapeKind = ShapeKind.UNKNOWN
    product: Optional[str] = None
    brand: Optional[str] = None
    ...

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:130
class IdentificationResponse(BaseModel):
    existing_identifications: List[Identification] = Field(default_factory=list)
    added_shapes: List[AddedShape] = Field(default_factory=list)

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:137
class IdentificationResult(BaseModel):
    image_id: str = "img0"
    identifications: List[Identification] = Field(default_factory=list)
    added: List[Shape] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:50
class Shape(BaseModel):
    """One perceived shape, in SOURCE-image pixels."""
    shape_id: str
    image_id: str
    kind: ShapeKind = ShapeKind.UNKNOWN
    box: DetectionBox
    row_index: Optional[int] = None    # 0-based, top → bottom
    slot_index: Optional[int] = None   # 1..n inside its row
    ocr_text: Optional[str] = None
    source: ObservationSource = ObservationSource.CV
    ...

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:86
class PerceptionResult(BaseModel):
    image_id: str = "img0"
    image_size: Tuple[int, int] = (0, 0)   # (width, height)
    shapes: List[Shape] = Field(default_factory=list)
    slots: List[Slot] = Field(default_factory=list)
    zones: List[Shape] = Field(default_factory=list)
    row_count: int = 0
    detection_source: str = "cv"
    errors: List[str] = Field(default_factory=list)

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:322
class CycleContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    vision: Any = None        # VisionAdapter
    executor: Any = None      # CpuExecutor
    ocr: Any = None           # OcrReader
    output_dir: Optional[Path] = None
    errors: List[str] = Field(default_factory=list)
    ...

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/backend.py:28
class ResolvedBackend(BaseModel):
    provider: str
    model: Optional[str] = None
    origin: BackendOrigin
    def as_string(self) -> str: ...     # line 34

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/shapes.py:128
def propose_shapes(
    image: np.ndarray, profiles: Sequence[ShapeProfile], *, work_width: int = 2048
) -> List[ShapeCandidate]: ...

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/rows.py:20
def group_rows(...) -> ...  # signature to re-read at task time

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py:115
def build_slots(
    rows: Sequence[Sequence[ShapeCandidate]],
    image_size: Tuple[int, int],
    *,
    image_id: str,
    rule: AnchorRule,
    fill_gaps: bool = True,
    untagged_bottom_row: bool = False,
) -> List[Slot]: ...

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py:214
def strip_box(slots: Sequence[Slot], image_size: Tuple[int, int], pad: float = 0.04) -> DetectionBox: ...

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py:242
def to_strip_norm(box: DetectionBox, strip: DetectionBox) -> List[int]: ...     # pixels → 0-1000 [ymin,xmin,ymax,xmax]

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py:263
def from_strip_norm(norm: Sequence[int], strip: DetectionBox) -> DetectionBox: ...  # 0-1000 → pixels

# From packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py:725
def _prepare_messages(self, prompt: str, files: Optional[List[Union[str, Path]]] = None) -> List[Dict[str, Any]]:
    """...
    Note:
        File/image attachments are not yet supported for Bedrock
        Converse in this client — a warning is logged and files are
        skipped (no Bedrock-specific encoding implemented yet).
    """
    if files:
        self.logger.warning(
            "BedrockConverseClient: file/image attachments are not yet " "supported (%d file(s) ignored).",
            len(files),
        )
    return [{"role": "user", "content": [{"text": prompt}]}]

# From packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/client.py:34
class NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration):
    client_type: str = "nova"
    client_name: str = "nova"
    provider_keys: tuple[str, ...] = ("nova",)
    models: type[Enum] = AmazonModel
    _default_model: str = "nova-2-lite"
    _fallback_model: str = "nova-lite"
    # region_prefix DEFAULTS to "us" here → us.amazon.nova-2-lite-v1:0
```

#### Verified Imports

```python
# Confirmed to resolve in the current tree:
from parrot.models.detections import DetectionBox                       # identify.py:14
from parrot_pipelines.planogram.contracts import (                      # identify.py:16-25
    CycleContext, Identification, IdentificationResponse,
    IdentificationResult, ObservationSource, PerceptionResult, Shape, Slot,
)
from parrot_pipelines.planogram.identification.vision import VisionError, encode_png   # identify.py:27
from parrot_pipelines.planogram.perception.slots import from_strip_norm, strip_box, to_strip_norm  # identify.py:29
from parrot_pipelines.planogram.perception.membership import assign_membership, usable_shapes      # identify.py:28
from parrot_pipelines.planogram.grid.merger import _compute_iou         # identify.py:26
from parrot_pipelines.planogram.backend import ResolvedBackend          # vision.py:17
from parrot_pipelines.planogram.perception import (                     # perception/__init__.py:3-6
    PRICE_TAG_PROFILE, ShapeCandidate, ShapeProfile, propose_shapes,
)
from parrot.clients.factory import LLMFactory                           # backend.py:10
from parrot.conf import DEFAULT_LLM_MODEL                               # backend.py:11
```

#### Key Attributes & Constants

- `IDENTIFY_PROMPT_VERSION` → `"identify-v1"` (identify.py:33) — the example must use its **own** version string for the closed-set prompt so cache entries never collide.
- `IDENTIFY_STAGE` → `"identify"` (identify.py:34)
- `DUPLICATE_IOU` → `0.5` (identify.py:35)
- `_MARK_COLOUR` → `(0, 255, 0)` BGR (identify.py:40)
- `_EMPTY_IDENTITY_TOKENS` → `frozenset({"", "none", "null", "unknown", "n/a", "na", "empty", "empty slot"})` (identify.py:43)
- `_COMMON` → `frozenset({"model", "max_tokens", "temperature", "structured_output", "reference_images"})` (vision.py:21) — **the kwarg set `"nova"` will receive**, since it is absent from `SUPPORTED_KWARGS`.
- `SUPPORTED_KWARGS` keys → `{"google", "claude", "openai"}` only (vision.py:22-27).
- `DEFAULT_LLM_BACKEND` → `f"google:{DEFAULT_LLM_MODEL}"` (backend.py:23).
- `Identification.occupancy` accepts `"occupied" | "empty" | "unknown"` (contracts.py:110).
- `AddedShape.box_norm` is `[ymin, xmin, ymax, xmax]` 0–1000 (contracts.py:120).
- `aioboto3>=13.2.0` (packages/ai-parrot-client-amazon/pyproject.toml:17).
- `examples/planogram/*` is git-ignored (`.gitignore:418`).

### Does NOT Exist (Anti-Hallucination)

- ~~`BedrockConverseBase.ask_to_image`~~ / ~~`NovaClient.ask_to_image`~~ — **does not exist.** `ask_to_image` is implemented only at `clients/anthropic/client.py:1329`, `clients/google/client.py:5011`, `clients/openai/client.py:1468` (plus a passthrough at `anthropic/claude_agent.py:1036`). This is the whole reason the shim exists.
- ~~Bedrock Converse image content blocks~~ — `bedrock.py:725-745` drops files with a warning; `_to_bedrock_content_block` (line 747) returns `None` for unsupported types. There is no image encoding path in the Bedrock client today.
- ~~`SUPPORTED_KWARGS["nova"]`~~ / ~~`SUPPORTED_KWARGS["bedrock"]`~~ / ~~`SUPPORTED_KWARGS["amazon"]`~~ — not registered in `vision.py:22-27`. Unknown providers silently fall back to `_COMMON`; this is fine and needs no edit.
- ~~`examples/planogram/aws/`~~ — the directory does not exist yet.
- ~~`common.py`~~, ~~`prompt_template.txt`~~, ~~`change_detection_result_format`~~, ~~`is_bbox_valid`~~, ~~`sanitize_object_list`~~, ~~`visualize_boxes`~~ — upstream aws-samples symbols, **absent from this repository.**
- ~~`parrot/vectorstores/`~~, ~~a repo-root `parrot/` package~~ — this is a uv workspace; source lives under `packages/<dist>/src/`.
- ~~`parrot_pipelines.planogram.identification.identify.build_closed_set_prompt`~~ — no closed-set prompt builder exists; `build_identify_prompt` is contractually open-set and must not be changed by this feature.
- ~~`IdentifyStrategy.CROPS`~~ — the enum has only `FULL_IMAGE` and `STRIPS` (contracts.py:43-47).
- ~~`requests`~~ / ~~`httpx`~~ / ~~sync `boto3` in new code~~ — banned by `.claude/rules/codebase-conventions.md`; use `aiohttp` / `aioboto3`.

---

## Parallelism Assessment

- **Internal parallelism**: Limited but real. The Nova transport shim
  (`nova_vision.py` — credentials, Converse request shape, geo-prefix
  validation) is independently testable against a recorded Converse response and
  has no dependency on the perception wiring. The CLI/perception/flatten path in
  `nova2.py` depends on the shim's signature only, which the shim task fixes
  first. The README is trivially parallel. Realistically 2 tasks can overlap
  after a shared interface task, which is not enough to justify separate
  worktrees.
- **Cross-feature independence**: High. The feature adds files under
  `examples/planogram/aws/` and edits **nothing** under `packages/`. It reads
  `parrot_pipelines.planogram` but never writes it, so it cannot conflict with
  in-flight work on FEAT-574 (`new-planogram-pipeline`) or FEAT-565
  (`new-planogram-compliance-algo`) at the file level. The only coupling is
  semantic: if `identify_strips` or `validate_response` change signature while
  this is in flight, the example breaks at import — loudly, and easy to fix.
  Note that `examples/planogram/` currently has uncommitted work on `dev`
  (`pipelines/`, and `98eae4b45 wip: planogram identification`), so the worktree
  should be cut from `origin/dev` as usual and the example must not touch those
  paths.
- **Recommended isolation**: `per-spec`
- **Rationale**: Small feature (3–5 tasks, all in one new directory), strong
  sequential coupling between the shim's signature and its consumer, and zero
  shared files with other specs. One worktree, tasks run in order, no
  coordination overhead.

---

## Open Questions

- [x] Flow type and base branch — *Owner: Jesus Lara*: `type: feature`, `base_branch: dev`.
- [x] Standalone example vs. fixing the client first — *Owner: Jesus Lara*: ship the example now; the `BedrockConverseBase` image-support work is a separate follow-up feature.
- [x] Where do the boxes come from — *Owner: Jesus Lara*: run Stage-1 perception live, with `--boxes <PerceptionResult.json>` to override for reproducible reruns.
- [x] Output JSON shape — *Owner: Jesus Lara*: flat `{bbox, brand, product, occupancy, …}` array in source-image pixels, not the `Identification` contract.
- [x] How are boxes presented to Nova — *Owner: Jesus Lara*: Set-of-Marks numbered overlay **plus** the boxes JSON, reusing `render_marked_strip`.
- [x] Open-set or closed-set prompting — *Owner: Jesus Lara*: closed-set, vocabulary built from the planogram's SKUs/brands.
- [x] Behaviour on a mismatched answer — *Owner: Jesus Lara*: reconcile ids against those sent and retry once on an invalid answer (both already provided by `validate_response` + `VisionAdapter.repair_retries=1`).
- [x] Self-contained vs. reusing pipeline helpers — *Owner: Jesus Lara*: reuse the pipeline helpers; write only the Nova transport locally.
- [x] Result destination — *Owner: Jesus Lara*: `--output <dir>` containing `detections.json` and an annotated image.
- [x] Model, region and credentials — *Owner: Jesus Lara*: `parrot.conf` `AWS_CREDENTIALS` resolution, default model `us.amazon.nova-2-lite-v1:0`.
- [ ] The closed-set decision conflicts with `build_identify_prompt`'s contract ("Must NOT mention a planogram or expected products", identify.py:125). Confirm the example may carry its own closed-set prompt builder permanently, or whether a closed-set mode should eventually be promoted into the pipeline as an opt-in — *Owner: Jesus Lara*
- [ ] Does the closed-set vocabulary come from the planogram's `product`/`brand` fields only, or also from the descriptor fields (`display_name`, `family`, `xl`, `colors`, `pack`, `aliases`) documented in `examples/planogram/README.md`? The latter is richer but makes the prompt considerably longer per strip — *Owner: Jesus Lara*
- [ ] Which region and IAM identity will be used for the first runs, and is Nova 2 Lite model access already granted there? Bedrock model access is per-account/per-region and is a common first-run blocker — *Owner: Jesus Lara*
- [ ] Should a recorded-response fixture test live under `examples/planogram/tests/` (where `conftest.py` already exists) so the shim is covered without hitting AWS, given that `examples/` is git-ignored and not collected by CI? — *Owner: Jesus Lara*
- [ ] Is there a target cost/latency per photo that would decide whether Nova replaces or merely supplements the Google backend? Without one, the example produces numbers nobody can act on — *Owner: Jesus Lara*
