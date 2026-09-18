# TASK-3349: Pipeline orchestration — `run_check()` (stages 1→8) + integration tests

**Feature**: FEAT-565 — New Planogram Compliance Algorithm
**Spec**: `sdd/specs/new-planogram-compliance-algo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3339, TASK-3340, TASK-3341, TASK-3342, TASK-3343, TASK-3344, TASK-3345, TASK-3346, TASK-3347, TASK-3348
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 12 (pipeline half)**, §2 Overview (eight stages) and the Component
Diagram. Every other module is a pure function or a single-purpose adapter; this task
is the only place where they are wired together, where concurrency is bounded, where
the *cloud vs local* defaults are resolved, and where per-row failures become
`RunInfo.errors` (which the CLI, TASK-3350, turns into exit code 2).

It also owns the three **integration tests** of spec §4 — the only tests that prove
the modules compose (detect → grid → prices ‖ identify → register → verify → score → report).

---

## Scope

- Implement `async def run_check(settings: Settings, *, backend_factory: Callable[..., Any] | None = None) -> ComplianceReport`
  in `examples/planogram/plancheck/pipeline.py`, with the stage order of spec §2.
- Implement the small pure helpers `resolve_verify_pass`, `effective_concurrency`, `absolutize`.
- Resolve every path in `Settings` to absolute **before** the first backend is constructed
  (constructing `VisionBackend` is the first `parrot` import, and importing `parrot` `chdir`s).
- One `asyncio.Semaphore(effective_concurrency)` shared by pass 1 and pass 2; concurrency forced
  to 1 when the identification backend `is_local`.
- `verify_pass=None` → on for cloud, off for local; explicit `True`/`False` wins.
- Per image: `read_prices` ‖ `identify_rows` concurrently (`asyncio.gather`), then
  register, then (optionally) verify. A photo with no tag rows is reported unregistered
  (`ImageInfo.registration is None`) and the run continues.
- Collect every error string into `RunInfo.errors`; fill `RunInfo.reference_provisional`,
  `catalog_missing_skus`, `local_ocr_available`, effective `verify_pass`, timestamps.
- Call `write_report` through `asyncio.to_thread` and return the `ComplianceReport`.
- Write `examples/planogram/tests/test_plancheck_pipeline.py` with the three integration tests
  of spec §4 plus the two helper tests.

**NOT in scope**: argument parsing, logging setup, exit codes, README (TASK-3350); any
algorithm inside the stages (TASK-3339 … TASK-3348); changing any signature of those
modules; touching `conftest.py`, `plancheck/__init__.py` or `plancheck/models.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/plancheck/pipeline.py` | CREATE | `run_check` + pure helpers |
| `examples/planogram/tests/test_plancheck_pipeline.py` | CREATE | 3 integration tests (spec §4) + 2 helper tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: this module imports **no** existing repository code — only stdlib, `cv2`,
> `numpy` and sibling FEAT-565 modules. It must never import `parrot` itself.

### Verified Imports
```python
import asyncio                                  # stdlib — asyncio.to_thread, Semaphore, gather
import contextlib                               # stdlib — AsyncExitStack
import hashlib                                  # stdlib
import json                                     # stdlib (tests)
import logging                                  # stdlib
import re                                       # stdlib (tests)
from collections.abc import Callable            # stdlib
from datetime import datetime, timezone         # stdlib
from pathlib import Path                        # stdlib
from typing import Any                          # stdlib

import cv2                                      # installed: opencv-python 4.10.0.84
import numpy as np                              # installed: numpy 2.4.6
import pytest                                   # tests only; coroutine tests need @pytest.mark.asyncio
```

### Existing Signatures to Use
None from the pre-existing repository. Facts verified in the spec that bind this task:
- spec §6: *"`plancheck/vision.py` must import parrot lazily inside `VisionBackend.__init__`"* → importing
  `plancheck.vision` at module top is safe; **constructing** a `VisionBackend` is the first parrot import.
- spec §7: *"`import parrot` side effect: navconfig `chdir`s to the repo root — resolve all CLI paths to
  absolute before the first parrot import."*
- `pyproject.toml` has no `asyncio_mode` → every coroutine test carries `@pytest.mark.asyncio`.

#### Created by dependency tasks (exist only after they land)
```python
# examples/planogram/plancheck/reference.py — TASK-3339
def load_planogram(path: Path) -> PlanogramRef
def load_catalog(path: Path, planogram: PlanogramRef) -> tuple[Catalog, list[str]]   # (catalog, missing identity-required SKUs)
def load_prices(path: Path) -> dict[str, Decimal]
# examples/planogram/plancheck/detection.py — TASK-3340
def detect_tags(image: np.ndarray, image_id: str, *, work_width: int = 2048,
                roi: tuple[float, float, float, float] | None = None) -> tuple[list[TagRow], list[Box]]
# examples/planogram/plancheck/grid.py — TASK-3341
def row_pitch(row: TagRow) -> float
def build_slots(rows: list[TagRow], image_size: tuple[int, int]) -> list[Slot]        # image_size = (width, height)
# examples/planogram/plancheck/vision.py — TASK-3342
class VisionError(RuntimeError)
class VisionBackend:                                                                   # async context manager
    def __init__(self, llm: str, *, cache_dir: Path, base_url: str | None = None,
                 api_key: str | None = None, max_tokens: int = 8192) -> None
    is_local: bool  # property
# examples/planogram/plancheck/prices.py — TASK-3343
PRICE_PROMPT_VERSION: str
class TagOcr:  available: bool;  def read(self, crop: np.ndarray) -> str
async def read_prices(image: np.ndarray, slots: list[Slot], ocr: TagOcr, backend: "VisionBackend | None", *,
                      semaphore: asyncio.Semaphore | None = None,
                      errors: list[str] | None = None) -> dict[str, PriceReading]         # slot_id → reading
#   semaphore bounds the per-row price-LLM calls; per-row LLM failures are APPENDED to ``errors`` (OCR result kept)
# examples/planogram/plancheck/identify.py — TASK-3344
IDENTIFY_PROMPT_VERSION: str
async def identify_rows(image: np.ndarray, slots: list[Slot], backend: VisionBackend, catalog: Catalog,
                        semaphore: asyncio.Semaphore, *, marks: bool = True
                        ) -> tuple[list[SlotObservation], list[str]]                     # (observations, errors)
# examples/planogram/plancheck/registration.py — TASK-3345
def register_image(image_id: str, observations: list[SlotObservation], planogram: PlanogramRef,
                   catalog: Catalog, pitches: dict[int, float]) -> ImageRegistration     # pitches: row → px
def apply_registration(observations: list[SlotObservation], registration: ImageRegistration) -> None
# examples/planogram/plancheck/verify.py — TASK-3346
VERIFY_PROMPT_VERSION: str
async def verify_rows(image: np.ndarray, observations: list[SlotObservation], planogram: PlanogramRef,
                      catalog: Catalog, backend: VisionBackend, semaphore: asyncio.Semaphore) -> list[str]
# examples/planogram/plancheck/scoring.py — TASK-3347
def merge_positions(planogram, observations, catalog, weights: ScoringWeights,
                    prices: dict[str, Decimal] | None) -> list[PositionResult]
def shelf_scores(positions: list[PositionResult]) -> list[ShelfScore]
def brand_shares(planogram, positions, observations) -> list[BrandShare]
def summarize(positions, observations, planogram, prices: dict[str, Decimal] | None) -> ComplianceSummary
# examples/planogram/plancheck/report.py — TASK-3348
def write_report(report: ComplianceReport, images: dict[str, np.ndarray], settings: Settings,
                 prompt_versions: dict[str, str]) -> Path                                 # synchronous
# examples/planogram/plancheck/models.py — TASK-3337 / TASK-3338
ComplianceReport, ImageInfo, PriceReading, RunInfo, Settings, SlotObservation, TagRow, PlanogramRef, Catalog
```
Shared fixtures from `examples/planogram/tests/conftest.py` (TASK-3337 — use, never redefine):
`shelf_image`, `mini_planogram_data`, `mini_planogram`, `mini_catalog`, `FakeBackend`, `fake_backend`,
constants `TAG_W, TAG_H, TAG_X0, TAG_DX, TAG_ROWS_Y, TAGS_PER_ROW`. `FakeBackend.ask(prompt, images, schema,
*, stage, prompt_version)` pops `queue[stage][0]`: an `Exception` instance is raised, a callable is called
with `(prompt, images)`, anything else is returned. Stages: `"identify"`, `"verify"`, `"prices"`.
`FakeBackend` has **no** `__aenter__`.

### Does NOT Exist
- ~~`from parrot… import …` in `pipeline.py`~~ — the pipeline never imports parrot; only `VisionBackend.__init__` does.
- ~~`client.client` / `chat.completions` / any provider SDK~~ — forbidden everywhere (spec §8 Q7).
- ~~`run_check(settings, backend=…)`~~ — the seam is the keyword-only **`backend_factory`**.
- ~~`read_prices(...)` returning errors~~ — it returns only the dict; per-row failures arrive through the keyword-only `errors=` list you pass in, and the shared `semaphore=` MUST be passed so price calls honour `--concurrency`.
- ~~`identify_rows(...)` returning only observations~~ — it returns `(observations, errors)`.
- ~~`Settings.api_key`~~ — not a field; credentials come from the environment inside the parrot client.
- ~~`asyncio_mode = "auto"`~~ — not configured.
- ~~`time.sleep` / blocking `cv2.imread` inside a coroutine~~ — decode via `asyncio.to_thread`.
- ~~`print(...)`~~ — `logger = logging.getLogger(__name__)`.
- ~~exit codes here~~ — `run_check` returns the report; TASK-3350 maps `report.run.errors` → exit 2.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/planogram/plancheck/pipeline.py",
      "action": "CREATE"
    },
    {
      "path": "examples/planogram/tests/test_plancheck_pipeline.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Decided details (do not re-decide)
- **Test seam (additive to the spec skeleton)**: `backend_factory(llm: str, *, cache_dir: Path, base_url: str | None) -> backend`.
  `None` → `VisionBackend`. The factory is called once per **distinct** llm string
  (`settings.llm`, and `settings.ocr_llm` only when it is set and different). A backend that has
  `__aenter__` is entered through an `AsyncExitStack`; one that does not (the `FakeBackend`) is used as is.
- `image_id = f"image_{n:02d}"` (1-based) in the order of `settings.images`.
- `pitches`: `{row.row: row_pitch(row) for row in rows}`; a synthesized `untagged_row` (row number =
  last row + 1, no `TagRow`) inherits the pitch of the last tag row.
- `observation.price = prices.get(slot_id, PriceReading())` is set by the pipeline after the gather.
- Call `read_prices(image, slots, ocr, ocr_backend, semaphore=semaphore, errors=errors)`: per-row price-LLM failures
  land in `errors` (→ exit code 2) while OCR results are kept. Still wrap the call: an unexpected exception becomes ONE
  error string `"<image_id>: price reading failed: <exc>"` and every price stays `not_assessed`.
- Any `Exception` from a stage on one image is recorded and the run continues with the next image;
  only input errors (`FileNotFoundError`, `FileExistsError`, `ValueError` from the loaders/decoder) propagate.
- A photo with zero tag rows: `ImageInfo(tag_rows=0, tags=0, slots=0, registration=None)`, one entry
  appended to `report.notes` (not to `errors` — it is not a model/OCR error), warning logged.
- Early guard: `Path(settings.output).exists()` → `FileExistsError` before any work (the report writer
  guards again at write time).
- `RunInfo.reference_provisional = any(f.reference_read_method != "direct" for f in planogram.facings)`.
- Timestamps: `datetime.now(timezone.utc).isoformat(timespec="seconds")`.

### Key Constraints
- Async-first: LLM stages awaited; `cv2.imdecode`/file hashing and `write_report` via `asyncio.to_thread`.
- Do not import `parrot`; do not catch `BaseException`; black line length 120; Google-style docstrings.
- Tests: no network, no real photos, synthetic SKUs only; fake the OCR by monkeypatching
  `plancheck.pipeline.TagOcr` (RapidOCR is installed and would otherwise really run).

---

## Implementation Blueprint

### Steps (in order)
1. Create `pipeline.py` part 1 (imports, notes, pure helpers) — *why*: the helpers are what `test_verify_pass_auto_default` and the concurrency test pin; they need no other module.
2. Implement `absolutize` with `Path(...).expanduser().resolve()` for every path field — *why*: the first `VisionBackend(...)` imports parrot, whose navconfig `chdir`s to the repo root; relative paths would silently point elsewhere afterwards.
3. Implement `_load_image` (bytes → sha256 + `cv2.imdecode`) in a thread — *why*: decode is CPU/IO bound and must not block the loop; hashing the same bytes avoids reading twice.
4. Implement `_process_image` — *why*: one coroutine per photo keeps per-image failure isolation (an exception is recorded, the run continues).
5. Implement `run_check` — *why*: owns backend lifetime (`AsyncExitStack`), the shared semaphore, the cloud/local defaults and the final merge/score/report.
6. Write the tests with a prompt-driven canned reader — *why*: rows are processed concurrently, so a positional queue would be order-dependent; a callable that answers from the slot ids in the prompt is not.
7. Run the validation command and `ruff check` — *why*: merge gate.

### `examples/planogram/plancheck/pipeline.py` (CREATE) — part 1/3
```python
"""Pipeline orchestration for the planogram compliance check (FEAT-565, spec §2 stages 1→8)."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .detection import detect_tags
from .grid import build_slots, row_pitch
from .identify import IDENTIFY_PROMPT_VERSION, identify_rows
from .models import Catalog, ComplianceReport, ImageInfo, PlanogramRef, PriceReading, RunInfo, Settings, SlotObservation
from .prices import PRICE_PROMPT_VERSION, TagOcr, read_prices
from .reference import load_catalog, load_planogram, load_prices
from .registration import apply_registration, register_image
from .report import write_report
from .scoring import brand_shares, merge_positions, shelf_scores, summarize
from .verify import VERIFY_PROMPT_VERSION, verify_rows
from .vision import VisionBackend

logger = logging.getLogger(__name__)

STANDING_NOTES: tuple[str, ...] = (
    "All planogram mappings are automatic (registration_method=auto_alignment); none was human-reviewed.",
    "Metrics describe model observations; they are not calibrated accuracy estimates.",
    "verified_by_expectation and inferred results count only in the lenient score.",
)


def resolve_verify_pass(setting: bool | None, is_local: bool) -> bool:
    """``None`` → auto (on for cloud, off for local backends); an explicit value always wins."""
    return (not is_local) if setting is None else setting


def effective_concurrency(requested: int, is_local: bool) -> int:
    """Local servers are driven one call at a time (spec §2 CLI: '1 when the provider is a local server')."""
    return 1 if is_local else requested


def absolutize(settings: Settings) -> Settings:
    """Return a copy of ``settings`` whose path fields are absolute.

    MUST run before the first backend is constructed: that is the first ``parrot`` import and
    navconfig ``chdir``s to the repository root (spec §7).
    """
    # FILL IN: settings.model_copy(update={...}) resolving images[], planogram, catalog, output,
    #   cache_dir and prices (when not None) with Path(p).expanduser().resolve() → str.
    #   Bounded by: every other field unchanged; test_absolutize_resolves_relative_paths.
    raise NotImplementedError


def _default_backend_factory(llm: str, *, cache_dir: Path, base_url: str | None) -> VisionBackend:
    """Build the real backend (this call performs the first ``parrot`` import)."""
    return VisionBackend(llm, cache_dir=cache_dir, base_url=base_url)


def _read_image(path: Path) -> tuple[np.ndarray, str]:
    """Synchronous: read bytes, hash them, decode to BGR. Raises ``ValueError`` when undecodable."""
    data = path.read_bytes()
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot decode image: {path}")
    return image, hashlib.sha256(data).hexdigest()
```
**Why this shape**: the three helpers are pure so the cloud/local rules of spec §2/§8 Q4 are testable
without a backend. `_read_image` hashes the exact bytes it decodes (the snapshot in TASK-3348 records
them). All sibling imports are relative and at module top — safe because `plancheck.vision` imports
parrot lazily inside `VisionBackend.__init__` (spec §6).

### `examples/planogram/plancheck/pipeline.py` (CREATE) — part 2/3
```python
async def _process_image(
    image_id: str,
    path: Path,
    *,
    settings: Settings,
    planogram: PlanogramRef,
    catalog: Catalog,
    backend: Any,
    ocr_backend: Any,
    ocr: TagOcr,
    semaphore: asyncio.Semaphore,
    verify_pass: bool,
) -> tuple[ImageInfo, np.ndarray, list[SlotObservation], list[str], list[str]]:
    """Stages 1–7 for one photo.

    Returns:
        (image info, decoded image, observations, errors, notes).
    """
    errors: list[str] = []
    notes: list[str] = []
    image, sha256 = await asyncio.to_thread(_read_image, path)
    height, width = image.shape[:2]
    rows, _unassigned = await asyncio.to_thread(
        detect_tags, image, image_id, work_width=settings.work_width, roi=settings.roi
    )
    info = ImageInfo(
        image_id=image_id, path=str(path), sha256=sha256, width=width, height=height,
        tag_rows=len(rows), tags=sum(len(r.tags) for r in rows), slots=0,
    )
    if not rows:
        logger.warning("%s: no tag rows detected — photo reported unregistered", image_id)
        notes.append(f"{image_id}: no price-tag rows detected; photo is unregistered.")
        return info, image, [], errors, notes
    slots = build_slots(rows, (width, height))
    info.slots = len(slots)

    async def _prices() -> dict[str, PriceReading]:
        try:
            return await read_prices(image, slots, ocr, ocr_backend, semaphore=semaphore, errors=errors)
        except Exception as exc:  # noqa: BLE001 — a failed price pass must not abort the photo
            errors.append(f"{image_id}: price reading failed: {exc}")
            return {}

    prices, (observations, identify_errors) = await asyncio.gather(
        _prices(), identify_rows(image, slots, backend, catalog, semaphore, marks=settings.marks)
    )
    errors.extend(identify_errors)
    for obs in observations:
        obs.price = prices.get(obs.slot.slot_id, PriceReading())
    # FILL IN: build ``pitches`` ({row.row: row_pitch(row)}; any observation row missing from it
    #   — the synthesized untagged row — inherits the LAST tag row's pitch), then
    #   registration = register_image(image_id, observations, planogram, catalog, pitches);
    #   apply_registration(observations, registration); info.registration = registration.
    #   If verify_pass: errors.extend(await verify_rows(image, observations, planogram, catalog,
    #   backend, semaphore)). Bounded by "Decided details"; registration is deterministic/no LLM.
    raise NotImplementedError
```
**Why this shape**: `asyncio.gather(_prices(), identify_rows(...))` is the "prices ‖ identify" of the
spec skeleton. `read_prices` reports per-row LLM failures through `errors=`; the wrapper only converts an
unexpected exception into exactly one error string. The "no rows" branch returns early with `registration=None` — that is what "reported
unregistered and the run continues" means. The LLM is never given `facing_id`: only
`register_image`/`apply_registration` set it (spec §5).

### `examples/planogram/plancheck/pipeline.py` (CREATE) — part 3/3
```python
async def run_check(settings: Settings, *, backend_factory: Callable[..., Any] | None = None) -> ComplianceReport:
    """Run the whole compliance check and write the report.

    Args:
        settings: Run settings (paths may be relative; they are absolutized first).
        backend_factory: Test seam. ``factory(llm, *, cache_dir, base_url)`` → backend exposing
            ``ask(...)`` and ``is_local``. ``None`` uses :class:`VisionBackend`.

    Returns:
        The report that was written to ``settings.output``.

    Raises:
        FileExistsError: ``settings.output`` already exists (checked before any work).
        FileNotFoundError / ValueError: Invalid inputs (planogram, catalog, prices, images).
    """
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    settings = absolutize(settings)  # BEFORE any backend construction (first parrot import)
    if Path(settings.output).exists():
        raise FileExistsError(f"Output directory already exists: {settings.output}")
    planogram = load_planogram(Path(settings.planogram))
    catalog, missing = load_catalog(Path(settings.catalog), planogram)
    expected_prices = load_prices(Path(settings.prices)) if settings.prices else None
    factory = backend_factory or _default_backend_factory
    ocr = TagOcr()
    async with contextlib.AsyncExitStack() as stack:
        # FILL IN: build ``backend`` = factory(settings.llm, cache_dir=Path(settings.cache_dir),
        #   base_url=settings.base_url); ``ocr_backend`` = the same object unless settings.ocr_llm is
        #   set AND differs (then a second factory call). Enter each through
        #   ``stack.enter_async_context`` ONLY when it has ``__aenter__`` (FakeBackend has none).
        #   Then: verify_pass = resolve_verify_pass(settings.verify_pass, backend.is_local);
        #   semaphore = asyncio.Semaphore(effective_concurrency(settings.concurrency, backend.is_local));
        #   run _process_image for every image (image_id = f"image_{n:02d}", 1-based) with
        #   asyncio.gather; an Exception from one photo other than FileNotFoundError/ValueError is
        #   appended to errors as f"{image_id}: {exc}" and the run continues.
        #   Bounded by "Decided details" and test_run_check_backend_failure_row.
        raise NotImplementedError
    # FILL IN (after the stack closes): positions = merge_positions(planogram, all_observations,
    #   catalog, settings.weights, expected_prices); build RunInfo (visit_id, planogram_id, llm,
    #   ocr_llm = settings.ocr_llm or settings.llm, effective verify_pass, started/finished,
    #   errors, catalog_missing_skus=missing, reference_provisional, local_ocr_available=ocr.available)
    #   and ComplianceReport(run, images, slots, positions, shelves=shelf_scores(positions),
    #   brands=brand_shares(planogram, positions, all_observations),
    #   compliance=summarize(positions, all_observations, planogram, expected_prices),
    #   notes=[*STANDING_NOTES, *per-image notes, reference-draft note when provisional]);
    #   await asyncio.to_thread(write_report, report, images_by_id, settings,
    #   {"identify": IDENTIFY_PROMPT_VERSION, "verify": VERIFY_PROMPT_VERSION, "prices": PRICE_PROMPT_VERSION});
    #   return report.
```
**Why this shape**: `absolutize` is the very first statement so nothing relative survives the parrot
`chdir`. The early `exists()` guard makes "existing `--output` writes nothing" cheap (no LLM call is
spent); `write_report` still guards at write time. `AsyncExitStack` lets real backends be context-managed
while the fake is used bare. Scoring runs once over the observations of **all** photos — that is the
multi-photo merge of spec §2 stage 8.

### `examples/planogram/tests/test_plancheck_pipeline.py` (CREATE)
```python
"""Integration tests for plancheck.pipeline (FEAT-565, TASK-3349) — no network, synthetic data only."""
from __future__ import annotations

import json
import re
from pathlib import Path

import cv2
import numpy as np
import pytest

import plancheck.pipeline as pipeline
from plancheck.models import ComplianceReport, RowReading, Settings, SlotReading
from plancheck.pipeline import absolutize, effective_concurrency, resolve_verify_pass, run_check

SLOT_ID = re.compile(r'"slot_id"\s*:\s*"([^"]+)"')   # the identify prompt embeds a JSON list of slot ids
SLOT_PARTS = re.compile(r"_r(\d+)_s(\d+)$")            # slot_id = f"{image_id}_r{row:02d}_s{index:02d}"


class _FakeOcr:
    """Stands in for TagOcr so RapidOCR never loads; every tag reads a full price."""
    available = True

    def read(self, crop: np.ndarray) -> str:
        return "$9.99"


def _reader(fail_rows: frozenset[int] = frozenset()):
    """Return a FakeBackend callable answering pass 1 from the slot ids found in the prompt."""
    def _answer(prompt: str, images: list[bytes]) -> RowReading:
        # FILL IN: for every slot id in SLOT_ID.findall(prompt) build a SlotReading(occupancy="occupied",
        #   visibility="full", brand/family/xl/colors per conftest's mini_catalog rule for (row, index),
        #   visible_text=[the synthetic SKU "AC-<row><index>" / "BO-<row><index>"]); row 3 index 6 is the
        #   CLOSEOUT slot → brand None, no text. Raise RuntimeError("boom") when the row is in fail_rows.
        raise NotImplementedError
    return _answer


def _settings(tmp_path: Path, image: np.ndarray, planogram_data: dict, catalog, n_images: int = 1) -> Settings:
    # FILL IN: cv2.imwrite n_images PNG copies, json-dump planogram_data and
    #   catalog.model_dump(mode="json") into tmp_path; return Settings(images=[...], planogram=...,
    #   catalog=..., output=str(tmp_path / "out"), cache_dir=str(tmp_path / "cache"), verify_pass=False).
    raise NotImplementedError


def test_verify_pass_auto_default() -> None:
    assert resolve_verify_pass(None, is_local=False) is True
    assert resolve_verify_pass(None, is_local=True) is False
    assert resolve_verify_pass(True, is_local=True) is True
    assert resolve_verify_pass(False, is_local=False) is False
    assert effective_concurrency(4, is_local=True) == 1 and effective_concurrency(4, is_local=False) == 4


def test_absolutize_resolves_relative_paths(tmp_path, monkeypatch) -> None:
    # FILL IN: monkeypatch.chdir(tmp_path); Settings with relative paths → every path field absolute,
    #   prices stays None, non-path fields unchanged.
    raise NotImplementedError


@pytest.mark.asyncio
async def test_run_check_synthetic_end_to_end(tmp_path, monkeypatch, shelf_image, mini_planogram_data,
                                              mini_catalog, fake_backend) -> None:
    # FILL IN: monkeypatch.setattr(pipeline, "TagOcr", _FakeOcr); fake_backend.queue["identify"] =
    #   [_reader()] * 20; report = await run_check(settings, backend_factory=lambda llm, **kw: fake_backend).
    #   Assert: run.errors == []; the 3 rows registered to shelves [1, 2, 3]; every identity-required
    #   facing of shelves 1–2 is "match" via "direct"; compliance.strict_pct is not None;
    #   compliance.json / annotated_image_01.jpg / slots/ / tags/ / run.snapshot.json exist;
    #   no "verify" call was made (verify_pass=False); prices are "read" from OCR (no "prices" call).
    raise NotImplementedError


@pytest.mark.asyncio
async def test_run_check_two_overlapping_photos(tmp_path, monkeypatch, shelf_image, mini_planogram_data,
                                                mini_catalog, fake_backend) -> None:
    # FILL IN: n_images=2 (same synthetic view twice). Assert len(report.positions) == number of
    #   planogram facings (19, not 38); matched facings list slot_ids from BOTH images; strict_pct
    #   equals the single-photo value (agreeing views count once, no double counting).
    raise NotImplementedError


@pytest.mark.asyncio
async def test_run_check_backend_failure_row(tmp_path, monkeypatch, shelf_image, mini_planogram_data,
                                             mini_catalog, fake_backend) -> None:
    # FILL IN: queue = [_reader(fail_rows=frozenset({2}))] * 20. Assert: run completes and returns a
    #   ComplianceReport; run.errors is non-empty (→ exit code 2 in the CLI); shelf-2 facings are
    #   "not_assessed" (never "empty"); all artefacts are still written.
    raise NotImplementedError
```
**Why this shape**: the reader answers from the prompt, so the test is independent of the order in
which concurrent rows reach the fake. `_FakeOcr` is patched onto `plancheck.pipeline.TagOcr` because
`run_check` instantiates it by that name. `verify_pass=False` in `_settings` keeps pass 2 out of the
two happy-path tests; the helper test covers the auto default. The three `test_run_check_*` names are
fixed by spec §4.

### FILL IN checklist
- [ ] `pipeline.py::absolutize` — resolve all path fields; bounded by `test_absolutize_resolves_relative_paths`
- [ ] `pipeline.py::_process_image` — pitches (+ inherited pitch), register, apply, optional verify
- [ ] `pipeline.py::run_check` (inside the stack) — backends, semaphore, verify default, per-image gather + failure isolation
- [ ] `pipeline.py::run_check` (after the stack) — merge/score, `RunInfo`, `ComplianceReport`, `write_report` via `to_thread`
- [ ] `test_plancheck_pipeline.py::_reader`, `_settings` and the four FILL IN test bodies

---

## Acceptance Criteria

- [ ] `run_check` runs stages in the spec order and returns the written `ComplianceReport`.
- [ ] Paths are absolutized before any backend is constructed; `pipeline.py` never imports `parrot`.
- [ ] Concurrency is 1 on local backends; `verify_pass=None` → on (cloud) / off (local); explicit values win.
- [ ] Prices and pass 1 run concurrently per image; `obs.price` is filled for every observation.
- [ ] A photo without tag rows yields `registration=None`, a note, and the run continues.
- [ ] A failing row ends with a complete report and non-empty `run.errors`; its facings are `not_assessed`.
- [ ] Two photos of the same facings yield one `PositionResult` per facing.
- [ ] An existing `settings.output` raises `FileExistsError` before any backend call.
- [ ] `RunInfo.reference_provisional`, `catalog_missing_skus`, `local_ocr_available` and effective `verify_pass` are populated.
- [ ] No `print(`; `ruff check examples/planogram/plancheck/pipeline.py examples/planogram/tests/test_plancheck_pipeline.py` clean.
- [ ] All tests pass: `pytest examples/planogram/tests/test_plancheck_pipeline.py -q`

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest examples/planogram/tests/test_plancheck_pipeline.py -q`

---

## Test Specification

Fixed names (spec §4): `test_run_check_synthetic_end_to_end`, `test_run_check_two_overlapping_photos`,
`test_run_check_backend_failure_row`, `test_verify_pass_auto_default`; plus
`test_absolutize_resolves_relative_paths`. Scaffold and bounds are in the blueprint's test block.
In a worktree prefix the command with
`PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-client-google/src:packages/ai-parrot-client-local/src`
(harmless here — these tests never import parrot).

---

## Agent Instructions

1. **Read the spec** (§2 Overview + Component Diagram, §3 Module 12, §4 Integration Tests, §7).
2. **Check dependencies** — all ten `Depends-on` tasks must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract**: open each sibling module and confirm the signature listed above;
   if one differs, update this contract FIRST (never adapt silently), then implement.
4. **Update status** in `sdd/tasks/index/new-planogram-compliance-algo.json` → `"in-progress"`.
5. **Implement** from the blueprint; complete every `# FILL IN:`; never change a fixed signature or path.
6. **Verify** all acceptance criteria and run the validation command.
7. **Move this file** to `sdd/tasks/completed/TASK-3349-pipeline.md` and set the index entry to `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-coder (backend nova, model zai.glm-5, attempt_uid 98a57d6a6c044baf95551e89a25be559)
**Date**: 2026-09-18
**Notes**: Created `examples/planogram/plancheck/pipeline.py` (run_check orchestrating
stages 1-8, resolve_verify_pass, effective_concurrency, absolutize, `_process_image`
with AsyncExitStack backend lifecycle and shared semaphore concurrency control) and
`examples/planogram/tests/test_plancheck_pipeline.py` with all 5 blueprint-named tests
(verified none disabled/renamed). `ruff check` clean. Engine lint autofix commit
`f64cc2177`. Post-merge full suite → 112 passed. Review recorded:
`coder-review:d634e4a5bf1be864a3ae1df7`, no corrections needed.

**Seat**: glm5 · Backend: nova · Model: zai.glm-5 · Attempts: 1 · Duration: 369.7s · Tokens: 1838672/8845

**Deviations from spec**: none
